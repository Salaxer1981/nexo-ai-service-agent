# APP-03AF1 — Fix for APP03A-01 (LOW)

## Audit context (independent Codex audit of `2fd4e2a`; preserved, not rewritten)
Result: **PASS WITH LOWS / SAFE FOR VM VALIDATION**.

> **APP03A-01 LOW:** Invalid or empty supplied `X-Conversation-ID` is normalized to "absent", bypassing the documented
> header/body mismatch rule. Examples: empty header; whitespace-only header; invalid value such as `bad value`.
> Bad behavior: header invalid + body `conversation_id` valid → handoff may be created with 201, and the audit
> `conversation_id` becomes null.

## Root cause
`tracing.py` computed `conversation_id = safe_id(request.headers.get("x-conversation-id"))`. `safe_id` returns `None`
both for a missing header and for an invalid one. `POST /handoffs` only applied the mismatch rule when the value was
not `None`, so "supplied but invalid" was indistinguishable from "absent" and passed.

## Fix (10 lines, no redesign)
- `src/backend/app/tracing.py`: also records `request.state.conversation_header_supplied` (whether the header was present
  at all). It validates the value with the **same** existing rule (`safe_id`: `^[A-Za-z0-9._-]{1,64}$`) after stripping
  outer whitespace. `conversation_id` is still `None` for an invalid value, so the raw value is never echoed into logs.
- `src/backend/app/main.py` (`POST /handoffs`): if the header was supplied but is invalid → **400** `"X-Conversation-ID
  header is invalid …"`, audited as `result: rejected`, `error: InvalidConversationHeader`. This check runs before the
  mismatch check and before the Idempotency-Key is used, so nothing is persisted and the key isn't consumed.
- Authentication, idempotency, the handoff schema and the tracing contract are unchanged.

## Header/body behavior matrix (body `conversation_id` = `conv-header-check`)

| # | `X-Conversation-ID` | Before fix | After fix | Rows |
|---|---------------------|-----------|-----------|------|
| 1 | absent | 201 | **201** | +1 |
| 2 | `conv-header-check` | 201 | **201** | +1 |
| — | `"  conv-header-check  "` | 201 (treated as absent) | **201** (normalized, then equal) | +1 |
| 3 | `conv-different` | 400 mismatch | **400** mismatch | 0 |
| 4 | `""` (empty) | **201** ✗ | **400** invalid | 0 |
| 5 | `"   "` (whitespace) | **201** ✗ | **400** invalid | 0 |
| 6 | `bad value` | **201** ✗ | **400** invalid | 0 |
| — | `bad/value` | **201** ✗ | **400** invalid | 0 |
| — | 65 × `x` | **201** ✗ | **400** invalid | 0 |
| — | invalid header + no auth | 401 | **401** (auth checked first) | 0 |

The "before fix" column is measured, not assumed: the new tests were run against the unfixed `2fd4e2a` code
(`runs.txt`). Exactly cases 4–6 and the other invalid values failed, and so did the "key not consumed" test.

## Traceability for rejected headers
The response still carries `X-Request-ID`; the audit line has `request_id`, `action: handoff_create`, `status: 400`,
`result: rejected`, `error: InvalidConversationHeader` (or `ConversationMismatch`), and **no** `handoff_id` or
`idempotency` field. The raw invalid header value isn't logged (asserted in the test). No secrets are logged.

## Tests (`tests/test_handoff_conversation_header.py`, 12)
Absent / valid-equal / valid-padded accepted; different / empty / whitespace / inner space / slash / too long rejected
with 0 rows and audited; rejected request doesn't consume its Idempotency-Key (the corrected retry → `created`, then
`replay`, same ID); invalid header without auth still 401; ownership unchanged (`X-Customer-Id` ignored).

## Regression (`runs.txt`)
Focused 12/12 · handoff suite 44/44 · APP-01 auth/isolation 24/24 · APP-02 tickets/idempotency/concurrency 55/55 ·
migrations 11/11 · full suite **159 passed, 2 skipped** (×2).

## Observation for the re-audit (not changed: outside this targeted fix)
`POST /tickets/prepare` reads the same `request.state.conversation_id`. A supplied-but-invalid header there still groups
the action with "no conversation" for superseding (the APP02-02 LOW behavior); ownership, confirmation binding and
idempotency are unaffected. Applying the same 400 rule to prepare would be a separate, explicitly authorized change.
