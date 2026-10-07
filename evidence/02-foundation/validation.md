# FOUNDATION-01 — Validation summary

Date: 2026-10-06. Validation scope: **local static and application-level only**.
The workstation has no Docker; the container runtime is validated in a later VM phase.

## Static validation (local, done)

| # | Required check | Test | Result |
|---|----------------|------|--------|
| 1 | `/health` returns 200 | `test_health.py::test_health_returns_200` | PASS |
| 2 | Exact body `{"status": "ok"}` | `test_health.py::test_health_body_is_exact` | PASS |
| 3 | Configuration loads safely | `test_config.py` (9 tests: load, default port, each missing var named without values, invalid port, password not in repr, app refuses to start unconfigured) | PASS |
| 4 | `compose.yaml` parses | `test_compose.py::test_compose_parses_with_expected_services` (PyYAML parse + structure) | PASS |
| 5 | No PostgreSQL host port | `test_db_publishes_no_host_port`, `test_all_published_ports_bind_to_loopback` | PASS |
| 6 | Images pinned, not `latest` | `test_compose_images_are_pinned[db,backend]`, `test_dockerfile_base_image_is_pinned` | PASS |
| 7 | Persistent DB volume | `test_db_uses_named_persistent_volume` | PASS |
| + | Healthcheck + startup order | `test_db_has_healthcheck_and_backend_waits_for_it` | PASS |
| + | Restart policy | `test_restart_policy_set` | PASS |
| + | Credentials only via `${VAR:?}` | `test_credentials_come_only_from_variable_substitution` | PASS |

Total: **23 passed, 0 failed** (`pytest.txt`). One upstream deprecation warning
(Starlette: "Using `httpx` with `starlette.testclient` is deprecated"), which doesn't affect the results.

### Negative check of the pin rule
`postgres` → not pinned; `postgres:latest` → not pinned; `localhost:5000/img` → not pinned;
`pgvector/pgvector:0.8.7-pg17-bookworm` → pinned; `python:3.12.15-slim-bookworm` → pinned.

### Live process smoke test (local)
`uvicorn app.main:app --app-dir src/backend --host 127.0.0.1 --port 8765` with dummy env →
`GET /health` → `HTTP 200 {"status":"ok"}`; process stopped afterwards.

## Runtime validation (PENDING, needs a Docker host = VM, separate authorization)

- `docker compose config` (Compose's own schema validation and variable interpolation)
- `docker compose build` of `src/backend/Dockerfile` (python:3.12.15-slim-bookworm)
- `docker compose up -d`: `db` becomes healthy (`pg_isready`), then `backend` starts and becomes healthy
- `curl http://127.0.0.1:${BACKEND_PORT}/health` from the VM → 200
- `ss -tlnH`: backend only on 127.0.0.1, no 5432 listener on the host
- Persistence: write a marker row, `docker compose down` (without `-v`), `up`, marker still present
- Clean-up policy for the test run to be agreed (`down -v` vs keep volume)
