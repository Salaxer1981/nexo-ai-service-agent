# APP-02 — Idempotency matrix

Scope of uniqueness (database PRIMARY KEY): `(customer_id, operation='ticket_confirm', idempotency_key)`.
`request_hash` = SHA-256 of `{op, pending_action_id, payload_hash}`. The record is written in the
**same transaction** as the ticket and the action's `consumed` status.

| # | Scenario | HTTP | `Idempotency-Outcome` | Tickets Δ | Test |
|---|----------|------|-----------------------|-----------|------|
| A | First confirm with key K | 201 | `created` | +1 | `test_same_key_same_action_returns_same_ticket_without_duplicates` |
| B | Exact retry with K (×2) | 201, identical body | `replay` | 0 | same |
| C1 | K reused for a **different action** | **409** `idempotency_key_conflict` | `conflict` | 0 | `test_same_key_with_different_request_conflicts` |
| C2 | K reused for the same action with a **different fingerprint** | 409 `idempotency_key_conflict` | `conflict` | 0 | same |
| D | Ticket committed, response lost (simulated: exception after commit → client gets 500), then retry K | 201 | `replay`, same ticket id as committed | 0 on retry (+1 total) | `test_retry_after_lost_response_returns_committed_ticket` |
| E | Same key used by CUSTOMER_A and CUSTOMER_B | 201 / 201 | `created` each | +1 each | `test_idempotency_keys_are_scoped_per_customer` |
| F | Two **concurrent** confirms, same key (threads, separate connections) | 201 / 201, same id | `created` + `replay` | **+1** | `test_concurrent_confirmations_create_one_ticket[True]` |
| G | Two **concurrent** confirms, different keys, same action | 201 / 409 | `created` / `confirmation_already_used` | **+1** | `test_concurrent_confirmations_create_one_ticket[False]` |
| H | Missing / empty / invalid key (`has space`, 129 chars, `bad/char`) | 400 | — | 0 (action stays `pending`) | `test_missing_or_invalid_idempotency_key_is_rejected[*]` |
| I | DB error **inside** the transaction after the ticket INSERT (trigger raises on `idempotency_keys`) | 503, "retry with the same Idempotency-Key" | — | **0** (rolled back) | `test_failure_inside_transaction_rolls_back_ticket` |
| I2 | …then retry with the same K after the failure is removed | 201 | `created` | +1 | same |
| J | Database unreachable | 503, no id, no "created" | — | 0 | `test_database_unavailable_never_reports_success` |
| K | Direct second INSERT for an already-used `source_action_id` | `UniqueViolation` (DB) | — | 0 | `test_database_rejects_second_ticket_for_same_action` |

## How the guarantees are layered

1. **Idempotency record lookup** before doing anything, and again after locking the action row
   (`SELECT … FOR UPDATE`), so a concurrent winner's committed result is seen and replayed.
2. **Action status** `pending → consumed` inside the same transaction.
3. **Database backstops:** `idempotency_keys` PRIMARY KEY and `tickets.source_action_id` UNIQUE. A losing
   concurrent transaction hits a unique violation, rolls back **entirely** (including its ticket INSERT),
   and is answered from the committed state.
4. Success is returned **only after COMMIT**, from the persisted row.

## Response-loss contract (REQ-FAIL-02)

If the ticket is committed but the response never reaches the caller, the caller retries with the
**same Idempotency-Key** and receives the original ticket (`201`, `Idempotency-Outcome: replay`). A 503
from confirm means "not confirmed": either rolled back or unknown, and the same-key retry returns the
definitive result. A retry can never create a second ticket.
