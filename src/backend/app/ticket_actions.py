"""Confirmed, idempotent ticket creation (APP-02).

Two backend guarantees:
  A. No ticket exists before an exact, server-bound confirmation (REQ-CONF-01/02, REQ-CONF-04).
  B. Retries cannot create duplicates (REQ-IDEMP-01/02).

Flow: prepare() stores the exact ticket data plus its fingerprint and returns them; nothing
is created. confirm() must present that fingerprint; inside ONE transaction it creates the
ticket from the STORED data, records the idempotency result and consumes the action, so
either all three happen or none do.
"""
import hashlib
import json
import unicodedata
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

PENDING_ACTION_TTL_MINUTES = 30
OPERATION = "ticket_confirm"
HASH_VERSION = "ticket-v1"
FIELDS = ("contact_name", "subject", "description", "priority")


def normalize_text(value: str) -> str:
    """Deterministic text form: Unicode NFC, outer whitespace removed."""
    return unicodedata.normalize("NFC", value).strip()


def canonical_payload(customer_id: str, data: dict) -> bytes:
    """Explicit canonical serialization: fixed key set, sorted keys, no whitespace, UTF-8."""
    document = {"v": HASH_VERSION, "customer_id": customer_id, **{f: data[f] for f in FIELDS}}
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def payload_hash(customer_id: str, data: dict) -> str:
    return hashlib.sha256(canonical_payload(customer_id, data)).hexdigest()


def request_hash(pending_action_id: UUID, presented_hash: str) -> str:
    """Fingerprint of the confirm request itself, used to detect key reuse with another request."""
    document = {"op": OPERATION, "pending_action_id": str(pending_action_id), "payload_hash": presented_hash}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def summary_text(customer_id: str, data: dict) -> str:
    return (
        f"New ticket for {customer_id} | Contact: {data['contact_name']} | Subject: {data['subject']} | "
        f"Priority: {data['priority']} | Description: {data['description']}"
    )


@dataclass(frozen=True)
class Outcome:
    """Result of confirm(). `status` is the HTTP status; `audit` holds observable facts."""
    status: int
    body: dict
    audit: dict
    idempotency_outcome: str | None = None  # created | replay | conflict


# --- prepare ---------------------------------------------------------------------------

def prepare_lock_key(customer_id: str, conversation_id: str | None) -> int:
    """Advisory-lock key for one confirmation group (customer + conversation scope).

    First 8 bytes of SHA-256 over a namespaced JSON array, read as a signed 64-bit integer.
    Deterministic across processes and restarts (unlike Python's randomized hash()); JSON keeps
    None (no conversation) distinct from any real conversation ID. Distinct groups share a key
    only on a 64-bit hash collision, which would merely serialize them, never change results.
    """
    material = json.dumps(["nexo:ticket_prepare:v1", customer_id, conversation_id], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big", signed=True)


def prepare(conn: psycopg.Connection, customer_id: str, data: dict, conversation_id: str | None) -> dict:
    data = {f: normalize_text(data[f]) for f in FIELDS}
    digest = payload_hash(customer_id, data)
    with conn.transaction():
        # APP02-01: serialize prepare() per confirmation group. Without this, two concurrent
        # transactions can both run the supersede UPDATE before either INSERT is committed
        # (READ COMMITTED) and leave two pending actions. The lock is transaction-scoped:
        # released automatically on COMMIT or ROLLBACK.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (prepare_lock_key(customer_id, conversation_id),))
        # A newer preparation in the same conversation invalidates older unconfirmed ones
        # (REQ-CONF-02: if the data changes, confirmation must be requested again).
        conn.execute(
            "UPDATE pending_ticket_actions SET status = 'superseded'"
            " WHERE customer_id = %s AND status = 'pending' AND conversation_id IS NOT DISTINCT FROM %s",
            (customer_id, conversation_id),
        )
        row = conn.execute(
            "INSERT INTO pending_ticket_actions"
            " (customer_id, conversation_id, contact_name, subject, description, priority, payload_hash, expires_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(mins => %s))"
            " RETURNING id, status, expires_at",
            (customer_id, conversation_id, data["contact_name"], data["subject"], data["description"],
             data["priority"], digest, PENDING_ACTION_TTL_MINUTES),
        ).fetchone()
    return {
        "pending_action_id": str(row[0]),
        "status": row[1],
        "confirmation_required": True,
        "summary": {"customer_id": customer_id, **data},
        "summary_text": summary_text(customer_id, data),
        "payload_hash": digest,
        "expires_at": row[2].isoformat(),
    }


# --- confirm ---------------------------------------------------------------------------

def _ticket_body(row) -> dict:
    keys = ("id", "customer_id", "contact_name", "subject", "description", "priority", "status",
            "created_at", "updated_at")
    body = dict(zip(keys, row))
    body["id"] = str(body["id"])
    body["created_at"] = body["created_at"].isoformat()
    body["updated_at"] = body["updated_at"].isoformat()
    return body


def _lookup_idempotency(conn, customer_id: str, key: str):
    return conn.execute(
        "SELECT request_hash, response_status, response_body, pending_action_id, ticket_id"
        " FROM idempotency_keys WHERE customer_id = %s AND operation = %s AND idempotency_key = %s",
        (customer_id, OPERATION, key),
    ).fetchone()


def _replay_or_conflict(record, req_hash: str) -> Outcome:
    stored_hash, status, body, action_id, ticket_id = record
    audit = {"pending_action_id": str(action_id), "ticket_id": str(ticket_id)}
    if stored_hash == req_hash:
        return Outcome(status, body, {**audit, "confirmation_result": "replayed"}, "replay")
    return Outcome(409, {"detail": "Idempotency-Key was already used with a different request",
                         "code": "idempotency_key_conflict"},
                   {**audit, "confirmation_result": "rejected"}, "conflict")


def _invalid(code: str, detail: str, action_id: UUID, **extra) -> Outcome:
    return Outcome(409, {"detail": detail, "code": code, **extra},
                   {"pending_action_id": str(action_id), "confirmation_result": code})


def _attempt(conn, customer_id: str, action_id: UUID, presented_hash: str, key: str, req_hash: str) -> Outcome:
    with conn.transaction():
        record = _lookup_idempotency(conn, customer_id, key)
        if record:
            return _replay_or_conflict(record, req_hash)

        # Ownership is part of the lookup: another customer's action is indistinguishable from none.
        action = conn.execute(
            "SELECT customer_id, contact_name, subject, description, priority, payload_hash, status,"
            " expires_at <= now() FROM pending_ticket_actions WHERE id = %s AND customer_id = %s FOR UPDATE",
            (action_id, customer_id),
        ).fetchone()
        if action is None:
            exists = conn.execute("SELECT EXISTS (SELECT 1 FROM pending_ticket_actions WHERE id = %s)",
                                  (action_id,)).fetchone()[0]
            return Outcome(404, {"detail": "Pending action not found"},
                           {"pending_action_id": str(action_id),
                            "confirmation_result": "denied_not_owner" if exists else "not_found"})

        # Re-check after acquiring the row lock: a concurrent request with the same key may have
        # just committed (READ COMMITTED: this new statement sees it).
        record = _lookup_idempotency(conn, customer_id, key)
        if record:
            return _replay_or_conflict(record, req_hash)

        owner, contact, subject, description, priority, stored_hash, status, expired = action
        if status == "consumed":
            ticket = conn.execute("SELECT id FROM tickets WHERE source_action_id = %s", (action_id,)).fetchone()
            return _invalid("confirmation_already_used",
                            "This confirmation was already used; no new ticket was created",
                            action_id, ticket_id=str(ticket[0]) if ticket else None)
        if status != "pending" or expired:
            if status == "pending":
                conn.execute("UPDATE pending_ticket_actions SET status = 'expired' WHERE id = %s", (action_id,))
            return _invalid("confirmation_invalid",
                            "Confirmation is no longer valid; prepare the ticket again", action_id)

        data = {"contact_name": contact, "subject": subject, "description": description, "priority": priority}
        if presented_hash != stored_hash or payload_hash(owner, data) != stored_hash:
            return _invalid("confirmation_mismatch",
                            "Confirmation does not match the prepared ticket data; prepare again", action_id)

        # Create the ticket from the STORED data; the owner is the authenticated customer.
        ticket = conn.execute(
            "INSERT INTO tickets (customer_id, contact_name, subject, description, priority, status, source_action_id)"
            " VALUES (%s, %s, %s, %s, %s, 'open', %s)"
            " RETURNING id, customer_id, contact_name, subject, description, priority, status, created_at, updated_at",
            (customer_id, contact, subject, description, priority, action_id),
        ).fetchone()
        body = _ticket_body(ticket)
        conn.execute(
            "INSERT INTO idempotency_keys (customer_id, operation, idempotency_key, request_hash,"
            " pending_action_id, ticket_id, response_status, response_body)"
            " VALUES (%s, %s, %s, %s, %s, %s, 201, %s)",
            (customer_id, OPERATION, key, req_hash, action_id, ticket[0], Jsonb(body)),
        )
        conn.execute(
            "UPDATE pending_ticket_actions SET status = 'consumed', consumed_at = now() WHERE id = %s",
            (action_id,),
        )
    # Only reached after COMMIT: success is reported strictly from persisted data (INV-07).
    return Outcome(201, body, {"pending_action_id": str(action_id), "ticket_id": body["id"],
                               "confirmation_result": "confirmed"}, "created")


def cancel(conn: psycopg.Connection, customer_id: str, action_id: UUID) -> bool:
    """AGENT-01B: withdraw a prepared, not yet confirmed action. Owner-scoped; only 'pending' can be cancelled.
    A cancelled action can never be confirmed (confirm() rejects every status other than 'pending')."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE pending_ticket_actions SET status = 'cancelled' WHERE id = %s AND customer_id = %s"
            " AND status = 'pending' RETURNING id", (action_id, customer_id)).fetchone()
    return row is not None


def confirm(conn: psycopg.Connection, customer_id: str, action_id: UUID, presented_hash: str, key: str) -> Outcome:
    req_hash = request_hash(action_id, presented_hash)
    try:
        return _attempt(conn, customer_id, action_id, presented_hash, key, req_hash)
    except psycopg.errors.UniqueViolation as exc:
        # A concurrent request won the race; its transaction committed and ours rolled back
        # completely (no ticket from this attempt). Answer from the committed state.
        constraint = exc.diag.constraint_name
        if constraint == "idempotency_keys_pkey":
            record = _lookup_idempotency(conn, customer_id, key)
            if record:
                return _replay_or_conflict(record, req_hash)
        if constraint == "tickets_source_action_id_key":
            # Database-level backstop: this action already produced a ticket.
            ticket = conn.execute("SELECT id FROM tickets WHERE source_action_id = %s AND customer_id = %s",
                                  (action_id, customer_id)).fetchone()
            return _invalid("confirmation_already_used",
                            "This confirmation was already used; no new ticket was created",
                            action_id, ticket_id=str(ticket[0]) if ticket else None)
        raise
