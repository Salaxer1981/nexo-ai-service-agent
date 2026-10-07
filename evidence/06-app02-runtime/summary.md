# APP-02V1 — VM runtime validation of APP-02/F1

| Item | Value |
|------|-------|
| Candidate | `1284f98197a3f0cbd21b1449397579807d8c4d58` (APP-02 `9ef9823` + fix APP-02F1), transferred as a git bundle, detached checkout on the VM, SHA verified |
| Audit status before run | Independent Codex focused re-audit: PASS / SAFE FOR VM VALIDATION; APP02-01 CLOSED |
| Runtime | Ubuntu 24.04.4 VM, Docker 29.8.2, Compose v5.6.0, PostgreSQL 17.11 (pgvector image), backend image built on the VM |
| Accepted run | **Run 2**, 2026-10-06 ~16:07–16:09 UTC: **80/80 checks PASS** (`run2.txt`) |
| Run 1 | PARTIAL, 78 pass / 2 fail, caused by the **validation script** (log capture after container removal), not the application (`run1-partial.txt`) |
| Script | `run.sh` (orchestration + embedded stdlib-only API driver; all API calls via `127.0.0.1:8000`) |
| Secrets | DB password + both tokens generated on the VM (`.env` mode 600), never printed; VM-side count in run log: **0 / 0 / 0**; deleted at cleanup |

## 1. Build, migrations, startup (`run2.txt` §1–5)
- `docker compose config` valid; backend image built; `up --wait`: `db` healthy, `backend` healthy (HEALTHCHECK = `/health/ready`).
- Backend start output: `migrations applied: ['0001_initial_schema', '0002_synthetic_seed', '0003_priority_and_ticket_confirmation', '0004_one_pending_action_per_group']`; `synthetic credentials provisioned for: CUSTOMER_A, CUSTOMER_B`.
- `schema_migrations` = exactly 4 rows, **checksums identical** to the SHA-256 of the checked-out files (`7d6223e6…`, `8c062ced…`, `a7f58cec…`, `01714a8c…`).
- `/health` → `200 {"status":"ok"}`; `/health/ready` → `200`, `schema_version` `0004_one_pending_action_per_group`.

## 2. Ports and network (§6)
| Check | Result |
|-------|--------|
| `docker port db` | none |
| `docker port backend` | `8000/tcp -> 127.0.0.1:8000` |
| Host listener on `:5432` | none |
| Backend listener | only `127.0.0.1:8000` |
| Public listeners | only `:9922` (SSH) |
| backend → `db:5432` (Docker DNS) | OK |
| OpenRouter / LLM | not called |

## 3. Authorization matrix (§7.2)
| Request | HTTP | Body |
|---------|------|------|
| CUSTOMER_A `GET /me` | 200 | `customer_id: CUSTOMER_A` |
| CUSTOMER_B `GET /me` | 200 | `customer_id: CUSTOMER_B` |
| A reads ticket A | 200 | own ticket |
| B reads ticket B | 200 | own ticket |
| A reads ticket B | 404 | `{"detail":"Ticket not found"}`, no leak |
| B reads ticket A | 404 | `{"detail":"Ticket not found"}`, no leak |
| Invalid token | 401 | `Not authenticated` |
| No token | 401 | `Not authenticated` |

## 4. Prepare / confirm (§7.3)
- `POST /tickets/prepare` (CUSTOMER_A, `normal`) → 201, `status: pending`, summary + 64-hex `payload_hash`; **ticket count 2 → 2**.
- `POST /tickets/confirm` (K1) → **201**, `Idempotency-Outcome: created`, ticket `3a5896c6-…`; count +1.
- DB row: `CUSTOMER_A | source_action_id = 0d65c2f6-… (the prepared action) | normal`.
- Owner `GET /tickets/3a5896c6-…` → 200; CUSTOMER_B → 404.

## 5. Idempotency matrix (§7.4)
| Case | HTTP | Outcome / code | Tickets |
|------|------|----------------|---------|
| A: K1 + same confirmation (retry) | 201, identical body | `replay` | unchanged |
| B: K1 + different action | 409 | `conflict` / `idempotency_key_conflict` | unchanged |
| B2: K1 + same action, different hash | 409 | `conflict` / `idempotency_key_conflict` | unchanged |
| C: consumed action + new key K2 | 409 | `confirmation_already_used`, `ticket_id` = `3a5896c6-…` | unchanged |
| D: missing key | 400 | — | unchanged |
| D: invalid key (`bad key/with space`) | 400 | — | unchanged |
| Other action after B–D | — | still `pending` | — |

## 6. Confirmation invalidation (§7.5), official flow "whole office without internet"
Same conversation: prepare A (`normal`) → prepare B (`critical`) → A is `superseded`; confirm A → **409 `confirmation_invalid`**;
confirm B → **201**, `priority: critical`; exactly one new ticket.

## 7. Concurrent prepare on the containerized stack (§7.6)
3 rounds × 8 concurrent `POST /tickets/prepare` (same customer, same `X-Conversation-ID`), all HTTP 201:

| Round | DB statuses | Confirm results | Tickets |
|-------|-------------|-----------------|---------|
| 0 | `pending=1, superseded=7` | pending → 201; 7 superseded → 409 | +1 |
| 1 | `pending=1, superseded=7` | pending → 201; 7 superseded → 409 | +1 |
| 2 | `pending=1, superseded=7` | pending → 201; 7 superseded → 409 | +1 |

## 8. Cross-customer confirmation (§7.7)
CUSTOMER_B prepares; CUSTOMER_A confirms B's action → **404 `{"detail":"Pending action not found"}`**, byte-identical to a
random nonexistent ID; response contains no `CUSTOMER_B`, contact name or action ID; no ticket created. CUSTOMER_B then
confirms its own action → 201, owner `CUSTOMER_B`.

## 9. Priority matrix (§7.8)
| Priority | API (`prepare`) | DB |
|----------|-----------------|----|
| `normal` | 201 accepted | — |
| `critical` | 201 accepted | — |
| `low` / `medium` / `high` / `urgent` | **422** each; no action created | `UPDATE … priority='high'` → `violates check constraint "tickets_priority_check"` |

## 10. Traceability and secrets (§10)
- 86 phase-1 audit lines saved before the restart, plus post-restart lines; 89 lines for this run, each with `request_id`,
  `status`, `duration_ms`. Outcomes seen: **created, replay, conflict**.
- Example (from `run2.txt`): `ticket_prepare` with `X-Request-ID` `v1-…-e37a0677`, `X-Conversation-ID` `v1-basic-…`,
  `pending_action_id`, `result: prepared`; then `ticket_confirm` with `ticket_id` (only after commit),
  `confirmation_result: confirmed`, `idempotency: created`; then `replay` with the same `ticket_id`.
- Backend logs contain **no** tokens, DB password, `Bearer`/authorization header, or ticket description text. No model
  reasoning exists or is logged.

## 11. Persistence / restart (§8–9)
- Persistence fixture: ticket `2a9bbb0c-54b1-4a1a-a30d-4724fd8ff830` created and confirmed by CUSTOMER_A.
- `docker compose down` (volume kept) → 0 containers, `nexo_db_data` present → `up --wait`: new db container ID, **same
  volume instance**; backend start: `migrations applied: none (up to date)`.
- After recreation: `/health/ready` 200; owner reads the **same ticket** (identical body); CUSTOMER_B → 404; replaying the
  saved Idempotency-Key → 201 `replay` with the same ticket, so **idempotency state survived the restart**.
- Final DB counts before cleanup: `tickets=9 pending_actions=3 idempotency_keys=7`.

## 12. Cleanup (§12–14)
`docker compose down -v` (containers, network, volume); images `nexo-backend:0.1.0` and `pgvector/pgvector:0.8.7-pg17-bookworm`
removed; build cache pruned (249 MB, this run only); `~/nexo-app02v1` (bundle, checkout, `.env`, `persist.json`, saved
logs) deleted. **Final state = pre-run state:** 0 containers, 0 images, 0 volumes, 0 build cache, default networks only;
listeners `:9922` + loopback DNS only. Docker itself untouched.

## Run 1 (PARTIAL), kept for audit history
All application checks passed (78), but section 10 saw only 4 audit lines: the log check ran after `docker compose down`,
which removes containers **and their logs**, so only post-restart requests were visible. This was a validation-script
defect, not an application defect, and the local dry run couldn't show it (there, one log file survived the restart).
`run.sh` now saves phase-1 backend logs before the restart; run 2 passed all 80 checks. Run 1 also cleaned up fully, with 0
secret occurrences.

## Pre-run dry run (local)
Before the first VM run, the embedded driver was dry-run locally against uvicorn + a throwaway PostgreSQL 17.11 (64/64
checks). That dry run found and fixed two driver bugs: the per-process run ID, and `conversation_id: null` handling.
