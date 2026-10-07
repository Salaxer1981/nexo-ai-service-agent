# N8N-01V1 — n8n foundation validated on the VM

| Item | Value |
|------|-------|
| Candidate | `e23679dbb1ea5fbc586ee34df38d3db936bfaf54` (N8N-01), git bundle → detached checkout on the VM, SHA verified |
| Runtime | Ubuntu 24.04.4 VM, Docker 29.8.2, Compose v5.6.0; images `nexo-backend:0.1.0` (built on VM), `pgvector/pgvector:0.8.7-pg17-bookworm`, `n8nio/n8n:2.42.3` |
| Image identity | n8n image ID on the VM `sha256:240eaa2a3d49…`, **identical** to the digest recorded from Docker Hub at pin selection (`architecture.md`); `n8n --version` → `2.42.3` |
| Accepted run | **Run 2 (2026-10-07): 32/32 checks PASS** (`vm-run2.txt`) |
| Run 1 | Didn't execute: CRLF line endings introduced by my own script edit; VM unchanged (`vm-run1-crlf.txt`) |
| Harness | `vm-validate.sh` (committed with this evidence). Only validation-script additions since `e23679d`: per-container network list, n8n env-name check, encryption-key fingerprint, APP-03A handoff smoke, SQL quoting fix. **No application or Compose change** |

## Required runtime proofs

| # | Requirement | Result | Evidence (`vm-run2.txt`) |
|---|-------------|--------|--------------------------|
| 1 | `docker compose config` succeeds | PASS | §3 |
| 2 | db / backend / n8n healthy | PASS: all three `healthy` | §3 |
| 3 | backend on `127.0.0.1:8000` only | PASS | §4 `ss`, compose ps |
| 4 | n8n on `127.0.0.1:5678` only | PASS: `docker port` = `5678/tcp -> 127.0.0.1:5678` | §4 |
| 5 | PostgreSQL: no host port, no `:5432` listener | PASS | §4 |
| 6 | n8n → `http://backend:8000/health` = 200 | PASS: `200 {"status":"ok"}` (Node.js fetch inside n8n) | §6 |
| 7 | n8n can't resolve/reach `db` | PASS: `dns.lookup('db')` fails (`EAI_AGAIN`) | §6 |
| 8 | n8n only on the automation network | PASS: attached to `nexo_automation` only; `nexo_automation` = backend + n8n | §5 |
| 9 | backend on internal + automation | PASS; `nexo_internal` = backend + db | §5 |
| 10 | harmless inactive marker workflow exists | PASS: `n8n import:workflow` → "Successfully imported 1 workflow"; `export:workflow --id=NexoMarker000001` finds it | §8 |
| 11 | recreate n8n keeping `n8n_data` | PASS: `compose rm -sf n8n`, volume still present, `up --wait n8n`, new container ID | §8 |
| 12 | marker survives | PASS | §8 |
| 13 | same encryption key across recreation | PASS: SHA-256 fingerprint of the configured key `cb3b097b8d7f5207…` before = after; n8n healthy; no "mismatching encryption keys" in n8n logs | §8 |
| 14 | no application secrets passed into n8n | PASS: n8n env names = `GENERIC_TIMEZONE N8N_DIAGNOSTICS_ENABLED N8N_ENCRYPTION_KEY N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS N8N_HOST N8N_PORT N8N_PROTOCOL N8N_RELEASE_TYPE N8N_VERSION_NOTIFICATIONS_ENABLED NODE_ENV NODE_PATH NODE_VERSION NPM_CONFIG_UPDATE_NOTIFIER PATH SHELL TZ`; no `POSTGRES_*`/`AUTH_TOKEN_*` | §5b |
| 15 | no secrets in logs/evidence | PASS: DB password, both tokens and `N8N_ENCRYPTION_KEY` = **0** occurrences in the run log and in all container logs | §9 |

The key fingerprint is the first 16 hex characters of the SHA-256 of a random 256-bit key: a comparison value, not the key.

## Owner/admin setup observation
`/rest/settings` (read once, in §7, after startup) reported `userManagement.showSetupOnFirstLoad = True`. Nothing in the
script calls an owner-setup endpoint, so **owner setup was neither completed nor bypassed**. The marker workflow was handled entirely through n8n's supported CLI
(`import:workflow` / `export:workflow` run inside the container as the `node` user), which works without the interactive
owner setup. No n8n Cloud account was created, and no credentials were invented or stored.

## APP-03A runtime smoke (recorded separately)
Authenticated `POST /handoffs` as CUSTOMER_A (synthetic, via `127.0.0.1:8000`):
first → `201`, `Idempotency-Outcome: created`, `status: pending`, `customer_id: CUSTOMER_A`; same key → `201` `replay`
with the **same id** (`b6253856-…`); `status_message` contains "pending human attention"; no false "attending/assigned/in
progress" wording; DB shows exactly `1` row, status `pending`. This is a smoke test, not a full APP-03A VM validation
(the 44 handoff tests remain local).

## Cleanup (§11–12)
`docker compose down -v` (3 containers, `nexo_internal`, `nexo_automation`, `nexo_db_data`, `nexo_n8n_data`); images
`nexo-backend:0.1.0`, `pgvector/pgvector:0.8.7-pg17-bookworm`, `n8nio/n8n:2.42.3` removed; build cache pruned (249 MB);
`~/nexo-n8n01` (bundle, checkout, `.env`, marker, logs) deleted. **Final state = pre-run:** 0 containers, 0 images,
0 volumes, 0 build cache, default networks only; listeners only `:9922` + loopback DNS. Docker itself untouched.

## Lesson recorded (run 1)
Editing a shell script with Python `Path.write_text()` on Windows converts line endings to CRLF. Git Bash's `bash -n` and
`grep -c $'\r'` didn't reveal it in this environment; a **byte-level** CR count of the exact remote command string did.
That check is now part of the pre-run procedure.
