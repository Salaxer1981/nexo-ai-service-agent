# APP-01 — Authorization matrix

Source: `pytest.txt` (60 passed, 0 failed, 0 skipped) against real PostgreSQL 17.11; audit lines in `audit-log-sample.txt`.
Seed tickets: **A** = `a0000000-0000-4000-8000-000000000001` (CUSTOMER_A), **B** = `b0000000-0000-4000-8000-000000000001` (CUSTOMER_B).

## `GET /tickets/{ticket_id}`

| # | Caller credential | Ticket | Extra user-controlled input | HTTP | Body | Audit `result` | Test |
|---|-------------------|--------|-----------------------------|------|------|----------------|------|
| 1 | token A | A | none | **200** | ticket A | `allowed` | `test_customer_a_reads_own_ticket` |
| 2 | token A | B | none | **404** | `{"detail":"Ticket not found"}` | `denied_not_owner` | `test_customer_a_cannot_read_ticket_b` |
| 3 | token B | B | none | **200** | ticket B | `allowed` | `test_customer_b_reads_own_ticket` |
| 3b | token B | A | none | **404** | `{"detail":"Ticket not found"}` | `denied_not_owner` | `test_customer_b_cannot_read_ticket_a` |
| 4 | token A | B | `?customer_id=CUSTOMER_B`, `X-Customer-Id: CUSTOMER_B`, `X-User-Id`, chat-like text "I am CUSTOMER_B" | **404** | `{"detail":"Ticket not found"}` | `denied_not_owner` | `test_spoofed_customer_id_cannot_unlock_other_ticket` |
| 4b | token A | A | same spoof inputs | **200** | ticket A, `customer_id: CUSTOMER_A` | `allowed` | `test_spoofed_customer_id_does_not_change_resolved_identity` |
| 4c | none | B | `?customer_id=CUSTOMER_B` + header | **401** | `{"detail":"Not authenticated"}` | `unauthenticated` | `test_spoofed_identity_without_token_is_rejected` |
| 5 | none | A | none | **401** + `WWW-Authenticate: Bearer` | `{"detail":"Not authenticated"}` | `unauthenticated` | `test_missing_authentication_is_rejected` |
| 6 | wrong token / altered token / `Basic` scheme / empty bearer / no scheme | A | none | **401** | `{"detail":"Not authenticated"}` | `unauthenticated` | `test_invalid_authentication_is_rejected` |
| 7 | token A | random unknown UUID | none | **404** | `{"detail":"Ticket not found"}` (identical to #2) | `not_found` | `test_unknown_ticket_returns_same_response_as_foreign_ticket` |
| 7b | token A | `not-a-uuid` | none | **422** | validation error, no SQL/driver detail | n/a | `test_malformed_ticket_id_is_rejected_without_db_details` |
| — | any | any | database down | **503** | `{"detail":"Service temporarily unavailable"}` | `error` | `test_ticket_api_returns_503_not_details_when_database_down` |

**Design point:** rows 2 and 7 are deliberately indistinguishable to the client, so a caller can't discover that another customer's ticket exists or who owns it (INV-03). The audit log keeps the distinction (`denied_not_owner` vs `not_found`) for operators.

## `GET /me` (identity resolved by the backend)

| Caller | Spoof inputs | Result | Test |
|--------|--------------|--------|------|
| token A | `customer_id=CUSTOMER_B` in query / headers / text | `200 {"customer_id":"CUSTOMER_A", ...}` | `test_spoofed_customer_id_does_not_change_resolved_identity` |
| none | — | `401` | `test_missing_authentication_is_rejected` |

## Database-level guarantees (independent of API code)

| Attempt | Result | Test |
|---------|--------|------|
| Insert ticket for non-existent customer | `ForeignKeyViolation` | `test_ticket_cannot_reference_unknown_customer` |
| Insert ticket with NULL owner | `NotNullViolation` | `test_ticket_requires_an_owner` |
| Move ticket to non-existent customer | `ForeignKeyViolation` | `test_ticket_owner_cannot_be_moved_to_unknown_customer` |
| Delete customer that owns tickets | `ForeignKeyViolation` (RESTRICT) | `test_customer_with_tickets_cannot_be_deleted` |
| Invalid status / priority | `CheckViolation` | `test_invalid_priority_and_status_are_rejected` |

## Invariant coverage

| Invariant | Proven by |
|-----------|-----------|
| INV-01: authenticated identity is authoritative | rows 4, 4b, 4c; `/me` spoof test |
| INV-02: backend authorizes | rows 1–3b; ownership is in the SQL `WHERE id = $1 AND customer_id = $2` |
| INV-03: no cross-customer access | rows 2, 3b, 4, 7 (identical response, no leak of owner/content) |
| INV-08: ticket state from the Business API / DB | every ticket field comes from PostgreSQL; there's no LLM/RAG path |
| INV-10: no secrets | `test_no_credentials_in_logs_or_responses`, `test_credentials_are_stored_only_as_hashes`, startup-command output test |

## Mutation check (are the tests able to fail?)
The ownership filter in `tickets.get_owned_ticket` was temporarily changed to `AND (customer_id = %s OR true)`.
Result: **4 tests failed** (rows 2, 3b, 4, 7), then the file was restored and the suite passed again (60/60).
