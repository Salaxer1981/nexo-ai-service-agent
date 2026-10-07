# APP-02 — Confirmation matrix

Sources: `pytest-focused.txt` (48 passed), `database-evidence.txt`, `audit-log-sample.txt`.
All cases run against a real throwaway PostgreSQL 17.11. "Tickets Δ" = change in `tickets` row count.

| # | Scenario | HTTP | Body / code | Tickets Δ | Action status after | Test |
|---|----------|------|-------------|-----------|---------------------|------|
| 1 | `POST /tickets/prepare` (valid data) | 201 | pending_action_id, summary, summary_text, payload_hash, expires_at, `confirmation_required: true` | **0** | `pending` | `test_prepare_creates_no_ticket` |
| 2 | Summary is bound to the exact data | — | `payload_hash` = SHA-256 of canonical JSON (independently recomputed in test); whitespace-normalized; differs per customer | 0 | — | `test_prepare_returns_summary_bound_to_exact_data` |
| 3 | Confirm with the presented fingerprint + Idempotency-Key | **201** | real ticket (`id`, owner = caller, data = stored data, status `open`) | **+1** | `consumed` | `test_confirm_creates_exactly_one_ticket_owned_by_caller` |
| 4 | Created ticket readable by owner / by other customer | 200 / 404 | — | 0 | — | same |
| 5 | CUSTOMER_A confirms CUSTOMER_B's action | **404** | `{"detail":"Pending action not found"}`, identical to an unknown ID | 0 | B's stays `pending` | `test_customer_a_cannot_confirm_customer_b_action` |
| 6a | `customer_id` in prepare/confirm **body** | 422 | unknown fields refused (`extra=forbid`) | 0 | none created | `test_customer_id_input_cannot_override_authentication` |
| 6b | `customer_id` in **query / X-Customer-Id header** | 201 | summary and ticket owner = authenticated `CUSTOMER_A` | +1 (own) | — | same |
| 7–10 | Re-prepare with changed `contact_name` / `subject` / `description` / `priority`, then confirm the OLD action | **409** | `confirmation_invalid` (old action `superseded`) | 0 | old: `superseded` | `test_changing_any_field_invalidates_previous_confirmation[*]` |
| 7–10b | Confirm old action with the NEW fingerprint | 409 | rejected | 0 | — | same |
| 7–10c | Confirm an action with a fingerprint of modified data | **409** | `confirmation_mismatch` | 0 | stays `pending` | same |
| 7–10d | Confirm the NEW action | 201 | ticket carries the new value | +1 | new: `consumed` | same |
| 15 | Re-confirm an already-consumed action with a **new** key | **409** | `confirmation_already_used` + existing `ticket_id` | 0 | `consumed` | `test_consumed_confirmation_cannot_create_another_ticket` |
| — | `{"pending_action_id":…, "confirmed": true}` without fingerprint | 422 | — | 0 | — | `test_plain_confirmed_flag_cannot_bypass_binding` |
| — | `POST /tickets` with `confirmed: true` (no such route) | 404/405 | — | 0 | — | same |
| 20a | Expired action (TTL 30 min) | 409 | `confirmation_invalid` | 0 | `expired` | `test_no_ticket_when_confirmation_validation_fails` |
| 20b | Wrong fingerprint (`000…`, `fff…`) | 409 | `confirmation_mismatch` | 0 | `pending` | same |
| 20c | Unknown action ID | 404 | — | 0 | — | same |
| 17 | Priority `urgent/high/medium/low/Critical/""/null` | 422 | — | 0 | none created | `test_invalid_priority_is_rejected[*]` |
| 18–19 | Priority `normal` / `critical` | 201 | ticket with that priority | +1 | `consumed` | `test_canonical_priorities_create_tickets[*]` |

**Rule enforced:** a ticket is created only by `POST /tickets/confirm` presenting the exact fingerprint of
a still-`pending`, unexpired action owned by the caller. The ticket is built from the **stored** action
data and the authenticated owner, never from fields in the confirm request.
