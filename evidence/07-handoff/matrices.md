# APP-03A — Handoff authorization, idempotency and contract matrices

Sources: `pytest-focused.txt` (32 passed), `database-and-trace-evidence.txt`, `mutation-and-repeats.txt`.
All against a real throwaway PostgreSQL 17.11. "Handoffs Δ" = change in `handoffs` row count.

## Requirements decision: no separate user confirmation step
The PDF requires confirmation before creating a **ticket** (§4B, REQ-CONF-01/02) and a **lead** (§4C, REQ-CONF-03).
§4E (human escalation) and the test matrix (REQ-TEST-06: "escalation persisted and status pending") require none,
so the prepare/confirm flow is **not** copied. Handoffs are protected by authentication, validation and idempotency.

## Authorization matrix (`POST /handoffs`)

| # | Caller | Input | HTTP | Result | Handoffs Δ | Test |
|---|--------|-------|------|--------|------------|------|
| 1 | token A | valid body (each of 3 reasons) | 201 | `customer_id: CUSTOMER_A`, `status: pending`, real UUID | +1 | `test_valid_handoff_persists_pending_for_authenticated_customer[*]` |
| 2 | token B | valid body | 201 | `customer_id: CUSTOMER_B` | +1 | `test_spoofed_customer_id_cannot_override_auth` |
| 3 | token A | body with `customer_id: CUSTOMER_B` | 422 | unknown field refused | 0 | same |
| 4 | token A | `?customer_id=CUSTOMER_B` + `X-Customer-Id: CUSTOMER_B` | 201 | owner still `CUSTOMER_A` | +1 | same |
| 5 | token A | body with `status` / `assigned_to` | 422 | client can't set status or assignee | 0 | `test_status_cannot_be_set_by_client` |
| 6 | none / invalid bearer / `Basic` | valid body | 401 | — | 0 | `test_missing_or_invalid_auth_is_rejected[*]` |
| 7 | token A | invalid reason / empty or >2000-char summary / bad conversation_id | 422 | — | 0 | `test_invalid_fields_are_rejected[*]` |
| 8 | token A | `X-Conversation-ID` ≠ body `conversation_id` | 400 | — | 0 | `test_conversation_header_must_match_body` |
| — | DB | `UPDATE handoffs SET status='in_progress'` | — | `CheckViolation` | — | `test_status_cannot_be_set_by_client` |

## Idempotency matrix
Uniqueness: database constraint `UNIQUE (customer_id, idempotency_key)` on the handoff row itself.
`request_hash` = SHA-256 of `{op: "handoff_create", conversation_id, reason, summary (NFC, trimmed)}`.

| # | Scenario | HTTP | `Idempotency-Outcome` | Handoffs Δ | Test |
|---|----------|------|-----------------------|------------|------|
| A | First request, key K | 201 | `created` | +1 | `test_same_key_same_request_replays_without_duplicate` |
| B | Same K + same request (×2, and whitespace-padded summary) | 201, identical body | `replay` | 0 | same |
| C | Same K + different reason / summary / conversation_id | **409** `idempotency_key_conflict` (original ID not revealed) | `conflict` | 0 | `test_same_key_different_request_conflicts[*]` |
| D | Same K used by CUSTOMER_A and CUSTOMER_B | 201 / 201, different IDs | `created` each | +1 each | `test_keys_are_scoped_per_customer` |
| E | 6 concurrent requests, same K (separate connections) | — | 1 `created` + 5 `replay`, one ID | **+1** | `test_concurrent_same_key_creates_one_handoff` |
| F | Committed, response lost (exception after commit → 500), retry K | 201, same ID | `replay` | 0 on retry | `test_retry_after_lost_response_returns_same_handoff` |
| G | Missing / empty / invalid key | 400 | — | 0 | `test_missing_or_invalid_idempotency_key_is_rejected[*]` |
| H | DB failure inside the transaction (trigger raises after INSERT) | 503 "retry with the same Idempotency-Key" | — | **0** (rolled back); retry → 201 `created` | `test_failure_inside_transaction_leaves_no_handoff` |
| I | Database unreachable | 503, no id, no "pending" | — | 0 | `test_database_unavailable_never_reports_success` |

## Status contract (REQ-HANDOFF-03)
- Only status `pending` exists (DB `CHECK`); no assignee or ETA fields exist in the schema or the response.
- `status_message`: *"Registered and pending human attention. It has not yet been picked up by a person; no response
  time is guaranteed."* The last clause is consistent with REQ-KB-02 ("no resolution time is guaranteed").
- `test_response_never_claims_a_human_is_attending` checks the response with a forbidden-claims pattern
  ("is attending/handling", "assigned to", "an agent will contact", "in progress", "being handled"). The pattern itself
  is verified to catch such claims (`test_forbidden_claims_detector_works`), and mutation H3 (injecting "A human is
  attending your case") is caught.
- No email or message is sent anywhere (REQ-HANDOFF-04).

## Traceability (audit line per request; example in `database-and-trace-evidence.txt`)
`request_id`, `conversation_id` (header), `handoff_conversation_id` (body), `action: handoff_create`, `reason`,
`handoff_id`, `idempotency: created|replay|conflict`, `result`, `status`, `duration_ms`, `customer_id`.
Never logged: tokens, DB password, `Authorization` header, the **summary text**.

## Mutation checks (`mutation-and-repeats.txt`)
| ID | Mutation | Caught by |
|----|----------|-----------|
| H1 | Request fingerprint ignored (any key reuse replays) | 4 tests (conflict ×3, audit) |
| H2 | Idempotency defeated (key unique per call) | 7 tests |
| H3 | Response claims "A human is attending your case" | `test_response_never_claims_a_human_is_attending` |
| H4 | Owner taken from `X-Customer-Id` header | `test_spoofed_customer_id_cannot_override_auth` |
| H5 | Idempotency-Key not required | 5 tests |
