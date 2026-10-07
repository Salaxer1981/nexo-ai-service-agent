# AGENT-01BF3 — Atomic authoritative check + re-prepare; cancellation ordering

Baseline: `c693a5a` (AGENT-01BF2). Codex: FAIL with AGENT01BF2-01 (**HIGH**, TOCTOU) and AGENT01BF2-02 (LOW).
- **Tests:** REAL PostgreSQL 17.11 + pgvector 0.8.7 (local); TEST-ONLY scripted model; **FakeN8n** = TEST stand-in, NOT n8n.
- **No live call, no migration.**
- **Only one source file changed:** `src/backend/app/chat_actions.py`. APP-02/APP-03B services are unchanged.
- **Preserved:** the earlier evidence is unchanged.

## AGENT01BF2-01 (HIGH): TOCTOU between the authoritative check and the re-prepare
**Root cause.** BF2's `reconcile()` read A's status with a plain `SELECT` on an autocommit connection. The read and the
following `prepare()` ran in **separate transactions** and A was **not row-locked**:
1. reconcile reads A = `pending`;
2. a plain-API confirmation (its own transaction) consumes or confirms A;
3. chat continues into `prepare()`, whose supersede `UPDATE … WHERE status = 'pending'` no longer matches A;
4. B is inserted and becomes the pointer → "A consumed AND B pending".

**Reproduced on c693a5a** (`f3-tests-vs-c693a5a.txt`, `f3-proposal-wins-vs-c693a5a.txt`):
- **Confirm-wins (ticket and lead):** the stale proposal published B (`awaiting_confirmation`) after A was
  consumed/confirmed.
- **Proposal-wins:** the plain API did **not** wait (`api_waited = False`); it ran through the gap.

**Fix: one transaction, row-locked** (`propose()`, under the existing conversation advisory lock):
```
read state + revision basis → COMMIT → model call (NO transaction, NO locks held)
→ conversation advisory lock
→ BEGIN
   → load conversation state
   → prepare-group advisory xact lock (service.prepare_lock_key: the SAME lock the service prepare takes first)
   → SELECT status … FROM pending_*_actions WHERE id AND owner AND conversation_id FOR UPDATE   ← A locked
   → authoritative recheck: not 'pending' ⇒ synchronize chat state, reject (no B)
   → revision check
   → service.prepare(conn, …)   (its own `with conn.transaction()` is now a SAVEPOINT: supersede A + INSERT B)
   → publish B into chat_conversations
→ COMMIT (row + advisory xact locks released)
```
- **No service refactor:** the existing service `prepare()` participates through psycopg nested transactions.
- **No duplicated rules:** the advisory key comes from the service's own `prepare_lock_key`.
- **No gap:** any route that wants to consume or confirm A (`ticket_actions.confirm` and `leads.begin_confirm` both
  `SELECT … FOR UPDATE` A) **waits** until the proposal commits or rolls back. If such a route locked A first, the
  proposal waits, and then sees the committed `consumed`/`confirmed` status.

## Lock-order / deadlock assessment
| Path | Order |
|------|-------|
| chat proposal (new) | conversation advisory → prepare-group advisory xact → A row (FOR UPDATE) → supersede/INSERT B |
| API `POST /tickets/prepare` / `/leads/prepare` | prepare-group advisory xact → pending rows (UPDATE) → INSERT |
| API/chat confirm (`ticket_actions.confirm`, `leads.begin_confirm`) | A row only (FOR UPDATE) |
| `internal_create` (n8n writer) | A row only |
| chat CONFIRMAR/CANCELAR | conversation advisory → (service: A row) |

- **Group advisory before row lock:** the chat path takes the group advisory lock before A's row lock, exactly like the
  API prepare path. Taking the row lock first would allow a cycle with a concurrent API prepare (advisory → rows).
- **Confirm paths take only the row lock,** so no cycle exists.
- **Tested:** 5 rounds of a chat re-prepare and an API prepare started together on one conversation (barrier) → no
  deadlock or error, exactly one pending action each time.
- **APP-02/APP-03B lock order is unchanged.**

## AGENT01BF2-02 (LOW): other pending actions were cancelled before pointer validation
**Root cause.** BF2 validated the pointer membership only inside the pointer branch, after the loop that cancels the
conversation's *other* pending actions. Reproduced on c693a5a: with Y's pointer corrupted to X and a valid pending
action Z in Y, CANCELAR called `ticket_actions.cancel(Z)` before failing on X.

**Fix (order):**
1. Validate the pointer (customer AND conversation AND action). If invalid: clear the corrupted chat pointer (chat state
   only), answer `not_pending` «no he cancelado ni ejecutado nada», **zero cancel-service calls**.
2. Advance the revision (`_touch`) before the first business mutation.
3. Only then cancel the other pending actions, then the pointed one, with BF1's authoritative cancellation
   (0 rows ≠ success).

## Proofs (deterministic: observed lock waits in pg_locks, bounded polling; no sleep decides an outcome)
| Test | Result |
|------|--------|
| ticket: proposal wins | the hook pauses the proposal **after** it row-locked A; the plain-API `/tickets/confirm` is observed **waiting**; the proposal commits B (A `superseded`); the API then answers 409 `confirmation_invalid`; statuses `[superseded, pending]`; 0 tickets |
| lead: proposal wins | same with `/leads/confirm`; API 409 `confirmation_invalid`; **0 FakeN8n calls**; 0 leads |
| ticket: confirm wins | a test transaction runs the real `ticket_actions.confirm` on A (row locked, uncommitted); the chat proposal (model output already computed from "A pending") is observed **waiting**; after COMMIT: `already_completed`, **no B**, chat synchronized to completed A; 1 ticket |
| lead: confirm wins | a test transaction runs the real `leads.begin_confirm` (chat key) on A; proposal waits; after COMMIT: `action_in_progress`, **no B**, pointer A kept; CONFIRMAR later redispatches through the (TEST) workflow → lead created; 1 lead |
| lock order | 5× concurrent chat re-prepare + API prepare: no deadlock, 1 pending |
| X/Z cancel | Y → X corrupted, Z valid in Y: `not_pending`, **0 cancel calls**, X and Z still `pending` |
| revision before mutation | cancel commits, then the chat sync fails (503): the revision already advanced |

**BF1/BF2 regressions under the new transaction:** all 15 BF1 and 8 BF2 tests pass, including:
- ticket commit + lost response (T1);
- lead confirmed + n8n failure (T2);
- plain-API completion during the model call (T3, ticket and lead);
- cross-conversation cancel (T4/T5);
- re-prepare vs confirm, and the lost re-prepare response;
- API confirm vs cancel, lead completion vs cancel, confirm vs cancel.
