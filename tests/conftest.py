"""Shared fixtures.

Integration tests run against a REAL, throwaway PostgreSQL 17 server started by the
`pg_server` fixture: initdb into a temp dir, scram-sha-256 auth, 127.0.0.1 on a random
port, stopped and discarded after the session. The superuser password and the synthetic
bearer tokens are generated randomly per run and never written to the repository.
"""
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PG_BIN = ROOT / ".tools" / "pg17.11" / "pgsql" / "bin"

# Dummy, non-secret values used only by tests that never touch a database.
TEST_ENV = {
    "POSTGRES_HOST": "db",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "nexo_test",
    "POSTGRES_USER": "nexo_test",
    "POSTGRES_PASSWORD": "test-only-not-a-secret",
}

TICKET_A = "a0000000-0000-4000-8000-000000000001"
TICKET_B = "b0000000-0000-4000-8000-000000000001"


@pytest.fixture
def test_env(monkeypatch):
    for name, value in TEST_ENV.items():
        monkeypatch.setenv(name, value)
    return dict(TEST_ENV)


# --- real PostgreSQL ---------------------------------------------------------------

def _pg_tool(name: str) -> str | None:
    bin_dir = os.environ.get("PG_BIN", str(DEFAULT_PG_BIN))
    return shutil.which(name, path=bin_dir)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class PgServer:
    host: str
    port: int
    user: str
    password: str

    def connect(self, dbname: str = "postgres") -> psycopg.Connection:
        return psycopg.connect(
            host=self.host, port=self.port, user=self.user, password=self.password,
            dbname=dbname, autocommit=True, connect_timeout=5,
        )

    def env(self, dbname: str) -> dict[str, str]:
        return {
            "POSTGRES_HOST": self.host,
            "POSTGRES_PORT": str(self.port),
            "POSTGRES_DB": dbname,
            "POSTGRES_USER": self.user,
            "POSTGRES_PASSWORD": self.password,
        }

    def create_database(self) -> str:
        name = f"nexo_test_{uuid.uuid4().hex[:12]}"
        with self.connect() as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        return name

    def drop_database(self, name: str) -> None:
        with self.connect() as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture(scope="session")
def pg_server():
    initdb, pg_ctl = _pg_tool("initdb"), _pg_tool("pg_ctl")
    if not (initdb and pg_ctl):
        pytest.skip("PostgreSQL binaries not found: set PG_BIN or install into .tools/pg17.11/pgsql/bin")

    # Not tmp_path/mkdtemp: on Windows those create owner-only (mode 0o700) ACLs, and initdb's
    # restricted process token cannot read them. A default-mode dir inherits TEMP's ACLs.
    # Removed explicitly at teardown.
    base = Path(tempfile.gettempdir()) / f"nexo-pg-{uuid.uuid4().hex[:12]}"
    base.mkdir()
    data, log, pwfile = base / "data", base / "server.log", base / "pwfile"
    password = secrets.token_urlsafe(24)
    pwfile.write_text(password, encoding="utf-8")
    try:
        init = subprocess.run(
            [initdb, "-D", str(data), "-U", "postgres", "-A", "scram-sha-256",
             f"--pwfile={pwfile}", "-E", "UTF8", "--locale=C"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    finally:
        pwfile.unlink(missing_ok=True)
    if init.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        pytest.fail("initdb failed: " + init.stderr.decode("utf-8", "replace")[-1000:])

    port = _free_port()
    with open(data / "postgresql.conf", "a", encoding="utf-8") as conf:
        conf.write(f"\nport = {port}\nlisten_addresses = '127.0.0.1'\nunix_socket_directories = ''\nfsync = off\n")

    # stdout/stderr to DEVNULL: on Windows the server inherits pipes and would block subprocess.run.
    started = subprocess.run(
        [pg_ctl, "start", "-D", str(data), "-l", str(log), "-w", "-t", "60"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if started.returncode != 0:
        tail = log.read_text(encoding="utf-8", errors="replace")[-1000:] if log.exists() else ""
        shutil.rmtree(base, ignore_errors=True)
        pytest.fail("PostgreSQL failed to start: " + tail)
    try:
        yield PgServer(host="127.0.0.1", port=port, user="postgres", password=password)
    finally:
        subprocess.run([pg_ctl, "stop", "-D", str(data), "-m", "fast", "-w"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def fresh_db(pg_server):
    """An empty database, dropped after the test."""
    name = pg_server.create_database()
    try:
        yield name
    finally:
        pg_server.drop_database(name)


@pytest.fixture(scope="session")
def app_db(pg_server):
    """A migrated + seeded database with synthetic credentials provisioned (random tokens)."""
    from app.migrate import apply_migrations
    from app.provision_auth import hash_token, provision, provision_services

    name = pg_server.create_database()
    tokens = {"CUSTOMER_A": secrets.token_urlsafe(32), "CUSTOMER_B": secrets.token_urlsafe(32)}
    service_token = secrets.token_urlsafe(32)  # n8n lead-writer; only its hash is stored
    with pg_server.connect(name) as conn:
        conn.autocommit = False
        apply_migrations(conn)
        provision(conn, tokens)
        provision_services(conn, {"n8n-lead-writer": ("lead_write", hash_token(service_token))})
    yield {"name": name, "env": pg_server.env(name), "tokens": tokens, "service_token": service_token}
    pg_server.drop_database(name)


@pytest.fixture
def api(app_db, monkeypatch):
    """A TestClient wired to the real test database, plus the per-run tokens."""
    from app.main import app

    for key, value in app_db["env"].items():
        monkeypatch.setenv(key, value)
    with TestClient(app) as client:
        yield client, app_db["tokens"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
