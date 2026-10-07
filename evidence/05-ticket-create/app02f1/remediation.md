# APP02-01 remediation (APP-02F1)

## Audit finding (as reported by the independent Codex audit of `9ef9823`; preserved, not rewritten)

> **APP02-01 HIGH:** `ticket_actions.prepare` is not serialized per authenticated customer/conversation
> group. Two prepare requests can execute concurrently. Both may perform the supersede UPDATE before
> either has inserted its new pending action. Both then insert a pending action. Result: two pending
> confirmations can coexist for what should be one confirmation scope. If confirmed using different
> idempotency keys, both can create tickets.

Other findings from the same audit (retained, not fixed here): APP02-02 LOW (missing/reused conversation IDs
make same-customer flows supersede each other); APP02-03 INFO (no retention cleanup); APP02-04 INFO (no
connection failure injected exactly around COMMIT); APP02-05 INFO (historical R-13 unexplained).

## Root cause
`prepare()` ran `UPDATE … SET status='superseded' WHERE … status='pending'` followed by `INSERT`. Under
READ COMMITTED each statement sees only rows committed before it started. Two concurrent transactions for
the same group both ran the UPDATE while neither INSERT was committed, so neither saw the other's
row, and both inserted a `pending` action. Nothing in the database forbade two pending actions per group.

**Reproduced** with the original code (variant V0 in `variant-runs.txt`): the deterministic test ended with
both actions `pending`, and a free-running race of 6 concurrent prepares left **3** pending.

## Fix
1. **Serialization (`src/backend/app/ticket_actions.py`):** the first statement of the prepare transaction is
   `SELECT pg_advisory_xact_lock(prepare_lock_key(customer_id, conversation_id))`.
   - Key derivation: SHA-256 of the JSON array `["nexo:ticket_prepare:v1", customer_id, conversation_id]`
     (compact separators, UTF-8), first 8 bytes read as a signed big-endian 64-bit integer. Deterministic
     across processes and restarts (no Python `hash()`); `null` (no conversation) is distinct from any real
     ID. The namespace string separates it from the migration runner's lock key `727001`.
   - Transaction-scoped: released automatically on COMMIT or ROLLBACK; no session state, no app memory.
   - The key is never logged or returned.
2. **Database invariant (`migrations/0004_one_pending_action_per_group.sql`):** partial unique index
   `pending_ticket_actions (customer_id, coalesce(conversation_id, '')) WHERE status = 'pending'`. The
   migration first supersedes all but the newest pending action per group, so it applies to existing data.

## Why it is safe under READ COMMITTED
- The lock is acquired **before** the supersede UPDATE. A second transaction for the same group blocks at
  the lock until the first COMMITs. Its UPDATE is a new statement, which under READ COMMITTED takes a fresh
  snapshot, so it **sees the first transaction's committed pending row and supersedes it**.
- The UPDATE and INSERT therefore never interleave with another prepare of the same group, and every
  order of execution ends with exactly one pending action: the last one committed.
- Different groups use different keys, so they don't wait on each other (proven below). A 64-bit hash
  collision would only serialize two unrelated groups, never change their results, because the UPDATE
  itself is scoped by customer and conversation.
- Independently of code paths, the unique index rejects any second pending row in a group.

## What each layer contributes (variant runs, `variant-runs.txt`)

| Variant | Lock | Index | Same-group deterministic test | 6-way race | DB invariant test |
|---------|------|-------|-------------------------------|------------|-------------------|
| V0 (original APP-02) | – | – | **FAIL: both pending** | **FAIL: 3 pending** | FAIL |
| V1 | – | ✓ | FAIL: second prepare errors (`UniqueViolation`); never 2 pending | FAIL (errors) | pass |
| V2 | ✓ | – | pass | pass | FAIL (no DB invariant) |
| **V3 (this fix)** | ✓ | ✓ | **pass** | **pass** | **pass** |

The lock gives the correct semantics (the newer action supersedes the older one), and the index guarantees
the invariant even if a future code path forgets the lock.

## Deterministic regression test (`tests/test_prepare_concurrency.py`)
A test-only trigger makes each `INSERT INTO pending_ticket_actions` wait on a GATE advisory lock held by the
test. T1 runs `prepare()` and is paused **after** its supersede UPDATE, inside its INSERT: the audited
critical point. T2 then runs `prepare()` for the same group, and the test reads `pg_locks` to see what T2
waits on:
- **fixed:** T2 waits on the **group lock**, i.e. before its UPDATE. After the GATE is released: T1 `superseded`,
  T2 `pending`, exactly 1 pending in the group; confirming T1 → `409 confirmation_invalid` (twice), confirming
  T2 → `201`; ticket count +1.
- **vulnerable (V0):** T2 waits on the GATE (its UPDATE already ran) → both end `pending`.

Waiting is on observable lock states (`pg_locks`), not on sleeps. Also covered:
- different customer / different conversation / no conversation: T2 is **not** blocked by T1's group lock
  and both stay pending (5 iterations each);
- 20 rounds × 6 free-running concurrent prepares → always `{pending: 1, superseded: 5}`;
- the DB index rejects a second pending row (with and without conversation);
- lock key is deterministic, 64-bit, and distinct across customer/conversation groups.

## Repeated runs (`repeated-runs.txt`)
- Concurrent-prepare file: **10/10 runs, 7/7 each**, i.e. 50 deterministic same-group interleavings,
  150 different-group interleavings, 200 six-way races.
- Full suite: **3/3 runs, 115 passed, 1 skipped** (opt-in evidence dump).
- M1–M5 mutation checks against the fixed code: all caught. Under M5 (supersede disabled), the new index
  rejects the second prepare in a group (`503`, audit `error: UniqueViolation`), so a second pending action
  can't exist even with broken code.
- No intermittent failure occurred during this fix (R-13 not observed).
