"""Ticket reads. Ticket state always comes from PostgreSQL (INV-08)."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg

TICKET_COLUMNS = (
    "id, customer_id, contact_name, subject, description, priority, status, created_at, updated_at"
)


@dataclass(frozen=True)
class Ticket:
    id: UUID
    customer_id: str
    contact_name: str
    subject: str
    description: str
    priority: str
    status: str
    created_at: datetime
    updated_at: datetime


def get_owned_ticket(conn: psycopg.Connection, ticket_id: UUID, customer_id: str) -> Ticket | None:
    """Return the ticket only if it belongs to `customer_id`.

    Ownership is part of the WHERE clause, so another customer's ticket can never
    be loaded into memory for this request, even by a bug in later code.
    """
    row = conn.execute(
        f"SELECT {TICKET_COLUMNS} FROM tickets WHERE id = %s AND customer_id = %s",
        (ticket_id, customer_id),
    ).fetchone()
    return Ticket(*row) if row else None


def resolve_reference(conn: psycopg.Connection, reference: str, customer_id: str) -> UUID | None:
    """Short reference (e.g. T-1001) -> internal id, ONLY within the authenticated customer's tickets.
    Another customer's reference resolves to None, exactly like an unknown one."""
    row = conn.execute("SELECT id FROM tickets WHERE reference = %s AND customer_id = %s",
                       (reference.upper(), customer_id)).fetchone()
    return row[0] if row else None


def reference_exists(conn: psycopg.Connection, reference: str) -> bool:
    """Audit-only, like ticket_exists. Never exposed to clients."""
    return conn.execute("SELECT EXISTS (SELECT 1 FROM tickets WHERE reference = %s)", (reference.upper(),)).fetchone()[0]


def reference_of(conn: psycopg.Connection, ticket_id: UUID, customer_id: str) -> str | None:
    row = conn.execute("SELECT reference FROM tickets WHERE id = %s AND customer_id = %s", (ticket_id, customer_id)).fetchone()
    return row[0] if row else None


def ticket_exists(conn: psycopg.Connection, ticket_id: UUID) -> bool:
    """Audit-only: distinguishes 'denied' from 'not found' in logs. Never exposed to clients."""
    return conn.execute("SELECT EXISTS (SELECT 1 FROM tickets WHERE id = %s)", (ticket_id,)).fetchone()[0]
