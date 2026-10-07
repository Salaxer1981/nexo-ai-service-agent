"""0003 priority alignment with the official support policy (REQ-KB-02)."""
import psycopg
import pytest

from app.migrate import apply_migrations, available_migrations
from conftest import TICKET_A, TICKET_B

INSERT = ("INSERT INTO tickets (customer_id, contact_name, subject, description, priority)"
          " VALUES ('CUSTOMER_A', 'Test Contact A', 'Synthetic', 'Synthetic', %s)")


def _apply_until(conn, last_version: str) -> None:
    """Apply migrations up to and including `last_version`, recorded like the real runner does."""
    conn.execute("CREATE TABLE schema_migrations (version text PRIMARY KEY, checksum text NOT NULL,"
                 " applied_at timestamptz NOT NULL DEFAULT now())")
    for version, checksum, sql in available_migrations():
        conn.execute(sql)
        conn.execute("INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)", (version, checksum))
        if version == last_version:
            return


def test_seed_priorities_are_mapped_to_normal(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        rows = dict(conn.execute("SELECT id::text, priority FROM tickets WHERE id IN (%s, %s)",
                                 (TICKET_A, TICKET_B)).fetchall())
    # 0002 seeded 'medium' (A) and 'low' (B); 0003 maps both to 'normal'.
    assert rows == {TICKET_A: "normal", TICKET_B: "normal"}


@pytest.mark.parametrize("priority", ["normal", "critical"])
def test_canonical_priorities_are_accepted(pg_server, fresh_db, priority):
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
        conn.execute(INSERT, (priority,))


@pytest.mark.parametrize("priority", ["low", "medium", "high", "urgent", "Critical", ""])
def test_legacy_or_unknown_priorities_are_rejected(pg_server, fresh_db, priority):
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(INSERT, (priority,))


@pytest.mark.parametrize("legacy", ["high", "urgent"])
def test_migration_refuses_to_guess_high_or_urgent(pg_server, fresh_db, legacy):
    with pg_server.connect(fresh_db) as conn:
        _apply_until(conn, "0002_synthetic_seed")
        conn.execute(INSERT, (legacy,))
        with pytest.raises(psycopg.errors.RaiseException):
            apply_migrations(conn)
        # Atomic: nothing from 0003 was applied, the legacy row is untouched.
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY 1")]
        assert versions == ["0001_initial_schema", "0002_synthetic_seed"]
        assert conn.execute("SELECT to_regclass('pending_ticket_actions')").fetchone()[0] is None
        assert conn.execute("SELECT count(*) FROM tickets WHERE priority = %s", (legacy,)).fetchone()[0] == 1
