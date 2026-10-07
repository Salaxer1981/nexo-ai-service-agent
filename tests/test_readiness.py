"""Liveness vs database-aware readiness (required cases 9 and 10)."""
from fastapi.testclient import TestClient

from app.main import app
from app.migrate import latest_version
from conftest import _free_port


# 9
def test_readiness_ok_when_database_reachable_and_migrated(api):
    client, _ = api
    r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready", "database": "ok", "schema_version": latest_version()}


# 10
def test_readiness_fails_safely_when_database_unreachable(pg_server, monkeypatch):
    env = pg_server.env("postgres")
    env["POSTGRES_PORT"] = str(_free_port())  # nothing listens here
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with TestClient(app) as client:
        ready = client.get("/health/ready")
        live = client.get("/health")
    assert ready.status_code == 503
    assert ready.json() == {"status": "not_ready", "database": "unavailable"}
    # No connection details or credentials in the failure response.
    for secret_or_detail in (env["POSTGRES_PASSWORD"], env["POSTGRES_PORT"], "127.0.0.1", "psycopg", "Traceback"):
        assert secret_or_detail not in ready.text
    # Liveness is independent of the database: the process is alive.
    assert live.status_code == 200


def test_readiness_fails_when_schema_not_migrated(pg_server, fresh_db, monkeypatch):
    for key, value in pg_server.env(fresh_db).items():
        monkeypatch.setenv(key, value)
    with TestClient(app) as client:
        r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json()["status"] == "not_ready"


def test_ticket_api_returns_503_not_details_when_database_down(pg_server, monkeypatch):
    env = pg_server.env("postgres")
    env["POSTGRES_PORT"] = str(_free_port())
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with TestClient(app) as client:
        r = client.get("/tickets/a0000000-0000-4000-8000-000000000001",
                       headers={"Authorization": "Bearer " + "x" * 40})
    assert r.status_code == 503
    assert r.json() == {"detail": "Service temporarily unavailable"}
    assert env["POSTGRES_PASSWORD"] not in r.text
