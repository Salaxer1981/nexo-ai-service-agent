"""The exact commands the container runs before serving (see Dockerfile CMD)."""
import hashlib
import os
import secrets
import subprocess
import sys

from conftest import ROOT

BACKEND_DIR = ROOT / "src" / "backend"


def _run(module: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", module], cwd=BACKEND_DIR, env=env,
                          capture_output=True, text=True, timeout=60)


def test_migrate_and_provision_commands_bootstrap_a_clean_database(pg_server, fresh_db):
    tokens = {"AUTH_TOKEN_CUSTOMER_A": secrets.token_urlsafe(32), "AUTH_TOKEN_CUSTOMER_B": secrets.token_urlsafe(32)}
    service_token = secrets.token_urlsafe(32)  # held by n8n in reality; the backend only sees the hash
    env = {**os.environ, **pg_server.env(fresh_db), **tokens,
           "LEAD_WRITER_TOKEN_SHA256": hashlib.sha256(service_token.encode()).hexdigest()}

    first = _run("app.migrate", env)
    assert first.returncode == 0, first.stderr
    assert all(v in first.stdout for v in ("0001_initial_schema", "0002_synthetic_seed",
                                            "0003_priority_and_ticket_confirmation"))

    again = _run("app.migrate", env)  # container restarts re-run it: must be a no-op
    assert again.returncode == 0 and "up to date" in again.stdout

    provisioned = _run("app.provision_auth", env)
    assert provisioned.returncode == 0, provisioned.stderr
    assert "CUSTOMER_A, CUSTOMER_B" in provisioned.stdout
    assert "service credentials provisioned: n8n-lead-writer" in provisioned.stdout

    output = first.stdout + first.stderr + again.stdout + provisioned.stdout + provisioned.stderr
    for secret in (*tokens.values(), env["POSTGRES_PASSWORD"], service_token, env["LEAD_WRITER_TOKEN_SHA256"]):
        assert secret not in output

    with pg_server.connect(fresh_db) as conn:
        assert conn.execute("SELECT count(*) FROM api_credentials").fetchone()[0] == 2
        assert conn.execute("SELECT name, scope FROM service_credentials").fetchall() == [("n8n-lead-writer", "lead_write")]


def test_provision_refuses_to_start_without_tokens(pg_server, fresh_db):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AUTH_TOKEN_")}
    env.update(pg_server.env(fresh_db))
    assert _run("app.migrate", env).returncode == 0
    result = _run("app.provision_auth", env)
    assert result.returncode != 0
    assert "AUTH_TOKEN_CUSTOMER_A" in result.stderr


def test_provision_refuses_to_start_without_service_hash(pg_server, fresh_db):
    env = {k: v for k, v in os.environ.items() if k != "LEAD_WRITER_TOKEN_SHA256"}
    env.update(pg_server.env(fresh_db))
    env.update({"AUTH_TOKEN_CUSTOMER_A": secrets.token_urlsafe(32), "AUTH_TOKEN_CUSTOMER_B": secrets.token_urlsafe(32)})
    assert _run("app.migrate", env).returncode == 0
    result = _run("app.provision_auth", env)
    assert result.returncode != 0
    assert "LEAD_WRITER_TOKEN_SHA256" in result.stderr
