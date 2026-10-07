# APP-03B — Matrices (local; real PostgreSQL 17.11; n8n hop = FakeN8n, NOT n8n)

Sources: `pytest-focused.txt` (47 passed), `postgres-and-trace-evidence.txt`, `regression-and-mutations.txt`.
"Leads Δ" = change in `leads` row count; "n8n calls" = calls reaching the (fake) webhook.

## 1. Confirmation matrix
| Scenario | HTTP | Code / outcome | Leads Δ | n8n calls | Action after | Test |
|----------|------|----------------|---------|-----------|--------------|------|
| prepare | 201 | summary (e-mail lower-cased), payload_hash = independent SHA-256 | 0 | 0 | pending | `test_prepare_creates_no_lead_and_binds_exact_data` |
| invalid e-mail / empty / too long / unknown field (`customer_id`, `confirmed`, `phone`) | 422 | — | 0 | 0 | none | `test_prepare_rejects_invalid_or_unknown_fields[*]` |
| no session / invalid `X-Conversation-ID` | 401 / 400 | — | 0 | 0 | — | `test_prepare_requires_auth_and_valid_conversation_header` |
| confirm (exact fingerprint + key) | **201** | `created`, lead from PostgreSQL, `workflow_execution_id` set | **+1** | 1 | consumed | `test_confirm_creates_lead_only_through_the_workflow` |
| any of the 4 fields changed → re-prepare; confirm old | 409 | `confirmation_invalid` (old superseded) | 0 | 0 | superseded | `test_changing_any_field_requires_new_confirmation[*]` |
| fingerprint of different data | 409 | `confirmation_mismatch` | 0 | 0 | pending | same |
| other session confirms my action | 404 | identical to unknown id, nothing leaked | 0 | 0 | pending | `test_other_session_cannot_confirm_and_nothing_leaks` |
| expired action | 409 | `confirmation_invalid` | 0 | 0 | expired | `test_expired_action_cannot_be_confirmed` |
| missing / invalid Idempotency-Key | 400 | — | 0 | 0 | pending | `test_missing_or_invalid_key_rejected_before_n8n[*]` |

## 2. Service-auth matrix (`POST /internal/leads`)
| Caller credential | Target | HTTP | Leads Δ | Test |
|-------------------|--------|------|---------|------|
| none | confirmed action | 401 | 0 | `test_private_write_rejects_anything_but_the_service_credential[none]` |
| CUSTOMER_A token | confirmed action | 401 | 0 | `…[customer_a]` |
| CUSTOMER_B token | confirmed action | 401 | 0 | `…[customer_b]` |
| random 43-char token | confirmed action | 401 | 0 | `…[random]` |
| **n8n lead-writer** | *pending* (unconfirmed) action | 409 `action_not_confirmed` | 0 | `test_service_credential_cannot_create_unconfirmed_or_altered_leads` |
| n8n lead-writer | confirmed, **other key** | 409 `idempotency_key_conflict` | 0 | same |
| n8n lead-writer | confirmed, **altered lead** | 409 `payload_mismatch` | 0 | same |
| n8n lead-writer | unknown action | 404 | 0 | same |
| n8n lead-writer | no Idempotency-Key | 400 | 0 | same |
| **n8n lead-writer** | confirmed action, same key, same payload | **201** | **+1** | same |

Provisioning refuses a missing/invalid `LEAD_WRITER_TOKEN_SHA256` and a hash equal to a customer token's hash
(`test_provision_refuses_to_start_without_service_hash`).

## 3. Idempotency matrix
| Scenario | HTTP | Outcome | Leads Δ | n8n calls | Test |
|----------|------|---------|---------|-----------|------|
| same key + same action (×2 retries) | 201, same id | `replay` (answered from PostgreSQL) | 0 | **0** | `test_same_key_replays_without_calling_n8n_again` |
| same key + different action | 409 | `conflict` / `idempotency_key_conflict` | 0 | 0 | `test_same_key_different_action_conflicts` |
| consumed action + new key | 409 | `confirmation_already_used` + existing `lead_id` | 0 | 0 | `test_consumed_action_with_new_key_is_rejected` |
| n8n delivers the write twice | 201 | — | +1 total | 1 | `test_duplicate_workflow_delivery_creates_one_lead` |
| 6 concurrent private writes, same action/key | 1 `created` + 5 `replay`, one id | — | +1 | — | `test_concurrent_workflow_deliveries_create_one_lead` |
| DB: second lead for same `source_action_id` | `UniqueViolation` | — | 0 | — | `test_database_enforces_one_lead_per_action_and_valid_email` |

## 4. Failure matrix (distributed hop)
| Failure injected (FakeN8n mode) | Confirm result | Leads Δ | Action | Then | Test |
|---------------------------------|----------------|---------|--------|------|------|
| n8n unreachable (closed port) | **503** `lead_not_confirmed` | 0 | confirmed | other key → 409 `confirmation_in_progress`; same key after recovery → 201 `created`, +1 | `test_failed_hop_never_reports_success_and_is_retryable[unreachable]` |
| n8n 500 before calling backend | 503 | 0 | confirmed | same | `…[fail_500]` |
| n8n can't reach `/internal/leads` | 503 | 0 | confirmed | same | `…[internal_unreachable]` |
| lead committed, response dropped | **201 `replay`** (`recovered_after_dispatch`) | +1 | consumed | retry → same id, still +1 | `test_committed_but_response_lost_recovers_same_lead` |
| workflow claims 201 but wrote nothing | **502** `workflow_inconsistent` | 0 | confirmed | — | `test_workflow_success_without_persisted_lead_is_not_success` |
| workflow alters the lead | **502** `workflow_rejected`, `upstream_code: payload_mismatch` | 0 | confirmed | — | `test_tampered_payload_is_refused_end_to_end` |
| DB error in private write (trigger) | 503 | 0 (rolled back) | confirmed | same key → 201, +1 | `test_database_failure_in_lead_write_rolls_back_and_is_retryable` |

## 5. Direct-bypass proof
| Bypass attempt | Result | Test |
|----------------|--------|------|
| public `POST /leads`, `/lead`, `/leads/create` | 404/405, 0 leads | `test_no_public_direct_lead_route` |
| customer/agent token on `/internal/leads` | 401 | service-auth matrix |
| unauthenticated `/internal/leads` | 401 | service-auth matrix |
| service credential without user confirmation | 409 `action_not_confirmed` | service-auth matrix |
| code path other than `leads.internal_create` inserting leads | none: static check finds `INSERT INTO leads` only in `internal_create`; `/leads/confirm` route contains no insert; `/internal/leads` route requires `require_service("lead_write")` | `test_only_the_private_write_path_inserts_leads` |
| n8n writing the DB directly | not possible: no DB node in the workflow (static test), n8n not on the `internal` network (N8N-01V1) | `test_no_database_or_code_nodes` |

## 6. Mutation checks (each break caught; `regression-and-mutations.txt`)
| ID | Protection removed | Caught by |
|----|--------------------|-----------|
| L1 | private write's "confirmed" check | `test_service_credential_cannot_create_unconfirmed_or_altered_leads` |
| L2 | payload fingerprint check | 2 tests (tamper end-to-end, direct altered lead) |
| L3 | service auth looks up customer credentials instead | 21 tests |
| L4 | confirm trusts the workflow's word instead of PostgreSQL | `test_workflow_success_without_persisted_lead_is_not_success` |
| L5 | no DB recovery after a lost response | `test_committed_but_response_lost_recovers_same_lead` |
| L6 | explicit "key bound to another action" check | **not caught alone**: the unique index `pending_lead_actions_confirm_key` still rejects it (defense in depth); with **both** removed (L6b) a second lead is created and the test fails |
| L7 | confirmation must match prepared data | 4 tests |
