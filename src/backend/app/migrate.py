"""Minimal versioned migration runner.

- Migrations are the `*.sql` files in app/migrations, applied in filename order.
- Each applied version is recorded in `schema_migrations` with a SHA-256 checksum;
  editing an already-applied file is detected and refused.
- All pending migrations run in one transaction under an advisory lock, so a failed
  migration leaves the database unchanged and concurrent starts cannot double-apply.

Usage: python -m app.migrate
"""
import hashlib
import sys
from pathlib import Path

import psycopg

from app.config import load_settings
from app.db import connect

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
ADVISORY_LOCK_ID = 727_001  # arbitrary constant identifying this runner


class MigrationError(RuntimeError):
    pass


def available_migrations() -> list[tuple[str, str, str]]:
    """Return (version, checksum, sql) for every migration file, in order."""
    result = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        result.append((path.stem, hashlib.sha256(sql.encode("utf-8")).hexdigest(), sql))
    return result


def latest_version() -> str:
    return available_migrations()[-1][0]


def apply_migrations(conn: psycopg.Connection) -> list[str]:
    """Apply pending migrations; return the versions applied in this call."""
    applied_now = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (ADVISORY_LOCK_ID,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version text PRIMARY KEY,"
            " checksum text NOT NULL,"
            " applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = dict(conn.execute("SELECT version, checksum FROM schema_migrations").fetchall())
        for version, checksum, sql in available_migrations():
            if version in applied:
                if applied[version] != checksum:
                    raise MigrationError(f"Migration {version} was modified after being applied")
                continue
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)", (version, checksum)
            )
            applied_now.append(version)
    return applied_now


def main() -> int:
    settings = load_settings()
    with connect(settings) as conn:
        applied = apply_migrations(conn)
    print(f"migrations applied: {applied or 'none (up to date)'}; schema version: {latest_version()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
