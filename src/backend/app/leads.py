"""Confirmed lead creation through n8n (APP-03B).

Journey:  prepare  ->  confirm (backend, customer session)  ->  n8n webhook  ->  n8n HTTP Request
          ->  POST /internal/leads (backend, n8n service credential)  ->  PostgreSQL.

Invariants:
  * Only `internal_create` inserts into `leads`, and only for an action the user CONFIRMED with the
    same Idempotency-Key, with a payload identical to what was shown (fingerprint re-verified).
  * The confirm endpoint never writes a lead; it marks the action `confirmed`, dispatches to n8n and
    then reports success only from the lead row it reads back from PostgreSQL.
  * One lead per action (UNIQUE source_action_id) and one action per key (UNIQUE key hash per session).
  * The action becomes `consumed` only in the same transaction that inserts the lead, so a failed or
    lost hop leaves it `confirmed` and a retry with the same key resumes safely.
"""
import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from uuid import UUID

import psycopg

from app.db import connect
from app.ticket_actions import normalize_text

PENDING_ACTION_TTL_MINUTES = 30
DISPATCH_TIMEOUT_SECONDS = 15
HASH_VERSION = "lead-v1"
FIELDS = ("company_name", "contact_name", "contact_email", "need")
STATUS_MESSAGE = ("Registered for commercial follow-up. No price, discount, contract or date has been "
                  "committed; the sales team will review the request.")
LEAD_COLUMNS = ("id, company_name, contact_name, contact_email, need, requested_by_customer_id, "
                "workflow_execution_id, created_at, updated_at")


# --- canonical data ---------------------------------------------------------------------

def normalize_lead(data: dict) -> dict:
    """Deterministic form: NFC + trimmed; e-mail additionally lower-cased."""
    lead = {f: normalize_text(data[f]) for f in FIELDS}
    lead["contact_email"] = lead["contact_email"].lower()
    return lead


def payload_hash(requested_by: str, lead: dict) -> str:
    document = {"v": HASH_VERSION, "requested_by": requested_by, **{f: lead[f] for f in FIELDS}}
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def key_fingerprint(key: str) -> str:
    """Short, non-reversible label for logs (the raw Idempotency-Key is never logged)."""
    return key_hash(key)[:12]


def prepare_lock_key(requested_by: str, conversation_id: str | None) -> int:
    material = json.dumps(["nexo:lead_prepare:v1", requested_by, conversation_id], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big", signed=True)


def summary_text(lead: dict) -> str:
    return (f"New commercial request | Company: {lead['company_name']} | Contact: {lead['contact_name']} "
            f"<{lead['contact_email']}> | Need: {lead['need']}")


def _lead_body(row) -> dict:
    keys = ("id", "company_name", "contact_name", "contact_email", "need", "requested_by_customer_id",
            "workflow_execution_id", "created_at", "updated_at")
    body = dict(zip(keys, row))
    body["id"] = str(body["id"])
    body["created_at"] = body["created_at"].isoformat()
    body["updated_at"] = body["updated_at"].isoformat()
    body["status_message"] = STATUS_MESSAGE
    return body


@dataclass
class Outcome:
    status: int
    body: dict
    audit: dict = field(default_factory=dict)
    idempotency_outcome: str | None = None  # created | replay | conflict
    envelope: dict | None = None            # set when the caller must dispatch to n8n


def _reject(status: int, code: str, detail: str, action_id, outcome=None, **extra) -> Outcome:
    return Outcome(status, {"detail": detail, "code": code, **extra},
                   {"pending_action_id": str(action_id), "confirmation_result": code}, outcome)


# --- prepare ------------------------------------------------------------------------------

def prepare(conn: psycopg.Connection, requested_by: str, data: dict, conversation_id: str | None) -> dict:
    lead = normalize_lead(data)
    digest = payload_hash(requested_by, lead)
    with conn.transaction():
        # Serialize prepare per (session, conversation) group, then supersede the older pending one.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (prepare_lock_key(requested_by, conversation_id),))
        conn.execute(
            "UPDATE pending_lead_actions SET status = 'superseded' WHERE requested_by_customer_id = %s"
            " AND status = 'pending' AND conversation_id IS NOT DISTINCT FROM %s",
            (requested_by, conversation_id),
        )
        row = conn.execute(
            "INSERT INTO pending_lead_actions (requested_by_customer_id, conversation_id, company_name,"
            " contact_name, contact_email, need, payload_hash, expires_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, now() + make_interval(mins => %s)) RETURNING id, status, expires_at",
            (requested_by, conversation_id, lead["company_name"], lead["contact_name"], lead["contact_email"],
             lead["need"], digest, PENDING_ACTION_TTL_MINUTES),
        ).fetchone()
    return {
        "pending_action_id": str(row[0]),
        "status": row[1],
        "confirmation_required": True,
        "summary": lead,
        "summary_text": summary_text(lead),
        "payload_hash": digest,
        "expires_at": row[2].isoformat(),
    }


# --- confirm, phase 1 (before the n8n hop) --------------------------------------------------

def _stored(action) -> dict:
    return dict(zip(FIELDS, action[2:6]))


def begin_confirm(conn: psycopg.Connection, requested_by: str, action_id: UUID, presented_hash: str,
                  key: str) -> Outcome:
    kh = key_hash(key)
    try:
        with conn.transaction():
            action = conn.execute(
                "SELECT requested_by_customer_id, status, company_name, contact_name, contact_email, need,"
                " payload_hash, confirm_key_sha256, expires_at <= now()"
                " FROM pending_lead_actions WHERE id = %s AND requested_by_customer_id = %s FOR UPDATE",
                (action_id, requested_by),
            ).fetchone()
            if action is None:
                exists = conn.execute("SELECT EXISTS (SELECT 1 FROM pending_lead_actions WHERE id = %s)",
                                      (action_id,)).fetchone()[0]
                return Outcome(404, {"detail": "Pending action not found"},
                               {"pending_action_id": str(action_id),
                                "confirmation_result": "denied_not_owner" if exists else "not_found"})
            other = conn.execute(
                "SELECT 1 FROM pending_lead_actions WHERE requested_by_customer_id = %s"
                " AND confirm_key_sha256 = %s AND id <> %s", (requested_by, kh, action_id)).fetchone()
            if other:
                return _reject(409, "idempotency_key_conflict",
                               "Idempotency-Key was already used with a different request", action_id, "conflict")

            status, stored_hash, bound_key, expired = action[1], action[6], action[7], action[8]
            if status == "consumed":
                lead = conn.execute(f"SELECT {LEAD_COLUMNS} FROM leads WHERE source_action_id = %s",
                                    (action_id,)).fetchone()
                if bound_key == kh and presented_hash == stored_hash:
                    return Outcome(201, _lead_body(lead), {"pending_action_id": str(action_id),
                                   "lead_id": str(lead[0]), "confirmation_result": "replayed_local"}, "replay")
                if bound_key == kh:
                    return _reject(409, "idempotency_key_conflict",
                                   "Idempotency-Key was already used with a different request", action_id, "conflict")
                return _reject(409, "confirmation_already_used",
                               "This confirmation was already used; no new lead was created", action_id,
                               lead_id=str(lead[0]))
            if status == "confirmed":
                if bound_key != kh:
                    return _reject(409, "confirmation_in_progress",
                                   "This action was confirmed with a different Idempotency-Key; retry with that key",
                                   action_id)
                if presented_hash != stored_hash:
                    return _reject(409, "idempotency_key_conflict",
                                   "Idempotency-Key was already used with a different request", action_id, "conflict")
                result = "redispatch"
            elif status != "pending" or expired:
                if status == "pending":
                    conn.execute("UPDATE pending_lead_actions SET status = 'expired' WHERE id = %s", (action_id,))
                return _reject(409, "confirmation_invalid",
                               "Confirmation is no longer valid; prepare the lead again", action_id)
            else:
                lead = _stored(action)
                if presented_hash != stored_hash or payload_hash(requested_by, lead) != stored_hash:
                    return _reject(409, "confirmation_mismatch",
                                   "Confirmation does not match the prepared lead data; prepare again", action_id)
                conn.execute(
                    "UPDATE pending_lead_actions SET status = 'confirmed', confirm_key_sha256 = %s,"
                    " confirmed_at = now() WHERE id = %s", (kh, action_id))
                result = "confirmed"
    except psycopg.errors.UniqueViolation:
        # A concurrent confirmation bound this key to another action of this session.
        return _reject(409, "idempotency_key_conflict",
                       "Idempotency-Key was already used with a different request", action_id, "conflict")
    envelope = {"pending_action_id": str(action_id), "idempotency_key": key, "payload_hash": stored_hash,
                "lead": _stored(action)}
    return Outcome(0, {}, {"pending_action_id": str(action_id), "confirmation_result": result}, None, envelope)


# --- the n8n hop ----------------------------------------------------------------------------

@dataclass
class DispatchResult:
    http_status: int | None       # None = no HTTP response (n8n unreachable, timeout, connection reset)
    body: dict | None
    error: str | None


def dispatch(webhook_url: str, envelope: dict, request_id: str, conversation_id: str | None) -> DispatchResult:
    headers = {"Content-Type": "application/json", "X-Request-ID": request_id}
    if conversation_id:
        headers["X-Conversation-ID"] = conversation_id
    req = urllib.request.Request(webhook_url, method="POST", headers=headers,
                                 data=json.dumps(envelope).encode("utf-8"))
    try:
        with urllib.request.urlopen(req, timeout=DISPATCH_TIMEOUT_SECONDS) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, OSError, ValueError) as e:  # refused, DNS, timeout, reset
        return DispatchResult(None, None, type(e).__name__)
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    return DispatchResult(status, body if isinstance(body, dict) else None, None)


# --- confirm, phase 2 (after the n8n hop): success only from PostgreSQL ------------------------

def finish_confirm(conn: psycopg.Connection, requested_by: str, action_id: UUID, result: DispatchResult) -> Outcome:
    lead = conn.execute(f"SELECT {LEAD_COLUMNS} FROM leads WHERE source_action_id = %s"
                        " AND requested_by_customer_id = %s", (action_id, requested_by)).fetchone()
    audit = {"pending_action_id": str(action_id), "n8n_status": result.http_status}
    if result.error:
        audit["n8n_error"] = result.error
    if lead is not None:
        reported = (result.body or {}).get("idempotency")
        if result.http_status in (200, 201) and reported in ("created", "replay"):
            outcome, confirmation = reported, ("confirmed" if reported == "created" else "replayed")
        else:
            # The lead IS committed although the hop failed (e.g. response lost): recover, don't duplicate.
            outcome, confirmation = "replay", "recovered_after_dispatch"
        audit.update(lead_id=str(lead[0]), workflow_execution_id=lead[6], confirmation_result=confirmation)
        return Outcome(201, _lead_body(lead), audit, outcome)
    if result.http_status is not None and 200 <= result.http_status < 300:
        audit["confirmation_result"] = "workflow_success_without_lead"
        return Outcome(502, {"detail": "The workflow reported success but no lead was persisted; nothing was created",
                             "code": "workflow_inconsistent"}, audit)
    if result.http_status is not None and 400 <= result.http_status < 500:
        audit["confirmation_result"] = "workflow_rejected"
        upstream = (result.body or {}).get("code")
        return Outcome(502, {"detail": "The lead workflow rejected the request; no lead was created",
                             "code": "workflow_rejected", "upstream_code": upstream}, audit)
    audit["confirmation_result"] = "dispatch_failed"
    return Outcome(503, {"detail": "Lead creation could not be confirmed (automation unavailable); retry with the "
                                   "same Idempotency-Key to get the definitive result",
                         "code": "lead_not_confirmed"}, audit)


def confirm_via_workflow(settings, requested_by: str, action_id: UUID, presented_hash: str, key: str,
                         request_id: str, conversation_id: str | None) -> Outcome:
    """The complete user confirmation: phase 1 -> n8n hop -> phase 2. Shared by POST /leads/confirm and the chat
    agent (AGENT-01B), so both follow exactly the same rules. Raises psycopg.Error if the database is unavailable
    (callers must not claim success; a retry with the same key gives the definitive result)."""
    with connect(settings, autocommit=True) as conn:
        outcome = begin_confirm(conn, requested_by, action_id, presented_hash, key)
    if outcome.envelope is not None:
        result = dispatch(settings.n8n_lead_webhook_url, outcome.envelope, request_id, conversation_id)
        with connect(settings, autocommit=True) as conn:
            outcome = finish_confirm(conn, requested_by, action_id, result)
    return outcome


def cancel(conn: psycopg.Connection, requested_by: str, action_id: UUID) -> bool:
    """AGENT-01B: withdraw a prepared lead that was not confirmed yet. Owner-scoped; a 'confirmed' action (already
    handed to n8n) can NOT be cancelled. A cancelled action can never be confirmed (begin_confirm rejects it)."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE pending_lead_actions SET status = 'cancelled' WHERE id = %s AND requested_by_customer_id = %s"
            " AND status = 'pending' RETURNING id", (action_id, requested_by)).fetchone()
    return row is not None


# --- private write: the ONLY place a lead is inserted -------------------------------------------

def internal_create(conn: psycopg.Connection, action_id: UUID, presented_hash: str, lead_in: dict, key: str,
                    execution_id: str) -> Outcome:
    kh = key_hash(key)
    lead_norm = normalize_lead(lead_in)
    try:
        with conn.transaction():
            action = conn.execute(
                "SELECT requested_by_customer_id, status, company_name, contact_name, contact_email, need,"
                " payload_hash, confirm_key_sha256 FROM pending_lead_actions WHERE id = %s FOR UPDATE",
                (action_id,),
            ).fetchone()
            if action is None:
                return _reject(404, "action_not_found", "Pending action not found", action_id)
            requested_by, status, stored_hash, bound_key = action[0], action[1], action[6], action[7]
            existing = conn.execute(f"SELECT {LEAD_COLUMNS} FROM leads WHERE source_action_id = %s",
                                    (action_id,)).fetchone()
            body_matches = presented_hash == stored_hash and payload_hash(requested_by, lead_norm) == stored_hash
            if existing is not None:
                if bound_key == kh and body_matches:
                    return Outcome(201, {**_lead_body(existing), "idempotency": "replay"},
                                   {"pending_action_id": str(action_id), "lead_id": str(existing[0])}, "replay")
                return _reject(409, "idempotency_key_conflict",
                               "This action already produced a lead for a different request", action_id, "conflict")
            if status != "confirmed":
                return _reject(409, "action_not_confirmed",
                               "The lead action has not been confirmed by the user", action_id)
            if bound_key != kh:
                return _reject(409, "idempotency_key_conflict",
                               "Idempotency-Key does not match the confirmation", action_id, "conflict")
            if not body_matches:
                return _reject(409, "payload_mismatch",
                               "Lead data does not match the confirmed action", action_id)
            stored = _stored(action)  # authoritative copy (verified equal to the body by the fingerprint)
            row = conn.execute(
                f"INSERT INTO leads (company_name, contact_name, contact_email, need, requested_by_customer_id,"
                f" source_action_id, workflow_execution_id) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                f" RETURNING {LEAD_COLUMNS}",
                (stored["company_name"], stored["contact_name"], stored["contact_email"], stored["need"],
                 requested_by, action_id, execution_id),
            ).fetchone()
            conn.execute("UPDATE pending_lead_actions SET status = 'consumed', consumed_at = now() WHERE id = %s",
                         (action_id,))
    except psycopg.errors.UniqueViolation:
        # A duplicate delivery committed first; answer from the committed row.
        existing = conn.execute(f"SELECT {LEAD_COLUMNS} FROM leads WHERE source_action_id = %s",
                                (action_id,)).fetchone()
        if existing is None:
            raise
        return Outcome(201, {**_lead_body(existing), "idempotency": "replay"},
                       {"pending_action_id": str(action_id), "lead_id": str(existing[0])}, "replay")
    return Outcome(201, {**_lead_body(row), "idempotency": "created"},
                   {"pending_action_id": str(action_id), "lead_id": str(row[0])}, "created")
