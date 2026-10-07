# Audit findings and remediations

## Process

Each high-risk phase got an **independent targeted audit by Codex**. Findings were fixed in dedicated phases
(`…F1`, `…F2`, `…F3`), each of which:
- reproduced the defect on the **old** commit first (a failing test or proof kept as evidence);
- applied the smallest fix;
- proved the fix with deterministic tests on a real PostgreSQL;
- checked the tests themselves with mutation testing (the fix is undone and the new tests must fail).

A **focused re-audit** decided whether each finding was CLOSED. The final candidate was then validated on the real VM
(real PostgreSQL/pgvector, real n8n, real `x-ai/grok-4.7`) and in a real browser.

**Status meanings:**
- **CLOSED:** fixed and accepted by the re-audit.
- **OPEN:** documented, not fixed. Every HIGH finding is CLOSED; one LOW remains OPEN.

## A. Product findings (chronological)

| ID | Severity | Found in → fixed in | Final status |
|---|---|---|---|
| AGENT01A-01 | LOW | AGENT-01A audit → AGENT-01B | **CLOSED** |
| AGENT01B-01 | **HIGH** | AGENT-01B audit → AGENT-01BF1 | **CLOSED** |
| AGENT01B-02 | **HIGH** | AGENT-01B audit → AGENT-01BF1 | **CLOSED** |
| AGENT01BF1-01 | **HIGH** | BF1 re-audit → AGENT-01BF2 | **CLOSED** |
| AGENT01BF1-02 | LOW | BF1 re-audit → AGENT-01BF2 | **CLOSED** |
| AGENT01BF2-01 | **HIGH** | BF2 re-audit → AGENT-01BF3 | **CLOSED** |
| AGENT01BF2-02 | LOW | BF2 re-audit → AGENT-01BF3 | **CLOSED** |
| AGENT01BF3-01 | LOW | BF3 re-audit | **OPEN (documented, accepted)** |

### AGENT01A-01 (LOW): malformed model metadata not hardened
- **Problem.** The OpenRouter client validated the answer's content but not ancillary metadata such as `usage` (token
  counts and cost).
- **Failure scenario.** A provider or proxy returns a non-numeric `usage.prompt_tokens`. Cost and audit code then
  crashes or records garbage instead of failing cleanly.
- **Root cause.** The response parser trusted metadata types.
- **Fix.** `_usage` validation in `llm.parse_completion`: malformed metadata is treated as invalid output, giving 503
  `llm_invalid_output` with `answer: null`.
- **Verification.** Unit tests; in-container stub matrix on the VM (AGENT-01BV1 §23, "malformed usage") PASS.
- **Status:** CLOSED.

### AGENT01B-01 (HIGH): a confirmation could execute a version the user never approved
- **Problem.** `CONFIRMAR` executed whatever action the conversation pointed to once the lock was acquired.
- **Failure scenario.**
  - The user sees draft A (priority *normal*) and sends CONFIRMAR.
  - Meanwhile a correction turn re-prepares B (*critical*), or B's summary is lost in transit.
  - The ticket **B** is created, but the user approved **A**. Reproduced on `8507448`.
- **Root cause.** Nothing tied the user's CONFIRMAR to the summary they had seen. Only the client knows which version
  it displayed.
- **Fix (AGENT-01BF1).**
  - A **`confirmation_token`** (`sha256("nexo:chat_confirm:v1:<action_id>:<payload_hash>")[:16]`) is returned with
    every summary.
  - The client echoes it with CONFIRMAR, and it's re-checked against the current version under the conversation lock.
  - A mismatch or missing token gives `confirmation_review_required` with the current summary; nothing executes.
  - A conversation revision rejects stale model proposals.
- **Verification.** Old-code proof plus new tests; mutation checks; VM: CONFIRMAR with A's token while B is current
  gives review with B's summary and no ticket (AGENT-01BV1 §21); browser: a stale draft has no buttons, and an unbound
  CONFIRMAR gives review (UI-02 #9).
- **Status:** CLOSED (re-audit).

### AGENT01B-02 (HIGH): cancellation could claim success from stale chat state
- **Problem.** CANCELAR decided its answer from cached chat state.
- **Failure scenario.** A plain-API confirmation consumes the action just before CANCELAR. The service cancel affects 0
  rows, yet chat answers «He cancelado… No se ha creado ningún ticket» while a ticket exists. Reproduced on `8507448`.
- **Root cause.** The answer didn't depend on the authoritative outcome of the cancel.
- **Fix (BF1).** Success only if the call moved the action from pending to cancelled (1 row). Otherwise the
  authoritative status is re-read: `consumed` gives `already_completed` with the real object, and an in-flight lead
  gives `cannot_cancel`.
- **Verification.** Tests (API-confirm-wins race); VM S4 (`already_completed`); VM and browser: cancelling a completed
  ticket or lead gives `already_completed` (AGENT-01BV1 §21; UI-02 #10).
- **Status:** CLOSED.

### AGENT01BF1-01 (HIGH): a stale proposal could replace a recovery pointer
- **Problem.** BF1 rejected stale proposals only by the conversation revision, which changes only when chat's own save
  succeeds.
- **Failure scenarios.**
  - Ticket A commits, then the chat sync fails.
  - Lead A goes confirmed, then n8n fails.
  - A plain-API confirmation completes A.

  In each case a correction interpreted at the old revision prepared B and replaced A's pointer, losing the replay or
  recovery handle. For leads, a second action appeared next to the in-flight one. Reproduced on `0b4f6c8`.
- **Root cause.** The chat cache was treated as authoritative instead of the business action row.
- **Fix (AGENT-01BF2).** `reconcile()` re-reads the pointed action (customer + conversation + action) before publishing
  any proposal. A completed action gives `already_completed`; an in-flight lead gives `action_in_progress` (the pointer
  is kept). Confirm and cancel advance the revision **before** any business mutation.
- **Verification.** Tests T1–T3 plus the in-flight case; mutation checks; VM n8n failure → same-action recovery
  (AGENT-01BV1 §18; UI-02 #13).
- **Status:** CLOSED.

### AGENT01BF1-02 (LOW): CANCELAR mutated before proving conversation membership
- **Problem.** The owner-scoped cancel ran before checking that the pointed action belonged to this conversation.
- **Failure scenario.** A corrupted pointer in conversation Y to an action in conversation X (same customer) cancels X.
- **Fix (BF2).** Dereference with customer + conversation + action first. If invalid, clear the corrupted pointer and
  answer `not_pending` with **zero** cancel calls.
- **Verification.** Tests T4/T5 (spied: zero calls); VM S5.
- **Status:** CLOSED.

### AGENT01BF2-01 (HIGH): time-of-check/time-of-use gap between the authoritative read and the re-prepare
- **Problem.** `reconcile()` read A's status, and the following `prepare()` ran in a **separate** transaction with no
  row lock.
- **Failure scenario.** Reconcile sees A pending, a plain-API confirmation consumes A, then prepare supersedes nothing
  and inserts B. The result is "A consumed **and** B pending". Reproduced on `c693a5a`.
- **Root cause.** The check and the act were not atomic.
- **Fix (AGENT-01BF3).** `propose()` is **one transaction**. It takes the prepare-group advisory lock, then
  `SELECT … FOR UPDATE` on A, rechecks, runs the service prepare as a savepoint, publishes, and commits. The lock order
  matches the API prepare path (no deadlock), and the model call stays outside any transaction.
- **Verification.** Deterministic tests with observed lock waits (proposal-wins and confirm-wins, for ticket and lead);
  5 rounds of concurrent re-prepare with no deadlock; mutations H1–H5 caught; 408 passed. VM: AGENT-01BV1 139/139.
- **Status:** CLOSED.

### AGENT01BF2-02 (LOW): CANCELAR cancelled other pending actions before validating the pointer
- **Fix (BF3).** The order is now: validate the pointer, then advance the revision, then cancel other pending actions,
  then cancel the pointed action.
- **Verification.** X/Z test: a corrupted pointer gives `not_pending` and **0** cancel calls; X and Z stay pending.
- **Status:** CLOSED.

### AGENT01BF3-01 (LOW): `_touch()` creates no row when no conversation row exists
- **Problem.** The "advance revision before mutation" helper updates an existing `chat_conversations` row but doesn't
  create one.
- **Impact.** For a conversation that never had a chat-state row, the early revision bump is a no-op. That only
  affects the secondary concurrency signal. The authoritative recheck from AGENT01BF1-01 still protects correctness.
- **Decision.** Documented as a known LOW. The VM run and the browser E2E exposed no blocker from it.
- **Status:** **OPEN**.

## B. Test-harness and infrastructure defects (not product defects)

| Run | What happened | Classification | Correction |
|---|---|---|---|
| AGENT-01AV1 run 1 | The in-container suite couldn't import `app`: a script file puts its own folder on `sys.path` | Harness | `-e PYTHONPATH=/srv`; faithful local dry run; run 2 accepted 129/129 |
| AGENT-01BV1 run 1 | **Rejected.** The lost-response test crashed (`AttributeError`): the driver's `http()` helper shadowed the `http` module, so the scenario never ran | Harness | `import http.client as httpclient` plus a scan for other name collisions; run 2 accepted 139/139 |
| UI-02 run 1 | **Rejected.** The owner's SSH session was reset by the network right after setup (21/21 checks passed); no browser test ran. With no disconnect handling, the stack and secrets stayed on the VM | Infrastructure + harness | Recovery cleanup; rerun with SSH keepalives, ignored SIGPIPE, and a control-endpoint heartbeat that triggers automatic teardown if the session is lost |
| UI-02 cleanup v1 | **Failed.** Its `pkill -f` pattern matched its own command line, so it killed itself before cleaning | Harness | v2: a regex-bracket pattern plus explicit self/parent exclusion; verified 0 containers, volumes, processes and listeners, and the work dir removed |
| UI-02 run 2 | **Accepted.** 28/28 harness checks; 23 browser scenarios; full teardown | — | — |
| UI-02 (browser) | The page-side request recorder couldn't hook `fetch`: the extension's JavaScript runs in an isolated world and the CSP blocks inline scripts. The window couldn't be resized | Automation limits | Token transport proven from backend behaviour and audit lines; responsive checked on identical code locally (labelled TEST) |
| FINAL-01 | Two `tests/test_compose.py` tests still expected the pre-UI-02 service and network sets | Stale test expectations (the runtime was VM-validated) | Updated to the validated topology, plus 2 new static guards for `web`; suite 410 passed / 8 skipped |

Every rejected run is kept as evidence (`vm-run1-*.txt`), never presented as passed.
