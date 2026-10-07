"""Schema migrations and database-enforced ownership (required cases 8 and 11)."""
import psycopg
import pytest

from app.migrate import MigrationError, apply_migrations, available_migrations, latest_version
from conftest import TICKET_A, TICKET_B

EXPECTED_VERSIONS = ["0001_initial_schema", "0002_synthetic_seed", "0003_priority_and_ticket_confirmation",
                     "0004_one_pending_action_per_group", "0005_handoffs", "0006_leads",
                     "0007_knowledge", "0008_chat_actions", "0009_chat_revision"]


def _tables(conn) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return {r[0] for r in rows}


def test_migration_files_are_ordered_and_named():
    assert [v for v, _, _ in available_migrations()] == EXPECTED_VERSIONS
    assert latest_version() == EXPECTED_VERSIONS[-1]


# 11
def test_migrations_initialize_a_clean_database(pg_server, fresh_db):
    with pg_server.connect(fresh_db) as conn:
        assert _tables(conn) == set()
        applied = apply_migrations(conn)
        assert applied == EXPECTED_VERSIONS
        assert _tables(conn) == {"schema_migrations", "customers", "api_credentials", "tickets",
                                 "pending_ticket_actions", "idempotency_keys", "handoffs",
                                 "service_credentials", "pending_lead_actions", "leads",
                                 "knowledge_documents", "knowledge_chunks", "chat_conversations"}
        recorded = [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
        assert recorded == EXPECTED_VERSIONS
        customers = conn.execute("SELECT id, display_name FROM customers ORDER BY id").fetchall()
        assert customers == [("CUSTOMER_A", "Synthetic Customer A"), ("CUSTOMER_B", "Synthetic Customer B")]
        owners = dict(conn.execute("SELECT id::text, customer_id FROM tickets").fetchall())
        assert owners == {TICKET_A: "CUSTOMER_A", TICKET_B: "CUSTOMER_B"}
        # No credentials are seeded by migrations.
        assert conn.execute("SELECT count(*) FROM api_credentials").fetchone()[0] == 0


def test_migrations_are_idempotent(pg_server, fresh_db):
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
        assert apply_migrations(conn) == []
        assert conn.execute("SELECT count(*) FROM tickets").fetchone()[0] == 2


def test_modified_applied_migration_is_refused(pg_server, fresh_db):
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
        conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = '0001_initial_schema'")
        with pytest.raises(MigrationError):
            apply_migrations(conn)


# 8
def test_ticket_cannot_reference_unknown_customer(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO tickets (customer_id, contact_name, subject, description, priority)"
                " VALUES ('CUSTOMER_X', 'Test', 'Synthetic', 'Synthetic', 'normal')"
            )


def test_ticket_requires_an_owner(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute(
                "INSERT INTO tickets (customer_id, contact_name, subject, description, priority)"
                " VALUES (NULL, 'Test', 'Synthetic', 'Synthetic', 'normal')"
            )


def test_ticket_owner_cannot_be_moved_to_unknown_customer(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("UPDATE tickets SET customer_id = 'CUSTOMER_X' WHERE id = %s", (TICKET_A,))


def test_customer_with_tickets_cannot_be_deleted(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute("DELETE FROM customers WHERE id = 'CUSTOMER_A'")


def test_invalid_priority_and_status_are_rejected(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE tickets SET status = 'hacked' WHERE id = %s", (TICKET_A,))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE tickets SET priority = 'p0' WHERE id = %s", (TICKET_A,))
