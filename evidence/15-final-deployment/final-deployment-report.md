# FINAL-02: Permanent evaluation deployment and final real evidence

**Result: PASS, 35/35 harness checks** (`vm-run-accepted.txt`). The stack was **left running on the VM for evaluation**.

**What was deployed.** Commit `16c587f`, with application code identical to the UI-02-validated `85781cf`.
Everything is real: PostgreSQL 17.11 + pgvector 0.8.7, the backend, **n8n 2.42.3**, OpenRouter `x-ai/grok-4.7`
plus embeddings, and the web client.

**How it was driven.** The real web client in the owner's Chrome, through SSH tunnels, plus an allowlisted,
token-protected control endpoint on the VM's loopback (fixed actions only, no arbitrary command).

## Hand-over state (left running)
| Item | State |
|---|---|
| Services | db, backend, n8n, web: all **healthy**, `restart: unless-stopped` (they return after a VM reboot; Docker is enabled at boot) |
| Exposure | `127.0.0.1:8000`, `:8080`, `:5678` only; db has no port; public listener `:9922` (SSH) only |
| Location | `~/nexo-eval/repo` (checkout of `16c587f`), `.env` mode **600**: the OpenRouter key and the synthetic credentials, git-ignored |
| Backups | `~/nexo-eval-backups` (mode 700): `nexo-db-20261007T171527.dump`, `n8n-state-20261007T171527/`, `snapshot-….json` |
| Knowledge | Canonical corpus (git tree clean), 4 documents / 10 sections indexed |
| Data at hand-over | Tickets 3 (T-1001, T-1002 seed; T-1003 critical), leads 1, handoffs 2 |
| Removed | Bundle, control token, raw lead-writer token (lives only in n8n's encrypted credential store), logs, control script; the control endpoint was stopped (`:8099` not listening) |
| n8n admin | Owner account created by the owner during the run; its credentials are private and not stored here |

## Scenarios (real stack)
| # | Scenario | Evidence | Result |
|---|---|---|---|
| 1 | Real journeys through the web client: critical ticket → **T-1003** + `critical_incident` handoff; lead → n8n execution 1; human handoff | `screenshots/01-db-records-after-real-journeys.jpg`, `data/records-1.json` | PASS |
| 2 | **120 € → 150 €**: one diff line, ingest `updated 1 / embedded 1 / unchanged 3`, **0 rows with 120 €**, top match `03_commercial_policy.md § Tarifas` contains 150 €. **Chat answer: «El diagnóstico inicial cuesta 150 € más IVA.»**, same reference | `02-rag-price-150-chat-answer.jpg`, `data/price150.json` | PASS |
| 3 | **Restore canonical corpus**: `git checkout`, tree clean, ingest `updated 1`, 0 rows with 150 €; chat answers 120 € again, same reference | `03-rag-price-restored-120-chat-answer.jpg`, `data/rag-restore.json` | PASS |
| 4 | **Real backend outage** (backend container stopped): red **NOT COMPLETED**, HTTP 502 `backend_unreachable` from the web boundary, all other fields "Not available", no success card. Backend restarted → healthy | `04-backend-down-not-completed.jpg` | PASS |
| 5 | **Real PostgreSQL outage** (db container stopped): badge **Unavailable** on reload; message → red **NOT COMPLETED**, HTTP 503, nothing invented. DB restarted → the **same data** (3/1/2); backend healthy again on its own within about 10 s, with no restart | `05-db-down-unavailable-badge.jpg`, `06-db-down-not-completed.jpg` | PASS |
| 6 | **Backup**: `pg_dump -Fc` exit 0 (118,701 bytes) + n8n state copy (n8n briefly stopped, webhook ready again after 0.6 s) | `data/backup.json` | PASS |
| 7 | **Restore**: an `unsafe_to_resolve` handoff was created *after* the backup (handoffs 3). `pg_restore --clean --if-exists` exit 0, no errors → handoffs **2**, that handoff gone, everything else identical | `07-backup-restore-before-restore.jpg`, `08-backup-restore-after-restore.jpg`, `data/restore.json` | PASS |
| 8 | **Restart / persistence**: `docker compose restart`, all healthy, webhook ready 0.5 s; data identical; web client reconnects and answers T-1003 from PostgreSQL | `09-restart-persistence-T1003.jpg`, `data/records-4-after-restart.json` | PASS |
| 9 | **n8n executions**: n8n UI lists `nexo-lead-create` executions 1–5, all Success. Execution 1 is the real lead; 2–5 are the endpoint's webhook-readiness probes after each restart (`400 invalid_envelope`, nothing written). Same list read from n8n's own database | `11-n8n-ui-executions.jpg`, `10-n8n-executions-from-n8n-db.jpg` | PASS |
| 10 | **Final secret scan**: **0 occurrences** of all 7 secrets in the backend, web, n8n and db logs, the run log, the served bundle, the web image filesystem/history/config, and the backup snapshots; harness check of the run and container logs: 7/7 PASS | `data/scan.json`, `vm-run-accepted.txt` §10 | PASS |

The database-records and n8n-database captures (01, 07, 08, 10) are rendered from the live VM by **read-only** queries
through the control endpoint (JSON in `data/`). All other screenshots show the real web client or the real n8n UI.

## New observation (UI-only LOW, not blocking)
**UI02-04.** The "Connected" badge checks readiness only when the page loads. During the backend outage it still read
"Connected" until a reload, after which it showed "Unavailable". Requests themselves always reported the outage
honestly.

## Model usage
**7 model-backed turns:**
- the critical incident and the lead request;
- the human request and the deletion request;
- 2 price questions;
- the post-restart lookup.

**No model call:** the 2 confirmations and the 2 turns sent during the outages.

**Embeddings:** the initial index, plus 1 section re-embedded for the price change and 1 for its restore.
