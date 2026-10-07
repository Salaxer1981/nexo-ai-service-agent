"""Idempotent human handoffs (APP-03A).

A handoff records that a conversation needs human attention. It is persisted as 'pending':
the system has no evidence that a person has picked it up, so it never says so (REQ-HANDOFF-03).
No email or message is sent (REQ-HANDOFF-04).

Idempotency: the handoff row carries (customer_id, idempotency_key) UNIQUE plus the request
fingerprint. One `INSERT … ON CONFLICT DO NOTHING` either creates the handoff or, if the key
was already used (even by a concurrent request, which it waits for), yields to the committed row,
which is then replayed (same request) or reported as a conflict (different request).
"""
import hashlib
import json
from dataclasses import dataclass

import psycopg

from app.ticket_actions import normalize_text

OPERATION = "handoff_create"
REASONS = ("critical_incident", "human_requested", "unsafe_to_resolve")
STATUS_MESSAGE = ("Registered and pending human attention. "
                  "It has not yet been picked up by a person; no response time is guaranteed.")
COLUMNS = "id, customer_id, conversation_id, reason, summary, status, created_at, updated_at, request_hash"


@dataclass(frozen=True)
class Outcome:
    status: int
    body: dict
    idempotency_outcome: str  # created | replay | conflict
    handoff_id: str


def request_hash(conversation_id: str, reason: str, summary: str) -> str:
    """Fingerprint of the effective request (customer scope is implied by the key's scope)."""
    document = {"op": OPERATION, "conversation_id": conversation_id, "reason": reason, "summary": summary}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def _body(row) -> dict:
    handoff_id, customer_id, conversation_id, reason, summary, status, created_at, updated_at, _ = row
    return {
        "id": str(handoff_id),
        "customer_id": customer_id,
        "conversation_id": conversation_id,
        "reason": reason,
        "summary": summary,
        "status": status,
        "status_message": STATUS_MESSAGE,
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }


def create(conn: psycopg.Connection, customer_id: str, conversation_id: str, reason: str, summary: str,
           key: str) -> Outcome:
    summary = normalize_text(summary)
    req_hash = request_hash(conversation_id, reason, summary)
    with conn.transaction():
        row = conn.execute(
            f"INSERT INTO handoffs (customer_id, conversation_id, reason, summary, idempotency_key, request_hash)"
            f" VALUES (%s, %s, %s, %s, %s, %s)"
            f" ON CONFLICT ON CONSTRAINT handoffs_customer_idempotency_key DO NOTHING RETURNING {COLUMNS}",
            (customer_id, conversation_id, reason, summary, key, req_hash),
        ).fetchone()
        if row is not None:
            return Outcome(201, _body(row), "created", str(row[0]))
        # Key already used by this customer (a concurrent holder was waited for and committed).
        existing = conn.execute(f"SELECT {COLUMNS} FROM handoffs WHERE customer_id = %s AND idempotency_key = %s",
                                (customer_id, key)).fetchone()
    if existing is None:  # not reachable: a conflict implies a committed row with this key
        raise RuntimeError("idempotency conflict without a committed handoff")
    if existing[-1] == req_hash:
        return Outcome(201, _body(existing), "replay", str(existing[0]))
    return Outcome(409, {"detail": "Idempotency-Key was already used with a different request",
                         "code": "idempotency_key_conflict"}, "conflict", str(existing[0]))
