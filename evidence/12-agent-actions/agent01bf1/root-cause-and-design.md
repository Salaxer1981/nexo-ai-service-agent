# AGENT-01BF1 — Exact-version confirmation and authoritative cancellation

Baseline: `8507448` (AGENT-01B). Codex audit: FAIL (0 BLOCKER, **2 HIGH**, 0 MEDIUM, 5 LOW, 3 INFO).
- **Tests:** REAL PostgreSQL 17.11 + pgvector 0.8.7 (local); TEST-ONLY scripted model; **FakeN8n** = TEST stand-in, NOT n8n.
- **No live OpenRouter call** was made for this fix.
- **Preserved:** the previous AGENT-01B evidence is unchanged.

## AGENT01B-01 (HIGH): a confirmation could execute a version the user never approved
**Root cause.** `confirm()` executed *whatever action the conversation pointer named once the command lock was
acquired*. Nothing tied the user's CONFIRMAR to the summary they had seen, which allowed two failures:
- **Concurrent correction:** the CONFIRMAR for A waits on the lock while a correction turn re-prepares B and moves the
  pointer → B executes.
- **Lost response:** B was prepared but its summary never reached the user → the user, still looking at A, sends
  CONFIRMAR → B executes.

**Reproduced on 8507448** (`old-semantic-proof.txt`): the user approved priority *normal*, and the old code created the
**critical** version.

**Why server-side admission capture alone is not enough.** In the lost-response case B *is* the authoritative state when
the CONFIRMAR arrives. Only the client knows which summary it displayed, so the binding must come from the client.

**Fix: `confirmation_token`** = `sha256("nexo:chat_confirm:v1:<action_id>:<payload_hash>")[:16]`.
- **Shown with the summary:** every awaiting-confirmation response carries it (`pending_action.confirmation_token`,
  `next_step.confirmation_token`). The human protocol is still "responde CONFIRMAR"; the client echoes the token of the
  summary it displayed (`{"message": "CONFIRMAR", "confirmation_token": …}`).
- **Checked under the lock:** on CONFIRMAR, the state is re-read under the conversation lock, and the presented token
  must equal the token of the current pointer (same kind, same action id, same payload hash).
- **Mismatch or missing token ⇒ fail closed:** `confirmation_review_required`, «no he ejecutado nada», and the
  **current** summary plus its token are shown for review. Nothing executes until the user confirms that version.
- **Not a credential:** the token names a version. Identity is still the bearer token, and the services still re-check
  ownership, status, expiry and payload fingerprint.
- **Unchanged:** the deterministic gate, no model call, the idempotency key `chat:<conversation>:<action>`, replay
  (the same token replays the same object).
- **Audit:** an admission snapshot (`admitted_revision`) is recorded, but **never** used to decide what to execute.

**Stale model proposals (section 4).** `chat_conversations.revision` (migration 0009) increments on every state change.
1. An interpretation turn records the revision it read: it reads state, commits (no transaction is open during the
   OpenRouter call), then calls the model.
2. `propose()` publishes a draft or re-prepare only if the revision is unchanged under the lock.
3. Otherwise the result is `conversation_changed` («No he aplicado este mensaje»): nothing is published.
4. Read paths never change the revision.

**Defense in depth (Codex note).** The pointer is dereferenced only with **customer AND conversation AND action id**
(`action_fields`, `action_status`). A pointer to another conversation's action fails closed (`confirmation_invalid`)
without calling any service. The service APIs are unchanged.

## AGENT01B-02 (HIGH): cancellation could claim success from stale chat state
**Root cause.** `cancel()` summed the service's `cancel()` results but then decided its answer from the *cached*
conversation state (`st.action_status == "pending"`). If a plain-API confirmation consumed the action first, the
service cancel affected 0 rows, yet chat marked the conversation `cancelled` and said «No se ha creado ningún ticket».

**Reproduced on 8507448:** the answer was «He cancelado… No se ha creado ningún ticket», while 1 ticket was created and
the chat state was `cancelled`.

**Fix.** Under the conversation lock:
1. Attempt the owner-scoped service cancel on the pointed action (plus any other pending action of the conversation).
2. **Success only if that call moved the action pending → cancelled** (1 row). Only then is the state set to `cancelled`
   and «con ella no se ha creado ningún ticket ni solicitud» said.
3. Otherwise re-read the **authoritative** action status (customer + conversation scoped):
   - `consumed` → `already_completed`, with the created object (ticket id + `T-` reference, or lead id). The state
     becomes `completed`; «La acción ya se había completado… no puede cancelarse. No he borrado ni modificado nada.»
   - `confirmed` (lead handed to n8n) → `cannot_cancel`.
   - `superseded` / `expired` / `cancelled` → `not_pending`; the state is cleared; «con ella no se ha creado nada»
     (true: the action never reached `consumed`).
   - not found → `not_pending`; nothing done.
4. A created ticket or lead is never deleted or reversed.

## Race outcome matrix (all deterministic, REAL PostgreSQL)
| Race | Mechanism | Outcome (tested) |
|------|-----------|------------------|
| C: re-prepare vs CONFIRMAR (ticket, lead) | CONFIRMAR(A) admitted and **waiting** on the conversation lock (seen in `pg_locks`); the lock holder re-prepares B exactly as `propose()` would | `confirmation_review_required`, B shown with its own token, **neither A nor B created**, B still `pending`; then CONFIRMAR with B's token → B created (once) |
| Lost re-prepare response (ticket, lead) | B prepared; its response discarded; CONFIRMAR with A's token or no token | review required both times; B shown, not executed; 0 objects, 0 workflow calls |
| D: plain-API confirm vs chat CANCELAR (ticket) | hook: API `/tickets/confirm` commits between CANCELAR's state load and its cancel attempt | `already_completed` with the API's ticket id; exactly 1 ticket; state `completed` (not `cancelled`); a later CONFIRMAR returns the same ticket |
| Workflow completion vs chat CANCELAR (lead, FakeN8n) | hook: API `/leads/confirm` → FakeN8n → `/internal/leads` commits before CANCELAR's cancel attempt | `already_completed`; exactly 1 lead, still present; state `completed`; «No he borrado ni modificado nada» |
| A: chat CONFIRMAR vs chat CANCELAR | both queued on the conversation lock while it is held | exactly one wins: either (ticket created + `already_completed` for the same id) or (`cancelled` + `nothing_pending`); never both, never a false success |
| B: re-prepare vs CANCELAR | CANCELAR commits while the model interprets a correction (revision N → N+1) | `conversation_changed`, nothing re-prepared, 0 pending |
| C (reverse): CONFIRMAR during interpretation | CONFIRMAR executes A while the model interprets a correction | `conversation_changed`; no re-prepare of a completed action |
| re-prepare then CANCELAR (sequential) | | the **current** version is cancelled (old `superseded`, new `cancelled`); CONFIRMAR → nothing |
| superseded / expired action + CANCELAR | | `not_pending`, truthful, 0 objects |
| forged token, another conversation's token, other customer | | review required / `nothing_pending`; 0 objects; non-hex token → 422 |
| pointer to another conversation's action | | `confirmation_invalid`, service not called, action stays `pending` |

Preserved (full suite 393 passed): deterministic gate, no model call on CONFIRMAR/CANCELAR, idempotent replay, 8-way /
6-way duplicate protection, the serialization lock, customer isolation, T-reference scoping, n8n-only lead creation,
the cancelled terminal status, changed-data re-prepare, critical handoff, injection controls, read-only informational
paths.
