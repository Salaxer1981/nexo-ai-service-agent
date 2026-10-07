# AGENT-01BF2 — Reconcile authoritative action state before publishing chat proposals

Baseline: `0b4f6c8` (AGENT-01BF1). Focused Codex re-audit: FAIL. AGENT01B-01 and AGENT01B-02 are **CLOSED**.
New findings: AGENT01BF1-01 (**HIGH**) and AGENT01BF1-02 (LOW).
- **Tests:** REAL PostgreSQL 17.11 + pgvector 0.8.7 (local); TEST-ONLY scripted model; **FakeN8n** = TEST stand-in, NOT n8n.
- **No live OpenRouter call.**
- **Preserved:** the earlier evidence (AGENT-01B, BF1) is unchanged.
- **Only one source file changed:** `src/backend/app/chat_actions.py`. The BF1 confirmation token is untouched.

## AGENT01BF1-01 (HIGH): stale proposals could replace a recovery pointer
**Root cause.** BF1 rejected a stale model proposal only by comparing the **conversation revision**. The revision changes
only when chat's own `_save()` succeeds, but the **business action** can leave `pending` without that save:
1. ticket A commits, then the connection fails before chat syncs;
2. lead A goes pending → `confirmed`, then n8n fails (chat saves nothing);
3. a plain-API confirmation completes A.

In each case the revision stayed at N. The correction interpreted at N passed the check, prepared B and replaced A's
pointer: the recovery or replay handle was lost, and for leads a second action appeared next to the in-flight one.

**Reproduced on 0b4f6c8** (`f2-tests-vs-0b4f6c8.txt`): T1, T2, both T3 variants and the in-flight test answered
`awaiting_confirmation`, meaning **a new action B was prepared over the recovery pointer**.

**Fix (business action status is authoritative; the revision is only a concurrency signal):**
1. **Authoritative recheck first.** In `propose()`, under the conversation lock, `reconcile()` re-reads the pointed
   action (customer AND conversation AND action id) **before** anything else, whenever chat believes it is `pending`.
   It changes **chat state only**, never business state:

   | Authoritative status | Chat state | Proposal |
   |----------------------|------------|----------|
   | `pending` | unchanged | may continue (then the revision check) |
   | `consumed` | synchronized to `completed` (pointer to A kept; ticket id + reference / lead id returned) | **rejected**: `already_completed` |
   | `confirmed` (lead in flight) | **pointer to A kept** as the retry/recovery handle | **rejected**: `action_in_progress` + «Responde CONFIRMAR para conocer el resultado» |
   | `cancelled` | synchronized to `cancelled` | rejected: `conversation_changed` |
   | `superseded` / `expired` | cleared | rejected |
   | not found (not this customer's/conversation's) | untouched | rejected, fail closed |

2. **Revision invalidation (secondary).** `confirm()` and `cancel()` advance the revision (`_touch`, autocommit)
   **before** the service may change business state. Even if the final chat save is lost, an interpretation that
   started earlier is stale. This is a signal, not the safety mechanism: a plain-API completion (T3) never touches chat
   state, and only step 1 catches it.
3. **Invariant (section 12).** Once the authoritative action has left `pending`, no proposal can replace its pointer
   with a new prepared action, whatever the revision (tested with a *current* revision too).

## AGENT01BF1-02 (LOW): CANCELAR mutated before proving conversation membership
**Root cause.** `cancel()` called the owner-scoped `ticket_actions.cancel` / `leads.cancel` on the pointed action and
only checked conversation membership afterwards. A corrupted same-customer pointer in conversation Y to an action of
conversation X cancelled X. Reproduced on 0b4f6c8 (T4/T5 answered `cancelled`).

**Fix.** Before any cancel mutation, the pointer is dereferenced with customer AND conversation AND action id (the same
`action_status` helper confirmation uses). If it isn't found, the corrupted chat pointer is cleared (chat state only),
the answer is `not_pending` «no he cancelado ni ejecutado nada», **no service cancel is called** (spied), and X stays
`pending` and can still be confirmed in X.

## Proofs (all deterministic, REAL PostgreSQL; the race runs inside the scripted model call)
| Test | Scenario | Result |
|------|----------|--------|
| T1 | ticket A pending (rev N) → correction waits on the model → user CONFIRMAR A → ticket commits → chat sync fails (503 `action_not_confirmed`) → model returns | `already_completed` with A's ticket id/reference; A `consumed`, **no B**; pointer = A `completed`; CONFIRMAR retry → same ticket; exactly 1 ticket |
| T2 | lead A pending → correction waits → CONFIRMAR A → `confirmed` → FakeN8n fails (503 `lead_not_confirmed`) → model returns | `action_in_progress`; A `confirmed`, **no B**; pointer = A `pending` (retry handle); FakeN8n back → CONFIRMAR → lead created via APP-03B retry; replay same id; exactly 1 lead, exactly 1 lead action |
| in-flight, current revision | lead `confirmed`; a correction with an up-to-date revision | still `action_in_progress`; pointer and single action kept |
| T3 ticket | plain-API `/tickets/confirm` completes A while the model interprets | `already_completed` with the API's ticket; chat synchronized (revision +1); no B; 1 ticket |
| T3 lead | plain-API `/leads/confirm` (FakeN8n) completes A while the model interprets | `already_completed` with the lead; synchronized; no B; 1 lead |
| revision | CONFIRMAR commits but the chat save fails | revision advanced (+1) although chat still says `pending` |
| T4 / T5 | Y's pointer corrupted to X's ticket / lead action; CANCELAR in Y | `not_pending`; **0 service cancel calls**; X stays `pending` (ticket: still confirmable in X) |

## Race matrix (BF1 + BF2)
| Race | Outcome |
|------|---------|
| re-prepare vs CONFIRMAR (ticket, lead) | review required; nothing executed (BF1) |
| lost re-prepare response | review required (BF1) |
| plain-API confirm vs chat CANCELAR (ticket) | `already_completed`; 1 ticket (BF1) |
| workflow completion vs chat CANCELAR (lead) | `already_completed`; 1 lead (BF1) |
| chat CONFIRMAR vs chat CANCELAR | exactly one wins; the loser sees the truth (BF1) |
| successful chat command during interpretation | `conversation_changed` (BF1) |
| **ticket commit + lost chat sync during interpretation** | `already_completed`, pointer kept (BF2 T1) |
| **lead confirmed + n8n failure during interpretation** | `action_in_progress`, retry pointer kept (BF2 T2) |
| **plain-API completion during interpretation** | `already_completed`, synchronized (BF2 T3) |
| **cross-conversation pointer + CANCELAR** | nothing mutated (BF2 T4/T5) |

All prior BF1 race tests pass unchanged (15/15).
