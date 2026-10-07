# FOUNDATION-02 — VM runtime validation summary

- **Date:** 2026-10-06, 12:54–12:56 UTC
- **Host:** assessment VM (Ubuntu 24.04.4, Docker 29.8.2, Compose v5.6.0)
- **Commit tested:** `59264698b854ddcd7e58ffb8168d68f60766bd28`, transferred as a git bundle and checked out detached in `~/nexo-f02/repo`
- **Result:** **22/22 automated checks PASS**. Full log: `run.txt`. Script: `run.sh`.

| Area | Evidence (`run.txt` section) | Result |
|------|------------------------------|--------|
| Exact commit | §1 `VM checkout HEAD` = expected SHA, clean tree | PASS |
| VM-local secrets | §2 `.env` generated on VM, mode `-rw-------`, git-ignored, values never printed | PASS |
| Compose config | §3 `docker compose config --quiet` → VALID; resolved config shown with password redacted | PASS |
| Image build | §4 `nexo-backend:0.1.0` built (221 MB), pinned deps installed | PASS |
| Container health | §5 `db` healthy, `backend` healthy (`up --wait`) | PASS |
| `/health` | §6 `HTTP 200 body={"status":"ok"}` from VM host via 127.0.0.1:8000 | PASS |
| Port mappings | §7 `docker port` db: none; backend: `8000/tcp -> 127.0.0.1:8000` | PASS |
| Listening ports | §7 `ss -tlnH`: new listener only `127.0.0.1:8000`; no `:5432`; public only `:9922` | PASS |
| Network type | §7 `nexo_internal`: driver `bridge`, `internal=false` | PASS |
| Service-to-service | §8 backend → `db:5432` TCP via Docker DNS (172.18.0.2); authenticated `psql` login over the network → PostgreSQL 17.11 | PASS |
| Egress readiness | §9 from backend container: DNS `openrouter.ai` → 104.18.3.115; HTTPS GET public `/api/v1/models` → 200. No API key, no LLM call | PASS |
| Persistence A/B | §10 marker `f02-20261006T125509Z-187` inserted and read; db mounts `volume nexo_db_data -> /var/lib/postgresql/data` | PASS |
| Persistence C | §10 `docker compose down` (no `-v`) → 0 containers, network removed, volume still listed; `up` again | PASS |
| Persistence D | §10 new db container `0445692978c7` ≠ `ef0f1a8a9342`, same volume (CreatedAt `2026-10-06T12:54:56Z`), marker read back identical | PASS |
| Secret hygiene | §13 generated password occurrences in full log: **0** | PASS |

## Why persistence is attributable to `db_data`
The database container was destroyed and replaced, which the different container IDs prove. The only storage mounted at PostgreSQL's data directory was the named volume `nexo_db_data`, and it was the same volume instance before and after. The marker row survived, so it was stored in that volume and not in the container.

## Cleanup performed (§12–14)
1. `DROP TABLE foundation02_marker`, confirmed gone (`to_regclass` IS NULL → `t`).
2. `docker compose down -v`: removed both containers, network `nexo_internal` and volume `nexo_db_data` (after persistence was proven).
3. `docker image rm`: `nexo-backend:0.1.0` and `pgvector/pgvector:0.8.7-pg17-bookworm` deleted. `python:3.12.15-slim-bookworm` reported "No such image" because the containerd image store keeps build base layers in the build cache.
4. `docker builder prune -f`: 220.7 MB of build cache from this run removed (the cache was empty before the run).
5. `~/nexo-f02` deleted (bundle, checkout, VM-local `.env`, VM-side log).
6. **Final state equals pre-run state:** 0 containers, 0 images, 0 volumes, 0 build cache, default networks only, listeners `:9922` + loopback DNS only.
7. Not touched: Docker installation, SSH, ufw, other system state.

## Observations (no defects)
- `git bundle verify` printed `(exit 1)` because it was run outside a repository (the command needs one). The clone and the SHA equality check succeeded, so the transfer is verified.
- Build warnings: pip "running as root" (build stage only, before `USER appuser`); `useradd` uid 10001 > SYS_UID_MAX (informational). Neither affects runtime.
