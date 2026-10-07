# APP-03BV1 — Lead flow validated on the VM with REAL n8n 2.42.3

**This is REAL n8n evidence, not FakeN8n.** Execution IDs are n8n's own integer IDs, looked up in n8n's own database
(`execution_entity`), never `fake-exec-*`. The local FakeN8n evidence in this folder is preserved and labelled as such.

| Item | Value |
|------|-------|
| Candidate | `5ce2d6ebd54e24c872087d47966a176c96abb73d` (APP-03B), git bundle → detached checkout on the VM, SHA verified, working tree clean (no edits) |
| Audit before run | Independent Codex audit: PASS WITH LOWS (BLOCKER 0, HIGH 0, MEDIUM 0, LOW 3, INFO 3), SAFE FOR VM VALIDATION |
| Runtime | Ubuntu 24.04.4 VM, Docker 29.8.2, Compose v5.6.0; `n8nio/n8n:2.42.3`, `pgvector/pgvector:0.8.7-pg17-bookworm`, `nexo-backend:0.1.0` built on the VM |
| Accepted run | **Run 2: 106/106 checks PASS** (`vm-run2-real-n8n.txt`) |
| Run 1 | 105/106: webhook probe hit n8n's registration lag (details below), kept in `vm-run1-real-n8n-partial.txt` |
| Harness | `vm-validate.sh`. Only change between runs: the probe polls (≤ 90 s) while n8n answers 404 "not registered". No application or workflow edits |

## 1. Startup / migrations
`docker compose config` valid; db, backend, n8n **healthy**; `/health/ready` 200; n8n `/healthz` 200. Backend start:
`migrations applied: [0001 … 0006_leads]`, `synthetic credentials provisioned: CUSTOMER_A, CUSTOMER_B`, `service credentials
provisioned: n8n-lead-writer`. `schema_migrations` = 6 rows with checksums **identical** to the checked-out files.

## 2. Network boundary
backend `127.0.0.1:8000` only; n8n `127.0.0.1:5678` only; db no published port, no `:5432` listener; public listeners only
`:9922`. n8n attached only to `nexo_automation`; backend to `nexo_automation` + `nexo_internal`; db only to
`nexo_internal`. n8n → `backend:8000/health` OK; `db` **unresolvable** from n8n.

## 3. Secrets / credential boundary
- Backend env: `LEAD_WRITER_TOKEN_SHA256` = SHA-256 of the raw token (verified); raw token **absent** from backend env and `.env`.
- n8n env: no `POSTGRES_*`, `AUTH_TOKEN_*` or `LEAD_*` variables.
- Credential `nexo-lead-writer` (id `NexoLeadWriter01`, type `httpHeaderAuth`) provisioned with the supported CLI
  **`n8n import:credentials`** → "Successfully imported 1 credential"; temporary files deleted on host and container
  immediately; n8n's `credentials_entity.data` doesn't contain the raw token or "Bearer" (**stored encrypted**).

## 4. Workflow import / activation
- **`n8n import:workflow`** → "Successfully imported 1 workflow" (`NexoLeadCreate01`, committed JSON unchanged).
- Activation with **`n8n publish:workflow --id=NexoLeadCreate01`** (n8n 2.x "publish"; n8n notes it applies after a
  restart) → `docker compose restart n8n` → `workflow_entity: active=1, activeVersionId=4575fc35…` (run 2).
- **Registration lag:** n8n's `/healthz` turned healthy ~**1.3 s** before the webhook was registered (run 2 measurement;
  run 1 probed inside that window and got n8n's own 404 "webhook not registered").
- Probe with an incomplete envelope → **HTTP 400 `{"code":"invalid_envelope"}` from the workflow's Respond node**:
  the IF false branch and the static `responseCode` work in 2.42.3 (that probe is n8n execution 1).
- HTTP Request node (v4.2 `httpHeaderAuth`, `fullResponse` + `neverError`, `jsonBody` with `$execution.id`) and Respond
  node (`responseCode = {{$json.statusCode}}`) are **valid in n8n 2.42.3**: 201, 409 and 503 were all relayed correctly.

## 5. Real lead journey (CUSTOMER_A, synthetic data)
- **Prepare:** 201, `status: pending`, exact summary, 64-hex `payload_hash`; pending row in DB; **lead count unchanged**.
- **Confirm:** 201 `created`, lead `623aafe4-…`, `workflow_execution_id: "2"`.
- **PostgreSQL row:** `623aafe4-… | CUSTOMER_A | fa230eff-… (the prepared action) | 2`; action `consumed`; exactly +1 lead.

## 6. Proof that n8n was in the path
| Link | Evidence |
|------|----------|
| confirm request | `lead_confirm` audit, request_id `v1-23061611809-main`, pending_action_id `fa230eff-…` |
| **real n8n execution** | n8n `execution_entity`: `{id: 2, workflowId: NexoLeadCreate01, mode: webhook, status: success, finished: 1}`; exactly one new execution |
| private write | `lead_write` audit, **same request_id**, `service: n8n-lead-writer`, same pending_action_id, same `idempotency_key_fp`, `workflow_execution_id: 2`, `idempotency: created` |
| PostgreSQL | `leads.workflow_execution_id = 2`, `source_action_id = fa230eff-…` |
| final result | confirm returns lead `623aafe4-…` = the row read back from PostgreSQL |

## 7. Bypass negative tests (all PASS)
`POST /leads`, `/lead`, `/leads/create` → 404; `/internal/leads` with no token / CUSTOMER_A / CUSTOMER_B / random token →
**401**; service token + **unconfirmed** action → 409 `action_not_confirmed`; + wrong key → 409; + altered payload → 409;
**webhook called directly for an unconfirmed action** → real n8n relays 409 `action_not_confirmed`; no lead created by
any attempt.

## 8. Idempotency / retries (real n8n)
| Case | Result |
|------|--------|
| A. same key + same request | 201 `replay`, same lead, **no new n8n execution** (answered from PostgreSQL) |
| B. duplicate delivery into n8n (webhook re-sent for the consumed action) | 201 `idempotency: replay`, same lead, no new lead |
| C. same action + new key | 409 `confirmation_already_used` + same `lead_id` |
| D. same key + different action | 409 `idempotency_key_conflict` |
| E. lost response: Y confirmed while n8n stopped (503), then delivered to n8n directly (lead committed, execution 6), then same-key confirm | **201 `replay`, same lead** `29bd1532-…` |

## 9. Failure behavior
| Failure | Result |
|---------|--------|
| n8n stopped | confirm X and Y → **503 `lead_not_confirmed`**, no lead, actions stay `confirmed`; other key → 409 `confirmation_in_progress` |
| n8n back | X same-key retry → 201 `created` (execution 5) |
| private writer INSERT fails (temporary trigger) | n8n relays the backend's 5xx → confirm **503**, no lead, action `confirmed`; after removal, same-key retry → 201 (execution 8) |
| workflow success without lead row | not producible with the unmodified workflow; covered by the local FakeN8n tests only |

## 10. Concurrent `/leads/confirm` (endpoint level; closes the INFO coverage gap)
same key ×2 → both **201, same lead**; different keys → **201 + 409 `confirmation_in_progress`**; one lead each.

## 11. Persistence / restart
`docker compose down` (volumes kept) → `up --wait`: all healthy; n8n encryption-key fingerprint `3fcf76ee…` before =
after; main lead still in PostgreSQL; main confirm retry → same lead (replay); credential and workflow still present
and active; **new journey after recreation → 201 through real n8n (execution 12)**, which proves the credential decrypts
with the same key.

## 12. Traceability / secrets / retention
- Backend logs: no customer tokens, lead-writer token, DB password or n8n key; no raw Idempotency-Key; no contact
  e-mail, company or need text.
- n8n logs: no tokens, passwords or keys. Counts in run log and all container logs: **0** for all five secrets.
- **Retention (APP03B-02, LOW, not fixed):** n8n `execution_data` for execution 2 **does** contain the synthetic contact
  e-mail, the company and the raw Idempotency-Key; it does **not** contain the lead-writer token or customer tokens.
- 12 executions of `NexoLeadCreate01` in total during the run.
- n8n log notices (informational): Python task runner unavailable (no Code node used); deprecation notices for
  future default changes.

## 13. Cleanup
`docker compose down -v` (3 containers, 2 networks, 2 volumes incl. n8n credential/workflow state); 3 images removed;
build cache pruned (249 MB); `~/nexo-app03bv1` (checkout, `.env`, token file, n8n DB copies, state) deleted. **Final
state = pre-run:** 0 containers/images/volumes/cache; listeners `:9922` + loopback DNS only.

## Findings disposition
| ID | Severity | Status after VM run |
|----|----------|---------------------|
| APP03B-01 | LOW | Webhook unauthenticated: **open**. Confirmed inside the loopback/private boundary; a direct call can't create an unconfirmed lead (409 via n8n) |
| APP03B-02 | LOW | n8n execution retention: **open**. Execution data holds the synthetic contact data and raw Idempotency-Key (no tokens) |
| APP03B-03 | LOW | Confirmed-action cleanup: **open** |
| APP03B-04 | INFO | Real n8n import/activation/execution unverified → **RESOLVED**: import (credential + workflow), `publish:workflow`, execution, `$execution.id`, HTTP Request and Respond formats all verified |
| APP03B-05 | INFO | Authenticated-session limitation for prospects: **open** |
| APP03B-06 | INFO | No endpoint-level concurrent-confirm test → **covered by this VM run** (same key / different keys) |
| new (INFO) | — | n8n `/healthz` is healthy ~1.3 s before webhooks are registered after a restart (observed). By code analysis (not exercised on the VM), a confirm in that window receives n8n's 404, so 502 `workflow_rejected`: no lead, action stays `confirmed`, same-key retry succeeds |
