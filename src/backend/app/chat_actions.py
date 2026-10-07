"""AGENT-01B: the narrow COMMAND side of POST /chat.

The only chat code that changes business state, and it does so exclusively by calling the existing services:
ticket_actions.prepare/confirm/cancel (APP-02), leads.prepare/confirm_via_workflow/cancel (APP-03B, n8n is the only
lead-creation path) and handoffs.create (APP-03A). It never inserts tickets, leads or handoffs itself.

Rules enforced here (the model can influence none of them):
- Final creation happens ONLY through the deterministic gate: the user's whole message is CONFIRMAR/CONFIRM
  (case-insensitive, trimmed). The model is not even called for that turn and has no confirmation field.
- The action to confirm is the one this conversation's state points to (customer + conversation scoped), never
  an id from model output; the idempotency key is derived from (conversation, action id); the services re-check
  ownership, status, expiry and payload fingerprint.
- One conversation = at most one pending action; if the action tables show anything else, nothing is executed.
- Turns of one conversation are serialized by an advisory lock, so concurrent messages cannot interleave.
Conversation state is a pointer plus the fields of an action that is still being collected; the authoritative
payload of a prepared action lives in pending_*_actions.

AGENT-01BF1 invariants:
- A CONFIRMAR executes ONLY the exact prepared version the client presented: every awaiting-confirmation response
  carries a confirmation_token = f(action id, payload hash); the confirmation must echo it and it is re-checked
  against the state re-read UNDER the conversation lock. A missing or different token (re-prepared meanwhile, or the
  newer summary never reached the user) fails closed and re-shows the current summary for review.
- Cancellation is answered from the AUTHORITATIVE action state after the owner-scoped cancel attempt, never from the
  cached conversation state.
- Each state change increments chat_conversations.revision; a model proposal is published only if the revision it
  was interpreted against is still current.

AGENT-01BF2 invariants (the business action status is AUTHORITATIVE; the revision is only a concurrency signal):
- Before a model proposal is published, the pointed action is re-read (customer AND conversation AND action id) and
  must still be 'pending'. consumed -> chat synchronized to completed; confirmed (lead in flight) -> pointer kept for
  retry/recovery; cancelled/superseded/expired -> synchronized; missing -> fail closed. In every non-pending case the
  stale proposal is rejected: it can NEVER replace a recovery pointer with a new prepared action.
- Every confirm/cancel attempt advances the revision BEFORE touching business state, so even if the final chat save
  is lost, an interpretation that started earlier is stale.
- Cancellation proves conversation membership BEFORE any cancel mutation.

AGENT-01BF3 invariants:
- Proposal publication is ONE transaction under the conversation lock: service prepare-group advisory lock ->
  pointed action row SELECT ... FOR UPDATE -> authoritative recheck -> (only if still 'pending') prepare B through
  the existing service (nested = savepoint) and publish -> single COMMIT. No other route can consume/confirm A between
  the check and the re-prepare: it waits on A's row lock. The model call happens BEFORE this, outside any transaction.
- Lock order (same as the APP-02/APP-03B prepare path): conversation advisory lock -> prepare-group advisory xact
  lock -> action row lock -> writes. Confirm paths take only the row lock, so no cycle exists.
- CANCELAR: pointer membership validated first (zero cancel-service calls if invalid) -> revision advanced -> only
  then any cancel mutation, including the conversation's other pending actions.
"""
import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb
from pydantic import ValidationError

from app import handoffs, leads, ticket_actions, tickets
from app.db import connect
from app.schemas import LeadDraft, TicketDraft

CONFIRM_WORDS = frozenset({"confirmar", "confirm"})
CANCEL_WORDS = frozenset({"cancelar", "cancel"})
KIND_OF_INTENT = {"create_ticket": "ticket", "create_lead": "lead"}
INTENT_OF_KIND = {"ticket": "create_ticket", "lead": "create_lead"}
FIELDS = {"ticket": ("contact_name", "subject", "description", "priority"),
          "lead": ("company_name", "contact_name", "contact_email", "need")}
MODELS = {"ticket": TicketDraft, "lead": LeadDraft}
ASK = {
    "contact_name": "tu nombre (persona de contacto)",
    "subject": "un asunto breve de la incidencia",
    "description": "una descripción del problema",
    "priority": ("si la incidencia deja sin servicio a toda la empresa (crítica) o afecta a una persona sin bloquear "
                 "toda su actividad (normal)"),
    "company_name": "el nombre de la empresa",
    "contact_email": "un correo electrónico de contacto",
    "need": "qué necesitáis",
}
LEAD_ASK = dict(ASK, contact_name="el nombre de la persona de contacto")
REASON_ES = {"human_requested": "petición expresa de atención humana", "unsafe_to_resolve": "caso que no puede resolverse con seguridad",
             "critical_incident": "incidencia crítica"}
PRIORITY_ES = {"normal": "normal", "critical": "crítica"}
STATUS_ES = {"open": "abierto", "in_progress": "en curso", "resolved": "resuelto", "closed": "cerrado"}
HANDOFF_PENDING_ES = ("Queda registrado y pendiente de atención humana: todavía no lo ha recogido ninguna persona y no se "
                      "garantiza un plazo de respuesta.")
LEAD_STATUS_ES = ("No se ha comprometido ningún precio, descuento, contrato ni fecha; el equipo comercial revisará la "
                  "solicitud.")
CONFIRM_HINT = "Para ejecutarlo responde CONFIRMAR. Para descartarlo, responde CANCELAR."


@dataclass
class State:
    collecting_kind: str | None = None
    draft: dict | None = None
    action_kind: str | None = None
    action_id: UUID | None = None
    action_payload_hash: str | None = None
    action_status: str | None = None
    revision: int = 0


@dataclass
class ChatResult:
    intent: str
    status: str
    answer: str
    http_status: int = 200
    code: str | None = None
    result: dict | None = None
    pending_action: dict | None = None
    next_step: dict | None = None
    audit: dict = field(default_factory=dict)


def gate(message: str) -> str | None:
    """Deterministic: only the WHOLE message, trimmed and case-folded, counts. 'vale', 'sí', 'ok', 'confirmar ya',
    or a model's opinion never do."""
    word = message.strip().casefold()
    if word in CONFIRM_WORDS:
        return "confirm"
    if word in CANCEL_WORDS:
        return "cancel"
    return None


def confirmation_key(conversation_id: str, action_id: UUID) -> str:
    """Deterministic Idempotency-Key bound to conversation + action (the services scope it to the customer)."""
    return f"chat:{conversation_id}:{action_id}"


def fingerprint(value) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def confirmation_token(action_id: UUID, payload_hash: str) -> str:
    """Names ONE prepared version (action id + payload fingerprint). Not a secret and not an authorization: identity
    comes from the bearer token and every service re-checks ownership; it only proves WHICH summary is approved."""
    return hashlib.sha256(f"nexo:chat_confirm:v1:{action_id}:{payload_hash}".encode("utf-8")).hexdigest()[:16]


def state_token(st: "State") -> str | None:
    return confirmation_token(st.action_id, st.action_payload_hash) if st.action_id else None


# --- state (reads are used by the READ side too) ----------------------------------------------------------
def load_state(conn: psycopg.Connection, customer_id: str, conversation_id: str) -> State:
    row = conn.execute(
        "SELECT collecting_kind, draft, action_kind, action_id, action_payload_hash, action_status, revision"
        " FROM chat_conversations WHERE customer_id = %s AND conversation_id = %s",
        (customer_id, conversation_id)).fetchone()
    return State(*row) if row else State()


def action_fields(conn, kind: str, action_id: UUID, customer_id: str, conversation_id: str) -> dict | None:
    """The authoritative prepared payload, scoped to customer AND conversation (defense in depth)."""
    if kind == "ticket":
        row = conn.execute("SELECT contact_name, subject, description, priority FROM pending_ticket_actions"
                           " WHERE id = %s AND customer_id = %s AND conversation_id = %s",
                           (action_id, customer_id, conversation_id)).fetchone()
    else:
        row = conn.execute("SELECT company_name, contact_name, contact_email, need FROM pending_lead_actions"
                           " WHERE id = %s AND requested_by_customer_id = %s AND conversation_id = %s",
                           (action_id, customer_id, conversation_id)).fetchone()
    return dict(zip(FIELDS[kind], row)) if row else None


def action_status(conn, kind: str, action_id: UUID, customer_id: str, conversation_id: str,
                  for_update: bool = False) -> str | None:
    """Authoritative status of the pointed action (customer AND conversation scoped); None if not found.
    for_update=True locks the row until the caller's transaction ends (only inside a transaction)."""
    table, owner = (("pending_ticket_actions", "customer_id") if kind == "ticket"
                    else ("pending_lead_actions", "requested_by_customer_id"))
    lock = " FOR UPDATE" if for_update else ""
    row = conn.execute(f"SELECT status FROM {table} WHERE id = %s AND {owner} = %s AND conversation_id = %s{lock}",
                       (action_id, customer_id, conversation_id)).fetchone()
    return row[0] if row else None


def created_object(conn, kind: str, action_id: UUID, customer_id: str) -> dict | None:
    """The business object an action produced, if any (one per action: UNIQUE source_action_id)."""
    if kind == "ticket":
        row = conn.execute("SELECT id, reference FROM tickets WHERE source_action_id = %s AND customer_id = %s",
                           (action_id, customer_id)).fetchone()
        return {"kind": "ticket", "id": str(row[0]), "reference": row[1]} if row else None
    row = conn.execute("SELECT id FROM leads WHERE source_action_id = %s AND requested_by_customer_id = %s",
                       (action_id, customer_id)).fetchone()
    return {"kind": "lead", "id": str(row[0])} if row else None


def missing(kind: str, values: dict) -> list:
    return [f for f in FIELDS[kind] if f not in values]


def model_context(conn, state: State, customer_id: str, conversation_id: str) -> dict:
    """What the interpreter may see: the action being collected and the customer's own values so far."""
    if state.action_status == "pending":
        return {"collecting": state.action_kind, "awaiting_confirmation": True,
                "collected": action_fields(conn, state.action_kind, state.action_id, customer_id, conversation_id) or {}}
    if state.collecting_kind:
        return {"collecting": state.collecting_kind, "collected": state.draft or {},
                "missing": missing(state.collecting_kind, state.draft or {})}
    return {"collecting": None}


def ask_missing(kind: str, fields_missing: list, rejected: list | None = None) -> str:
    labels = LEAD_ASK if kind == "lead" else ASK
    what = "la incidencia" if kind == "ticket" else "la solicitud comercial"
    text = f"Para preparar {what} necesito " + "; ".join(labels[f] for f in fields_missing) + "."
    if rejected:
        text += " (" + ", ".join(labels[f] for f in rejected) + ": no lo he podido validar, indícalo de nuevo.)"
    return text


def reprompt(state: State) -> str | None:
    """While an action is being collected, an unclear message re-asks for what is missing (no write)."""
    if state.collecting_kind:
        return ask_missing(state.collecting_kind, missing(state.collecting_kind, state.draft or {}))
    if state.action_status == "pending":
        return "Tienes una acción preparada pendiente. " + CONFIRM_HINT
    return None


def pending_reminder(state: State) -> dict | None:
    if state.action_status == "pending":
        return {"action": INTENT_OF_KIND[state.action_kind], "awaiting": "CONFIRMAR", "executed": False}
    return None


def _save(conn, customer_id: str, conversation_id: str, st: State) -> None:
    """Every state change increments the revision (monotonic per conversation)."""
    conn.execute(
        "INSERT INTO chat_conversations (customer_id, conversation_id, collecting_kind, draft, action_kind, action_id,"
        " action_payload_hash, action_status, revision) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1)"
        " ON CONFLICT (customer_id, conversation_id) DO UPDATE SET collecting_kind = EXCLUDED.collecting_kind,"
        " draft = EXCLUDED.draft, action_kind = EXCLUDED.action_kind, action_id = EXCLUDED.action_id,"
        " action_payload_hash = EXCLUDED.action_payload_hash, action_status = EXCLUDED.action_status,"
        " revision = chat_conversations.revision + 1",
        (customer_id, conversation_id, st.collecting_kind, Jsonb(st.draft) if st.draft is not None else None,
         st.action_kind, st.action_id, st.action_payload_hash, st.action_status))


def _touch(conn, customer_id: str, conversation_id: str) -> None:
    """Advance the revision BEFORE a command may change business state (autocommit: durable even if a later step
    fails), so any interpretation that started earlier becomes stale. Chat state only."""
    conn.execute("UPDATE chat_conversations SET revision = revision + 1 WHERE customer_id = %s AND conversation_id = %s",
                 (customer_id, conversation_id))


def reconcile(conn, customer_id: str, conversation_id: str, st: State,
              lock: bool = False) -> tuple[str, dict | None, State]:
    """Synchronize CHAT state from the AUTHORITATIVE action row (never changes business state). Only a pointer that
    chat believes 'pending' needs it. Returns (outcome, created object or None, current state):
    none | pending | in_flight | completed | cancelled | superseded | expired | missing."""
    if not st.action_id or st.action_status != "pending":
        return "none", None, st
    status = action_status(conn, st.action_kind, st.action_id, customer_id, conversation_id, for_update=lock)
    pointer = {"action_kind": st.action_kind, "action_id": st.action_id, "action_payload_hash": st.action_payload_hash}
    if status == "pending":
        return "pending", None, st
    if status == "confirmed":
        return "in_flight", None, st  # lead handed to n8n: the pointer IS the retry/recovery handle; keep it
    if status == "consumed":
        new = State(**pointer, action_status="completed")
        _save(conn, customer_id, conversation_id, new)
        return "completed", created_object(conn, st.action_kind, st.action_id, customer_id), new
    if status == "cancelled":
        new = State(**pointer, action_status="cancelled")
        _save(conn, customer_id, conversation_id, new)
        return "cancelled", None, new
    if status in ("superseded", "expired"):
        _save(conn, customer_id, conversation_id, State())
        return status, None, State()
    return "missing", None, st  # not this customer's/conversation's action: fail closed, change nothing


def _lock_key(customer_id: str, conversation_id: str) -> int:
    material = json.dumps(["nexo:chat_conversation:v1", customer_id, conversation_id], separators=(",", ":"))
    return int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:8], "big", signed=True)


@contextmanager
def _conversation(settings, customer_id: str, conversation_id: str):
    """A write-capable connection, held under the conversation's advisory lock for the whole command turn."""
    with connect(settings, autocommit=True) as conn:
        key = _lock_key(customer_id, conversation_id)
        conn.execute("SELECT pg_advisory_lock(%s)", (key,))
        try:
            yield conn
        finally:
            try:
                conn.execute("SELECT pg_advisory_unlock(%s)", (key,))
            except psycopg.Error:
                pass  # the lock dies with the session anyway


def _pending_ids(conn, customer_id: str, conversation_id: str, include_confirmed_leads: bool) -> set:
    lead_states = ("pending", "confirmed") if include_confirmed_leads else ("pending",)
    rows = conn.execute(
        "SELECT 'ticket', id FROM pending_ticket_actions WHERE customer_id = %s AND conversation_id = %s AND status = 'pending'"
        " UNION ALL SELECT 'lead', id FROM pending_lead_actions WHERE requested_by_customer_id = %s"
        " AND conversation_id = %s AND status = ANY(%s)",
        (customer_id, conversation_id, customer_id, conversation_id, list(lead_states))).fetchall()
    return {(k, i) for k, i in rows}


# --- propose: collect data, prepare (never create) -------------------------------------------------------
def propose(settings, customer_id: str, conversation_id: str, proposal, message: str,
            basis_revision: int | None = None) -> ChatResult:
    """`basis_revision` = the conversation revision the model interpreted the message against (read before the model
    call, without holding any transaction). The proposal is published only if that revision is still current."""
    if proposal.intent == "request_human":
        return _handoff(settings, customer_id, conversation_id, proposal.handoff_reason or "human_requested", message)
    kind = KIND_OF_INTENT[proposal.intent]
    audit = {"chat_command": "prepare", "action_kind": kind, "basis_revision": basis_revision}
    try:
        with _conversation(settings, customer_id, conversation_id) as conn:
            # AGENT01BF2-01: authoritative check and re-prepare/publication are ONE transaction (no TOCTOU gap).
            with conn.transaction():
                st = load_state(conn, customer_id, conversation_id)
                audit["revision"] = st.revision
                if st.action_id and st.action_status == "pending":
                    # Same lock order as the service prepare path: prepare-group advisory lock BEFORE the row lock.
                    conn.execute("SELECT pg_advisory_xact_lock(%s)",
                                 (_service(st.action_kind).prepare_lock_key(customer_id, conversation_id),))
                # AGENT01BF1-01/BF2-01: re-read AND LOCK the authoritative action row; it stays locked until COMMIT, so no
                # other route can consume/confirm it between this check and the re-prepare below.
                authoritative, obj, st = reconcile(conn, customer_id, conversation_id, st, lock=True)
                audit["authoritative"] = authoritative
                if authoritative not in ("none", "pending"):
                    audit["outcome"] = f"stale_proposal:{authoritative}"
                    return _stale_proposal(proposal.intent, authoritative, obj, st, audit)
                if basis_revision is not None and st.revision != basis_revision:
                    audit["outcome"] = "stale_basis"
                    return ChatResult(proposal.intent, "conversation_changed",
                                      "La conversación ha cambiado mientras procesaba tu mensaje (por ejemplo, se confirmó, "
                                      "canceló o actualizó una acción). No he aplicado este mensaje. Revisa el estado actual y "
                                      "repítelo si hace falta.", next_step=pending_reminder(st), audit=audit)
                if st.action_status == "pending" and st.action_kind != kind:
                    audit["outcome"] = "blocked_other_pending"
                    other = "un ticket" if st.action_kind == "ticket" else "una solicitud comercial"
                    return ChatResult(proposal.intent, "action_blocked",
                                      f"Tienes {other} preparado pendiente de confirmación. Responde CONFIRMAR para ejecutarlo "
                                      "o CANCELAR para descartarlo antes de iniciar otra acción. No se ha hecho nada más.",
                                      next_step=pending_reminder(st), audit=audit)
                re_prepare = st.action_status == "pending" and st.action_kind == kind
                if re_prepare:
                    base = action_fields(conn, kind, st.action_id, customer_id, conversation_id) or {}
                elif st.collecting_kind == kind:
                    base = dict(st.draft or {})
                else:
                    base = {}
                merged = {**base, **proposal.fields}
                if re_prepare and merged == base:
                    audit["outcome"] = "unchanged_pending"
                    return _awaiting(proposal.intent, kind, merged, None, "Sigue preparada esta acción, sin cambios.", audit,
                                     state_token(st))
                lacking = missing(kind, merged)
                if lacking:
                    _save(conn, customer_id, conversation_id, State(collecting_kind=kind, draft=merged))
                    audit.update(outcome="collecting", missing=lacking)
                    return ChatResult(proposal.intent, "collecting_info", ask_missing(kind, lacking, proposal.rejected_fields),
                                      next_step={"action": proposal.intent, "awaiting": "missing_fields", "missing": lacking,
                                                 "executed": False}, audit=audit)
                try:
                    draft = MODELS[kind](**merged).model_dump()  # full API validation of the complete draft
                except ValidationError:
                    _save(conn, customer_id, conversation_id, State(collecting_kind=kind, draft={}))
                    audit["outcome"] = "invalid_draft"
                    return ChatResult(proposal.intent, "collecting_info", ask_missing(kind, list(FIELDS[kind])), audit=audit)
                service = ticket_actions if kind == "ticket" else leads
                prepared = service.prepare(conn, customer_id, draft, conversation_id)  # supersedes this conversation's pending one
                action_id = UUID(prepared["pending_action_id"])
                _save(conn, customer_id, conversation_id, State(action_kind=kind, action_id=action_id,
                      action_payload_hash=prepared["payload_hash"], action_status="pending"))
                audit.update(outcome="re_prepared" if re_prepare else "prepared", action_fp=fingerprint(action_id))
                shown = {f: prepared["summary"][f] for f in FIELDS[kind]}
                lead_in = "He actualizado los datos. " if re_prepare else ""
                return _awaiting(proposal.intent, kind, shown, prepared["expires_at"], lead_in, audit,
                                 confirmation_token(action_id, prepared["payload_hash"]))
    except psycopg.Error as exc:
        audit.update(outcome="error", error=type(exc).__name__)
        return ChatResult(proposal.intent, "error", "No he podido preparar la acción por un problema técnico. No se ha "
                          "creado nada; inténtalo de nuevo.", 503, "database_unavailable", audit=audit)


def _stale_proposal(intent: str, authoritative: str, obj: dict | None, st: State, audit: dict) -> ChatResult:
    """The action moved out of 'pending' while the model was interpreting: reject the proposal, never replace it."""
    if authoritative == "completed":
        what = (f"el ticket {obj['reference']} (id {obj['id']})" if obj and obj["kind"] == "ticket"
                else f"la solicitud comercial (id {obj['id']})" if obj else "la acción")
        return ChatResult(intent, "already_completed", f"Mientras procesaba tu mensaje, la acción ya se completó ({what}). "
                          "No he aplicado tu cambio ni he preparado otra acción; si necesitas algo más, pídelo de nuevo.",
                          result=obj, audit=audit)
    if authoritative == "in_flight":
        return ChatResult(intent, "action_in_progress", "La solicitud comercial ya se envió a registrar y su resultado está "
                          "pendiente; no la sustituyo ni preparo otra. Responde CONFIRMAR para conocer el resultado.",
                          next_step={"action": INTENT_OF_KIND[st.action_kind], "awaiting": "CONFIRMAR", "executed": False,
                                     "confirmation_token": state_token(st)}, audit=audit)
    return ChatResult(intent, "conversation_changed", "La conversación ha cambiado mientras procesaba tu mensaje (la acción "
                      "ya no está pendiente). No he aplicado este mensaje; revisa el estado y repítelo si hace falta.",
                      audit=audit)


def _render(kind: str, values: dict) -> str:
    if kind == "ticket":
        lines = [f"• Contacto: {values['contact_name']}", f"• Asunto: {values['subject']}",
                 f"• Prioridad: {PRIORITY_ES.get(values['priority'], values['priority'])}",
                 f"• Descripción: {values['description']}"]
        head = "Voy a crear este ticket:"
        tail = (" Al ser una incidencia crítica, además se escalará a una persona: quedará pendiente de atención, "
                "sin plazo de respuesta garantizado." if values["priority"] == "critical" else "")
    else:
        lines = [f"• Empresa: {values['company_name']}", f"• Contacto: {values['contact_name']}",
                 f"• Correo: {values['contact_email']}", f"• Necesidad: {values['need']}"]
        head = "Voy a registrar esta solicitud comercial (no incluye precios, descuentos, contratos ni fechas):"
        tail = ""
    return head + "\n" + "\n".join(lines) + "\n" + (tail.strip() + "\n" if tail else "")


def _awaiting(intent, kind, values, expires_at, prefix, audit, token, status="awaiting_confirmation") -> ChatResult:
    """The summary shown for approval and the token that names exactly this version (the client echoes it)."""
    return ChatResult(intent, status, prefix + _render(kind, values) + CONFIRM_HINT,
                      pending_action={"kind": kind, "summary": values, "expires_at": expires_at, "confirmation_token": token},
                      next_step={"action": INTENT_OF_KIND[kind], "awaiting": "CONFIRMAR", "executed": False,
                                 "confirmation_token": token}, audit=audit)


# --- confirm: the deterministic gate ---------------------------------------------------------------------
MSG_NOTHING_TO_CONFIRM = "No hay ninguna acción preparada pendiente de confirmar en esta conversación. No se ha hecho nada."
MSG_REVIEW = ("Los datos preparados han cambiado desde el resumen que estás confirmando, o no indicas qué resumen apruebas, "
              "así que no he ejecutado nada. Revisa el resumen actual y, si es correcto, responde CONFIRMAR.\n")
MSG_INVALID = {"ticket": "La propuesta de ticket ya no es válida (caducó, se sustituyó o se canceló). No se ha creado ningún "
                         "ticket; si quieres, vuelve a pedirlo.",
               "lead": "La solicitud comercial ya no es válida (caducó, se sustituyó o se canceló). No se ha registrado "
                       "nada; si quieres, vuelve a pedirla."}


def confirm(settings, customer_id: str, conversation_id: str, request_id: str,
            presented_token: str | None = None) -> ChatResult:
    """Execute ONLY the version named by `presented_token` (the summary the client showed and the user approved)."""
    audit = {"chat_command": "confirm", "token_presented": presented_token is not None}
    try:
        # Admission snapshot (audit only, NEVER used to decide what to execute).
        with connect(settings) as rconn:
            rconn.read_only = True
            audit["admitted_revision"] = load_state(rconn, customer_id, conversation_id).revision
        with _conversation(settings, customer_id, conversation_id) as conn:
            st = load_state(conn, customer_id, conversation_id)  # authoritative: re-read UNDER the conversation lock
            audit["revision"] = st.revision
            if st.action_status not in ("pending", "completed"):
                audit["outcome"] = "nothing_pending"
                text = MSG_NOTHING_TO_CONFIRM
                if st.collecting_kind:
                    text += " " + ask_missing(st.collecting_kind, missing(st.collecting_kind, st.draft or {}))
                return ChatResult("confirmation", "nothing_pending", text, audit=audit)
            current = state_token(st)
            if presented_token != current:
                # AGENT01B-01: never switch to another (e.g. newer, re-prepared) version; fail closed and ask for review.
                audit.update(outcome="stale_confirmation" if presented_token else "token_missing",
                             action_kind=st.action_kind, action_fp=fingerprint(st.action_id))
                values = (action_fields(conn, st.action_kind, st.action_id, customer_id, conversation_id)
                          if st.action_status == "pending" else None)
                if values is not None:
                    return _awaiting("confirmation", st.action_kind, values, None, MSG_REVIEW, audit, current,
                                     status="confirmation_review_required")
                return ChatResult("confirmation", "nothing_pending", MSG_NOTHING_TO_CONFIRM, audit=audit)
            if action_status(conn, st.action_kind, st.action_id, customer_id, conversation_id) is None:
                _clear(conn, customer_id, conversation_id)  # pointer not owned by this customer+conversation: fail closed
                audit["outcome"] = "pointer_not_in_conversation"
                return ChatResult("confirmation", "confirmation_invalid", MSG_INVALID[st.action_kind], audit=audit)
            key = confirmation_key(conversation_id, st.action_id)
            audit.update(action_kind=st.action_kind, action_fp=fingerprint(st.action_id),
                         idempotency_key_fp=leads.key_fingerprint(key))
            _touch(conn, customer_id, conversation_id)  # before the service: any earlier interpretation is now stale
            if st.action_status == "pending":
                others = _pending_ids(conn, customer_id, conversation_id, True) - {(st.action_kind, st.action_id)}
                if others:
                    audit["outcome"] = "ambiguous_pending"
                    return ChatResult("confirmation", "action_ambiguous",
                                      "Hay más de una acción pendiente en esta conversación y no voy a adivinar cuál "
                                      "ejecutar. No se ha hecho nada. Responde CANCELAR y vuelve a pedir lo que necesites.",
                                      audit=audit)
            if st.action_kind == "ticket":
                outcome = ticket_actions.confirm(conn, customer_id, st.action_id, st.action_payload_hash, key)
                return _ticket_result(conn, customer_id, conversation_id, st, outcome, audit)
            outcome = leads.confirm_via_workflow(settings, customer_id, st.action_id, st.action_payload_hash, key,
                                                 request_id, conversation_id)
            return _lead_result(conn, customer_id, conversation_id, st, outcome, audit)
    except psycopg.Error as exc:
        audit.update(outcome="unknown", error=type(exc).__name__)
        return ChatResult("confirmation", "error", "No he podido comprobar si la acción se completó por un problema técnico, "
                          "así que no te digo que se haya creado. Vuelve a enviar CONFIRMAR para obtener el resultado "
                          "definitivo: no se duplicará.", 503, "action_not_confirmed", audit=audit)


def _clear(conn, customer_id, conversation_id) -> None:
    _save(conn, customer_id, conversation_id, State())


def _ticket_result(conn, customer_id, conversation_id, st: State, outcome, audit) -> ChatResult:
    body = outcome.body
    audit["service_outcome"] = outcome.audit.get("confirmation_result")
    if outcome.status == 201 or (body.get("code") == "confirmation_already_used" and body.get("ticket_id")):
        ticket_id = UUID(body.get("id") or body["ticket_id"])
        row = conn.execute("SELECT reference, status, priority, subject FROM tickets WHERE id = %s AND customer_id = %s",
                           (ticket_id, customer_id)).fetchone()
        reference, status, priority, subject = row
        _save(conn, customer_id, conversation_id, State(action_kind="ticket", action_id=st.action_id,
              action_payload_hash=st.action_payload_hash, action_status="completed"))
        replay = outcome.idempotency_outcome != "created"
        audit.update(outcome="replayed" if replay else "created", ticket_id=str(ticket_id), ticket_reference=reference,
                     idempotency=outcome.idempotency_outcome or "already_used")
        text = (f"{'Este ticket ya estaba creado' if replay else 'He creado el ticket'}: {reference} (id {ticket_id}), "
                f"prioridad {PRIORITY_ES.get(priority, priority)}, estado «{STATUS_ES.get(status, status)}».")
        result = {"kind": "ticket", "id": str(ticket_id), "reference": reference, "status": status, "priority": priority,
                  "idempotency": outcome.idempotency_outcome or "already_used", "handoff": None}
        if priority == "critical":
            # Support policy: critical incidents are escalated to a human (existing APP-03A service, idempotent per ticket).
            summary = f"Incidencia crítica registrada como ticket {reference} ({ticket_id}). Asunto: {subject}"[:2000]
            handoff = handoffs.create(conn, customer_id, conversation_id, "critical_incident", summary,
                                      f"chat-ticket-handoff:{ticket_id}")
            audit.update(handoff_id=handoff.handoff_id, handoff_idempotency=handoff.idempotency_outcome)
            result["handoff"] = {"id": handoff.handoff_id, "reason": "critical_incident", "status": "pending"}
            text += f" Al ser una incidencia crítica la he escalado a una persona (escalado {handoff.handoff_id}). " + HANDOFF_PENDING_ES
        return ChatResult("confirmation", "ticket_created", text, result=result, audit=audit)
    _clear(conn, customer_id, conversation_id)
    audit["outcome"] = body.get("code") or f"http_{outcome.status}"
    return ChatResult("confirmation", "confirmation_invalid", MSG_INVALID["ticket"], audit=audit)


def _lead_result(conn, customer_id, conversation_id, st: State, outcome, audit) -> ChatResult:
    body = outcome.body
    audit["service_outcome"] = outcome.audit.get("confirmation_result")
    if outcome.status == 201:
        _save(conn, customer_id, conversation_id, State(action_kind="lead", action_id=st.action_id,
              action_payload_hash=st.action_payload_hash, action_status="completed"))
        replay = outcome.idempotency_outcome != "created"
        audit.update(outcome="replayed" if replay else "created", lead_id=body["id"],
                     workflow_execution_id=body.get("workflow_execution_id"), idempotency=outcome.idempotency_outcome)
        text = (f"{'Esta solicitud ya estaba registrada' if replay else 'He registrado tu solicitud comercial'} "
                f"(id {body['id']}). " + LEAD_STATUS_ES)
        return ChatResult("confirmation", "lead_created", text, result={
            "kind": "lead", "id": body["id"], "workflow_execution_id": body.get("workflow_execution_id"),
            "status_message": body.get("status_message"), "idempotency": outcome.idempotency_outcome}, audit=audit)
    code = body.get("code")
    audit["outcome"] = code or f"http_{outcome.status}"
    if code == "confirmation_already_used" and body.get("lead_id"):
        _save(conn, customer_id, conversation_id, State(action_kind="lead", action_id=st.action_id,
              action_payload_hash=st.action_payload_hash, action_status="completed"))
        return ChatResult("confirmation", "lead_created", f"Esta solicitud ya estaba registrada (id {body['lead_id']}). "
                          + LEAD_STATUS_ES, result={"kind": "lead", "id": body["lead_id"], "idempotency": "already_used"},
                          audit=audit)
    if code == "lead_not_confirmed":
        return ChatResult("confirmation", "error", "No he podido confirmar que la solicitud se haya registrado (la "
                          "automatización no está disponible), así que no te digo que se haya creado. Vuelve a enviar "
                          "CONFIRMAR más tarde para obtener el resultado definitivo: no se duplicará.", 503, code, audit=audit)
    if code in ("workflow_rejected", "workflow_inconsistent"):
        return ChatResult("confirmation", "error", "La automatización no ha registrado la solicitud: no se ha creado "
                          "nada. Si quieres, pide hablar con una persona.", 502, code, audit=audit)
    if code == "confirmation_in_progress":
        return ChatResult("confirmation", "error", "Esta solicitud ya se está procesando por otra vía; no la ejecuto de "
                          "nuevo. No te confirmo que se haya creado.", 409, code, audit=audit)
    _clear(conn, customer_id, conversation_id)
    return ChatResult("confirmation", "confirmation_invalid", MSG_INVALID["lead"], audit=audit)


# --- cancel --------------------------------------------------------------------------------------------
def _service(kind: str):
    return ticket_actions if kind == "ticket" else leads


def cancel(settings, customer_id: str, conversation_id: str) -> ChatResult:
    """AGENT01B-02: the answer comes from the AUTHORITATIVE action state after the owner-scoped cancel attempt.
    Success only if this very call moved the action pending -> cancelled; never from the cached conversation state."""
    audit = {"chat_command": "cancel"}
    try:
        with _conversation(settings, customer_id, conversation_id) as conn:
            st = load_state(conn, customer_id, conversation_id)
            pointer = (st.action_kind, st.action_id) if st.action_id and st.action_status in ("pending", "completed") else None
            audit["action_fp"] = fingerprint(st.action_id) if st.action_id else None
            # AGENT01BF1-02 / BF2-02: 1) prove pointer membership (customer AND conversation AND action) BEFORE ANY cancel
            # mutation of any action; an invalid pointer fails closed with ZERO cancel-service calls.
            if pointer and action_status(conn, pointer[0], pointer[1], customer_id, conversation_id) is None:
                _clear(conn, customer_id, conversation_id)  # chat state only; no business action touched
                audit.update(outcome="pointer_not_in_conversation", other_actions_cancelled=0)
                return ChatResult("cancellation", "not_pending", "No encuentro la acción de esta conversación; no he "
                                  "cancelado ni ejecutado nada.", audit=audit)
            # 2) advance the revision BEFORE the first business mutation.
            _touch(conn, customer_id, conversation_id)
            # 3) only now: the conversation's other pending actions, then the pointed one.
            others = 0
            for kind, action_id in sorted(_pending_ids(conn, customer_id, conversation_id, False) - {pointer}, key=str):
                others += _service(kind).cancel(conn, customer_id, action_id)
            audit["other_actions_cancelled"] = others
            if pointer:
                kind, action_id = pointer
                if st.action_status == "pending" and _service(kind).cancel(conn, customer_id, action_id):
                    _save(conn, customer_id, conversation_id, State(action_kind=kind, action_id=action_id,
                          action_payload_hash=st.action_payload_hash, action_status="cancelled"))
                    audit["outcome"] = "cancelled"
                    return ChatResult("cancellation", "cancelled", "He cancelado la acción pendiente: con ella no se ha "
                                      "creado ningún ticket ni solicitud.", audit=audit)
                status = action_status(conn, kind, action_id, customer_id, conversation_id)
                audit["action_status"] = status
                if status == "consumed":
                    obj = created_object(conn, kind, action_id, customer_id)
                    _save(conn, customer_id, conversation_id, State(action_kind=kind, action_id=action_id,
                          action_payload_hash=st.action_payload_hash, action_status="completed"))
                    audit.update(outcome="already_completed", created_id=(obj or {}).get("id"))
                    what = (f"el ticket {obj['reference']} (id {obj['id']})" if kind == "ticket" and obj
                            else f"la solicitud comercial (id {obj['id']})" if obj else "el registro")
                    return ChatResult("cancellation", "already_completed", f"La acción ya se había completado ({what}) y "
                                      "no puede cancelarse. No he borrado ni modificado nada.", result=obj, audit=audit)
                if status == "confirmed":
                    audit["outcome"] = "in_flight"
                    return ChatResult("cancellation", "cannot_cancel", "La solicitud comercial ya se envió a registrar y no "
                                      "puedo cancelarla desde el chat. Responde CONFIRMAR para conocer el resultado.", audit=audit)
                _clear(conn, customer_id, conversation_id)
                audit["outcome"] = f"not_pending:{status}"
                if status in ("superseded", "expired", "cancelled"):
                    return ChatResult("cancellation", "not_pending", "La acción ya no estaba pendiente (sustituida, caducada "
                                      "o ya cancelada), así que no había nada que cancelar; con ella no se ha creado nada.",
                                      audit=audit)
                return ChatResult("cancellation", "not_pending", "No encuentro la acción de esta conversación; no he "
                                  "cancelado ni ejecutado nada.", audit=audit)
            if st.collecting_kind:
                _save(conn, customer_id, conversation_id, State())
                audit["outcome"] = "draft_discarded"
                return ChatResult("cancellation", "cancelled", "He descartado los datos que estaba recogiendo; todavía no se "
                                  "había preparado nada.", audit=audit)
            if others:
                audit["outcome"] = "cancelled_unpointed"
                return ChatResult("cancellation", "cancelled", f"He cancelado {others} acción(es) pendiente(s) de esta "
                                  "conversación; con ellas no se ha creado nada.", audit=audit)
            audit["outcome"] = "nothing_to_cancel"
            return ChatResult("cancellation", "nothing_pending", "No hay ninguna acción pendiente que cancelar.", audit=audit)
    except psycopg.Error as exc:
        audit.update(outcome="error", error=type(exc).__name__)
        return ChatResult("cancellation", "error", "No he podido cancelar por un problema técnico; vuelve a enviar CANCELAR.",
                          503, "database_unavailable", audit=audit)


# --- handoff (no confirmation required by the assessment) --------------------------------------------------
def _handoff(settings, customer_id: str, conversation_id: str, reason: str, message: str) -> ChatResult:
    """Reason from a closed enum; summary built by the backend from the customer's own words (never model text);
    identity and conversation from the request. Idempotent per conversation + reason."""
    audit = {"chat_command": "handoff", "handoff_reason": reason}
    summary = f"Escalado desde el chat ({REASON_ES[reason]}). Mensaje del cliente: «{message.strip()[:1500]}»"
    try:
        with _conversation(settings, customer_id, conversation_id) as conn:
            outcome = handoffs.create(conn, customer_id, conversation_id, reason, summary,
                                      f"chat-handoff:{conversation_id}:{reason}")
    except psycopg.Error as exc:
        audit.update(outcome="error", error=type(exc).__name__)
        return ChatResult("request_human", "error", "No he podido confirmar el registro del escalado por un problema "
                          "técnico; vuelve a pedirlo: no se duplicará.", 503, "database_unavailable", audit=audit)
    audit.update(handoff_id=outcome.handoff_id, idempotency=outcome.idempotency_outcome)
    result = {"kind": "handoff", "id": outcome.handoff_id, "reason": reason, "status": "pending",
              "idempotency": outcome.idempotency_outcome}
    if outcome.status == 201:
        audit["outcome"] = "created" if outcome.idempotency_outcome == "created" else "replayed"
        return ChatResult("request_human", "handoff_created",
                          f"He pasado tu consulta a una persona (escalado {outcome.handoff_id}). " + HANDOFF_PENDING_ES,
                          result=result, audit=audit)
    audit["outcome"] = "already_pending"
    return ChatResult("request_human", "handoff_already_pending",
                      f"Ya hay una solicitud de atención humana registrada en esta conversación (escalado "
                      f"{outcome.handoff_id}). " + HANDOFF_PENDING_ES, result=result, audit=audit)
