# N8N-01 — Self-hosted n8n foundation

Status: **static validation PASS (local)**; **runtime validation PENDING** (needs a Docker host; the VM run is
prepared in `vm-validate.sh` and awaits explicit authorization). No lead logic exists yet.

## Requirements traced
REQ-ARCH-02 / REQ-N8N-01 (n8n workflow integrated into an agent operation; built in APP-03B) · REQ-RESP-03 /
REQ-LEAD-02 (lead creation must go *through* a workflow; APP-03B) · REQ-N8N-02 (workflow export without credentials;
APP-03B) · REQ-DOCKER-01..05 · REQ-PERS-01/02 · REQ-SEC-01/02/03.

## Architecture

```
host 127.0.0.1:8000 ──► backend ◄──── automation network ────► n8n ◄── host 127.0.0.1:5678 (admin UI)
                          │                                       │
                   internal network                         n8n_data volume
                          │                              (/home/node/.n8n: SQLite,
                         db  ── db_data volume            owner, workflows, credentials)
              (no host port, PostgreSQL 17)
```

| Item | Value |
|------|-------|
| Service | `n8n` |
| Image | `n8nio/n8n:2.42.3` (official; the release tagged `stable` on 2026-10-06, same digest as `stable`/`latest`; `2.43.0` was `next`/`beta`) |
| Process user | the image's unprivileged `node` user; no `privileged`, no Docker socket, no host network (statically tested) |
| Host binding | `127.0.0.1:${N8N_HOST_PORT:-5678}` → container `5678` (loopback only) |
| Networks | n8n: `automation` only. backend: `internal` + `automation`. db: `internal` only. **n8n can reach the backend API but not PostgreSQL** |
| Persistence | named volume `n8n_data` → `/home/node/.n8n` (n8n's own embedded SQLite DB, separate from the business database) |
| Restart | `unless-stopped` |
| Healthcheck | `GET http://127.0.0.1:5678/healthz` via the image's Node.js (`fetch`); no extra tools assumed |
| Secrets | `N8N_ENCRYPTION_KEY` via `${N8N_ENCRYPTION_KEY:?…}` from the git-ignored `.env` only; n8n receives **no** DB password or customer tokens |
| Telemetry | `N8N_DIAGNOSTICS_ENABLED=false`, `N8N_VERSION_NOTIFICATIONS_ENABLED=false` (minimize data to external services, REQ-SEC-03) |
| Dependencies | none declared (`depends_on` absent): n8n starts independently; the lead workflow will call the backend at run time |

### Why loopback-only
Docker inserts its own iptables rules for published ports, which are evaluated **before** ufw. A port published on
`0.0.0.0` would therefore be reachable from the internet even with ufw active (PROJECT_STATE D-11). Binding to
`127.0.0.1` is intentional: the n8n admin UI and the backend are reachable only from the VM itself, and an evaluator
or operator uses an SSH tunnel, e.g. `ssh -p 9922 -L 5678:127.0.0.1:5678 user@<VM>`, then opens `http://localhost:5678`.

## Local admin / first-run behavior (no n8n Cloud)
- The self-hosted Community Edition runs fully locally; no n8n Cloud account, subscription or license key is needed for
  the features planned here (a webhook or manual trigger plus an HTTP Request node calling the backend).
- n8n (since v1.0) has **built-in user management**. On first visit the UI asks to **create the owner account**
  (email, name, password). The old `N8N_BASIC_AUTH_*` variables no longer exist. We don't script, pre-seed or bypass
  this. The owner password is chosen interactively by the operator, stored hashed in n8n's DB, and never written to
  the repo or evidence.
- **Window of exposure:** until the owner is created, whoever can open the UI could claim it. Mitigation: the UI is on
  loopback only, so only someone with SSH access to the VM can reach it; create the owner immediately after first start.
- The validation script reads n8n's internal `/rest/settings` (`showSetupOnFirstLoad`) for information only; it's
  not relied on as a contract.

## Persistence proof (planned; PENDING VM run)
Harmless marker: an **inactive** workflow `nexo-persistence-marker` (id `NexoMarker000001`, a single Manual Trigger node,
no credentials, no outbound calls), imported with n8n's own CLI (`n8n import:workflow`). Then: `docker compose rm -sf n8n`
(volume kept) → `up --wait n8n` → new container ID → `n8n export:workflow --id=NexoMarker000001` still finds it, and n8n
is healthy with the same encryption key. The volume is deleted only after this check, during cleanup.

## Connectivity proof (planned; PENDING VM run)
From inside the n8n container (Node.js `fetch`): `GET http://backend:8000/health` must return 200 (harmless liveness
endpoint: no LLM, no business write). Negative check: `db` must **not** resolve from n8n.

## VM validation recommendation
**Required before APP-03B relies on n8n at runtime.** This phase changes runtime infrastructure (new container, image,
network and volume), and several facts can only be proven on a Docker host: that the pinned image starts with this
configuration, the healthcheck command, loopback-only publication, network isolation, CLI-based persistence, and
cleanup. `vm-validate.sh` performs exactly that in one temporary, self-cleaning SSH session (same pattern as
FOUNDATION-02 / APP-02V1). **Not executed: awaiting explicit authorization.**

## Known limitations
- Runtime behavior of `n8nio/n8n:2.42.3` with this config is **unverified** until the VM run (no local Docker).
- Owner setup is interactive by design. Evaluators need SSH access and a tunnel to use the n8n UI.
- n8n state uses its embedded SQLite in `n8n_data`; backup = volume backup (to be documented with REQ-PERS-03).
- `N8N_ENCRYPTION_KEY` must not change for an existing `n8n_data` volume; losing it makes stored n8n credentials unreadable.
- The pin is a version tag, not an image digest. For reference, the Docker Hub tags API reported digest
  `sha256:240eaa2a3d49…` (prefix) for `2.42.3` = `stable` = `latest` on 2026-10-06.
