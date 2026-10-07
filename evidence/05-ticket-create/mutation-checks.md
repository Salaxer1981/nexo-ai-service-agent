# APP-02 — Mutation checks

Each mutation breaks one protection in `src/backend/app/ticket_actions.py`, runs
`tests/test_ticket_create.py` against real PostgreSQL, then restores the file byte-for-byte
(verified: `restored: True`; final SHA-256 of the file is unchanged, `437daf910e75…`).

| ID | Mutation | Tests that FAILED (i.e. caught it) |
|----|----------|------------------------------------|
| M1 | Idempotency lookup disabled (`_lookup_idempotency` returns `None`) | `same_key_same_action…`, `same_key_with_different_request_conflicts`, `retry_after_lost_response…`, `concurrent_confirmations…[same key]`, `audit_log_records_ids_and_outcomes` |
| M2 | Fingerprint check disabled | `changing_any_field…[contact_name, subject, description, priority]`, `no_ticket_when_confirmation_validation_fails` |
| M3 | Status checks (consumed / superseded / expired) disabled | `changing_any_field…[×4]`, `no_ticket_when_confirmation_validation_fails` |
| M4 | Ownership filter removed from the pending-action lookup | `customer_a_cannot_confirm_customer_b_action` |
| M5 | Re-prepare no longer supersedes older actions | `changing_any_field…[×4]` |

## Defense in depth observed (M3)
With the application-level `consumed` check removed, `test_consumed_confirmation_cannot_create_another_ticket`
still **passes**. The `tickets.source_action_id` UNIQUE constraint rejects the second ticket, the
transaction rolls back, and the API answers `409 confirmation_already_used` with the existing `ticket_id`.
(The first mutation run exposed that this backstop path omitted `ticket_id`; it was fixed so both layers
return the same contract.)

## Intermittent observation (reported, not hidden)
In 1 of 6 M5 executions, two additional tests failed (`test_failure_inside_transaction_rolls_back_ticket`,
`test_audit_log_records_ids_and_outcomes`); their error text wasn't captured. It didn't reproduce in 5
further M5 runs, and the **unmutated** suite passed 18/18 consecutive runs of `test_ticket_create.py`.
As a precaution, the failure-injection test now uses `CREATE OR REPLACE` / `DROP … IF EXISTS`, so a leftover
trigger can't cascade into later tests, and the concurrency test asserts its worker threads finished.
Root cause unconfirmed; flagged for the independent audit.
