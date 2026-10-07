import hashlib
import logging
import re
from contextlib import asynccontextmanager
from typing import Literal
from uuid import UUID, uuid4

import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app import agent, chat_actions, handoffs, leads, llm, rag, ticket_actions, tickets
from app.auth import AuthenticatedCustomer, require_customer
from app.service_auth import ServicePrincipal, require_service
from app.config import load_settings
from app.schemas import LeadDraft, TicketDraft
from app.db import connect
from app.migrate import latest_version
from app.tracing import trace_requests

logging.basicConfig(level=logging.INFO, format="%(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail fast at startup if configuration is missing, instead of at first request.
    app.state.settings = load_settings()
    # Real OpenRouter embeddings when configured; None => RAG answers 503 (never a silent fake).
    app.state.embedding_provider = rag.provider_from_settings(app.state.settings)
    # Agent chat model (same OpenRouter key). None => /chat answers 503 (never a silent fake).
    app.state.chat_client = llm.chat_client_from_settings(app.state.settings)
    yield


app = FastAPI(title="Nexo AI Service Agent", version="0.3.0", lifespan=lifespan)

IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
UNAVAILABLE = "Service temporarily unavailable"


class HandoffRequest(BaseModel):
    """Escalation data only. No customer_id: the owner always comes from authentication."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    reason: Literal["critical_incident", "human_requested", "unsafe_to_resolve"]
    summary: str = Field(min_length=1, max_length=2000)


class LeadConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pending_action_id: UUID
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class InternalLeadWrite(BaseModel):
    """What the n8n workflow sends to the private lead-write endpoint."""
    model_config = ConfigDict(extra="forbid")
    pending_action_id: UUID
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lead: LeadDraft
    workflow_execution_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,64}$")


def _reject_invalid_conversation_header(request: Request) -> JSONResponse | None:
    """APP03A-01 rule: a supplied but invalid X-Conversation-ID is rejected, not treated as absent."""
    if request.state.conversation_header_supplied and request.state.conversation_id is None:
        request.state.audit.update(result="rejected", error="InvalidConversationHeader")
        return JSONResponse(status_code=400, content={
            "detail": "X-Conversation-ID header is invalid (1-64 chars: A-Z a-z 0-9 . _ -)"})
    return None


class RagSearch(BaseModel):
    """Diagnostic retrieval request. The corpus is shared: no customer field can scope or alter it."""
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=3, ge=1, le=5)


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    message: str = Field(min_length=1, max_length=1000)
    # Same rule as the X-Conversation-ID header (tracing.safe_id); identity is NEVER taken from the body.
    conversation_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")
    # AGENT-01BF1: with CONFIRMAR, the client echoes the confirmation_token of the summary it showed the user, so only
    # that exact prepared version can execute. Ignored for every other message.
    confirmation_token: str | None = Field(default=None, pattern=r"^[0-9a-f]{16}$")


class TicketConfirmation(BaseModel):
    """Confirms one prepared action by echoing the fingerprint of the exact data shown."""
    model_config = ConfigDict(extra="forbid")
    pending_action_id: UUID
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
app.middleware("http")(trace_requests)


@app.get("/health")
def health() -> dict:
    """Liveness: the process is up and configuration loaded. Does not touch the database."""
    return {"status": "ok"}


@app.get("/health/ready")
def ready(request: Request):
    """Readiness: PostgreSQL is reachable and the schema is at the version this code expects."""
    request.state.audit["action"] = "health.ready"
    expected = latest_version()
    try:
        with connect(request.app.state.settings) as conn:
            current = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    except psycopg.Error as exc:
        request.state.audit.update(result="not_ready", error=type(exc).__name__)
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "unavailable"})
    if current != expected:
        request.state.audit.update(result="not_ready", error="SchemaOutdated")
        return JSONResponse(status_code=503, content={"status": "not_ready", "database": "schema_outdated"})
    request.state.audit["result"] = "ready"
    return {"status": "ready", "database": "ok", "schema_version": current}


@app.get("/me")
def me(request: Request, customer: AuthenticatedCustomer = Depends(require_customer)) -> dict:
    """The identity the backend resolved from the credential, and nothing else."""
    request.state.audit.update(action="identity.read", result="allowed")
    return {"customer_id": customer.customer_id, "display_name": customer.display_name}


@app.post("/tickets/prepare", status_code=201)
def prepare_ticket(
    draft: TicketDraft, request: Request, customer: AuthenticatedCustomer = Depends(require_customer)
) -> dict:
    """Store the exact ticket data awaiting confirmation. Creates NO ticket."""
    request.state.audit["action"] = "ticket_prepare"
    try:
        with connect(request.app.state.settings, autocommit=True) as conn:
            prepared = ticket_actions.prepare(
                conn, customer.customer_id, draft.model_dump(), request.state.conversation_id
            )
    except psycopg.Error as exc:
        request.state.audit.update(result="error", error=type(exc).__name__)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    request.state.audit.update(pending_action_id=prepared["pending_action_id"], result="prepared")
    return prepared


@app.post("/tickets/confirm")
def confirm_ticket(
    confirmation: TicketConfirmation,
    request: Request,
    customer: AuthenticatedCustomer = Depends(require_customer),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create the ticket from a prepared action, exactly once per action and per Idempotency-Key."""
    audit = request.state.audit
    audit.update(action="ticket_confirm", pending_action_id=str(confirmation.pending_action_id))
    if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        audit.update(result="rejected", confirmation_result="missing_idempotency_key")
        return JSONResponse(status_code=400, content={
            "detail": "A valid Idempotency-Key header is required (1-128 chars: A-Z a-z 0-9 . _ : -)"})
    try:
        with connect(request.app.state.settings, autocommit=True) as conn:
            outcome = ticket_actions.confirm(
                conn, customer.customer_id, confirmation.pending_action_id,
                confirmation.payload_hash, idempotency_key,
            )
    except psycopg.Error as exc:
        # Never claim success. The transaction either rolled back or its outcome is unknown;
        # a retry with the same key returns the committed result if there is one.
        audit.update(result="error", error=type(exc).__name__)
        return JSONResponse(status_code=503, content={
            "detail": f"{UNAVAILABLE}. The ticket creation could not be confirmed; "
                      "retry with the same Idempotency-Key to get the definitive result."})

    audit.update(outcome.audit, idempotency=outcome.idempotency_outcome,
                 result="success" if outcome.status in (200, 201) else "rejected")
    headers = {"Idempotency-Outcome": outcome.idempotency_outcome} if outcome.idempotency_outcome else None
    return JSONResponse(status_code=outcome.status, content=outcome.body, headers=headers)


@app.post("/handoffs")
def create_handoff(
    handoff: HandoffRequest,
    request: Request,
    customer: AuthenticatedCustomer = Depends(require_customer),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Persist a human handoff as 'pending' (never claims a person is attending). Idempotent per key."""
    audit = request.state.audit
    audit.update(action="handoff_create", reason=handoff.reason)
    header_conversation = request.state.conversation_id
    if request.state.conversation_header_supplied and header_conversation is None:
        # Supplied but empty/whitespace/invalid: reject instead of treating it as absent (APP03A-01).
        audit.update(result="rejected", error="InvalidConversationHeader")
        return JSONResponse(status_code=400, content={
            "detail": "X-Conversation-ID header is invalid (1-64 chars: A-Z a-z 0-9 . _ -)"})
    if header_conversation is not None and header_conversation != handoff.conversation_id:
        audit.update(result="rejected", error="ConversationMismatch")
        return JSONResponse(status_code=400, content={
            "detail": "X-Conversation-ID header and body conversation_id must match"})
    if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        audit.update(result="rejected", error="MissingIdempotencyKey")
        return JSONResponse(status_code=400, content={
            "detail": "A valid Idempotency-Key header is required (1-128 chars: A-Z a-z 0-9 . _ : -)"})
    try:
        with connect(request.app.state.settings, autocommit=True) as conn:
            outcome = handoffs.create(conn, customer.customer_id, handoff.conversation_id,
                                      handoff.reason, handoff.summary, idempotency_key)
    except psycopg.Error as exc:
        audit.update(result="error", error=type(exc).__name__)
        return JSONResponse(status_code=503, content={
            "detail": f"{UNAVAILABLE}. The handoff could not be confirmed as registered; "
                      "retry with the same Idempotency-Key to get the definitive result."})
    audit.update(handoff_id=outcome.handoff_id, idempotency=outcome.idempotency_outcome,
                 handoff_conversation_id=handoff.conversation_id,
                 result="success" if outcome.status == 201 else "rejected")
    return JSONResponse(status_code=outcome.status, content=outcome.body,
                        headers={"Idempotency-Outcome": outcome.idempotency_outcome})


@app.post("/rag/search")
def rag_search(body: RagSearch, request: Request, customer: AuthenticatedCustomer = Depends(require_customer)):
    """Return ranked, referenced EVIDENCE from the knowledge base, or `evidence: insufficient`.
    Generates no answer. Retrieved text is data, never instructions (REQ-RAG-05)."""
    audit = request.state.audit
    audit.update(action="rag_search", query_length=len(body.query),
                 query_fp=hashlib.sha256(body.query.encode("utf-8")).hexdigest()[:12], top_k=body.top_k)
    if (rejected := _reject_invalid_conversation_header(request)) is not None:
        return rejected
    settings, provider = request.app.state.settings, request.app.state.embedding_provider
    if provider is None:
        audit.update(result="error", error="rag_unavailable")
        return JSONResponse(status_code=503, content={"detail": "Knowledge search is not configured",
                                                      "code": "rag_unavailable"})
    audit["model"] = provider.model
    try:
        with connect(settings) as conn:
            result = rag.search_knowledge(conn, provider, body.query, body.top_k, settings.rag_min_score)
    except rag.RagError as exc:
        audit.update(result="error", error=exc.code)
        return JSONResponse(status_code=503, content={"detail": "Knowledge search is temporarily unavailable",
                                                      "code": exc.code})
    except psycopg.Error as exc:
        audit.update(result="error", error=type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": UNAVAILABLE, "code": "database_unavailable"})
    audit.update(result=result["evidence"], accepted=len(result["matches"]), best_score=result["best_score"],
                 chunk_ids=[m["chunk_id"] for m in result["matches"]],
                 source_ids=sorted({m["source_id"] for m in result["matches"]}))
    return {"query": body.query, **result}


@app.post("/chat")
def chat(body: ChatMessage, request: Request, customer: AuthenticatedCustomer = Depends(require_customer)):
    """One conversational turn (AGENT-01A read paths + AGENT-01B confirmed actions).

    CONFIRMAR / CANCELAR (whole message) go straight to the deterministic COMMAND gate: no model call at all.
    Any other message is interpreted on a READ-ONLY session; read intents are answered there; action intents come
    back as a validated proposal that only the narrow command side (chat_actions) may turn into a prepared action
    or a handoff through the existing services. A ticket or lead is created only by a later CONFIRMAR."""
    audit = request.state.audit
    audit.update(action="chat", message_length=len(body.message),
                 message_fp=hashlib.sha256(body.message.encode("utf-8")).hexdigest()[:12])
    if (rejected := _reject_invalid_conversation_header(request)) is not None:
        return rejected
    header_conv = request.state.conversation_id
    if body.conversation_id and header_conv and body.conversation_id != header_conv:
        audit.update(result="rejected", error="ConversationIdMismatch")
        return JSONResponse(status_code=400, content={"detail": "conversation_id differs from X-Conversation-ID",
                                                      "code": "conversation_id_mismatch"})
    conversation_id = body.conversation_id or header_conv or str(uuid4())
    audit["conversation_id"] = conversation_id
    envelope = {"conversation_id": conversation_id, "request_id": request.state.request_id}

    def failure(code: str, intent: str | None = None):
        audit.update(result="error", error=code)
        return JSONResponse(status_code=503, content={**envelope, "intent": intent, "status": "error", "code": code,
                                                      "answer": None, "sources": []})

    settings = request.app.state.settings

    def command_response(res: chat_actions.ChatResult, model: str | None, extra_audit: dict | None = None):
        audit.update(extra_audit or {})
        audit.update(res.audit, result=res.status)
        if res.code:
            audit["error"] = res.code
        content = {**envelope, "intent": res.intent, "status": res.status, "answer": res.answer, "sources": [],
                   "next_step": res.next_step, "model": model, "result": res.result, "pending_action": res.pending_action}
        if res.code:
            content["code"] = res.code
        return JSONResponse(status_code=res.http_status, content=content)

    gate = chat_actions.gate(body.message)
    if gate is not None:  # deterministic: the model is never consulted for confirmation/cancellation
        audit["gate"] = gate
        res = (chat_actions.confirm(settings, customer.customer_id, conversation_id, request.state.request_id,
                                    body.confirmation_token)
               if gate == "confirm" else chat_actions.cancel(settings, customer.customer_id, conversation_id))
        return command_response(res, None)

    client = request.app.state.chat_client
    if client is None:
        return failure("chat_unavailable")
    try:
        with connect(settings) as conn:
            conn.read_only = True  # READ side: PostgreSQL rejects any write in this transaction
            state = chat_actions.load_state(conn, customer.customer_id, conversation_id)
            context = chat_actions.model_context(conn, state, customer.customer_id, conversation_id)
            conn.commit()  # no transaction stays open during the model call (the session remains READ ONLY)
            reply = agent.handle(body.message, customer.customer_id, client, request.app.state.embedding_provider,
                                 conn, settings.rag_min_score, context)
    except (llm.LLMError, rag.RagError, psycopg.Error) as exc:
        audit.update(getattr(exc, "audit", {}), model=client.model)
        code = "database_unavailable" if isinstance(exc, psycopg.Error) else exc.code
        return failure(code, audit.get("intent"))
    if reply.proposal is not None:  # COMMAND side: prepare (never create) or handoff, via existing services only
        # Published only if the conversation is still at the revision the model interpreted against (AGENT-01BF1).
        res = chat_actions.propose(settings, customer.customer_id, conversation_id, reply.proposal, body.message,
                                   state.revision)
        return command_response(res, client.model, reply.audit)
    answer, next_step = reply.answer, reply.next_step or chat_actions.pending_reminder(state)
    if reply.status == "clarification_needed" and (again := chat_actions.reprompt(state)):
        answer = again
    audit.update(**reply.audit, result=reply.status)
    return {**envelope, "intent": reply.intent, "status": reply.status, "answer": answer,
            "sources": reply.sources, "next_step": next_step, "model": client.model}


@app.post("/leads/prepare", status_code=201)
def prepare_lead(draft: LeadDraft, request: Request, customer: AuthenticatedCustomer = Depends(require_customer)):
    """Store the exact lead data awaiting confirmation. Creates NO lead."""
    request.state.audit["action"] = "lead_prepare"
    if (rejected := _reject_invalid_conversation_header(request)) is not None:
        return rejected
    try:
        with connect(request.app.state.settings, autocommit=True) as conn:
            prepared = leads.prepare(conn, customer.customer_id, draft.model_dump(), request.state.conversation_id)
    except psycopg.Error as exc:
        request.state.audit.update(result="error", error=type(exc).__name__)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    request.state.audit.update(pending_action_id=prepared["pending_action_id"], result="prepared")
    return prepared


@app.post("/leads/confirm")
def confirm_lead(
    confirmation: LeadConfirmation,
    request: Request,
    customer: AuthenticatedCustomer = Depends(require_customer),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Confirm a prepared lead. The lead is created ONLY by the n8n workflow via /internal/leads;
    this endpoint reports success only from the lead row read back from PostgreSQL."""
    audit = request.state.audit
    audit.update(action="lead_confirm", pending_action_id=str(confirmation.pending_action_id))
    if (rejected := _reject_invalid_conversation_header(request)) is not None:
        return rejected
    if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        audit.update(result="rejected", confirmation_result="missing_idempotency_key")
        return JSONResponse(status_code=400, content={
            "detail": "A valid Idempotency-Key header is required (1-128 chars: A-Z a-z 0-9 . _ : -)"})
    audit["idempotency_key_fp"] = leads.key_fingerprint(idempotency_key)
    try:
        outcome = leads.confirm_via_workflow(request.app.state.settings, customer.customer_id,
                                             confirmation.pending_action_id, confirmation.payload_hash,
                                             idempotency_key, request.state.request_id, request.state.conversation_id)
    except psycopg.Error as exc:
        audit.update(result="error", error=type(exc).__name__)
        return JSONResponse(status_code=503, content={
            "detail": f"{UNAVAILABLE}. The lead could not be confirmed as created; "
                      "retry with the same Idempotency-Key to get the definitive result.",
            "code": "lead_not_confirmed"})
    audit.update(outcome.audit, idempotency=outcome.idempotency_outcome,
                 result="success" if outcome.status in (200, 201) else "rejected")
    headers = {"Idempotency-Outcome": outcome.idempotency_outcome} if outcome.idempotency_outcome else None
    return JSONResponse(status_code=outcome.status, content=outcome.body, headers=headers)


@app.post("/internal/leads")
def internal_write_lead(
    write: InternalLeadWrite,
    request: Request,
    service: ServicePrincipal = Depends(require_service("lead_write")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """PRIVATE: the only route that persists a lead. Callable only with the n8n lead-writer service
    credential (scope lead_write), and only for a user-confirmed action with the same key and payload."""
    audit = request.state.audit
    audit.update(action="lead_write", pending_action_id=str(write.pending_action_id),
                 workflow_execution_id=write.workflow_execution_id)
    if not idempotency_key or not IDEMPOTENCY_KEY.fullmatch(idempotency_key):
        audit.update(result="rejected", error="MissingIdempotencyKey")
        return JSONResponse(status_code=400, content={"detail": "A valid Idempotency-Key header is required",
                                                      "code": "missing_idempotency_key"})
    audit["idempotency_key_fp"] = leads.key_fingerprint(idempotency_key)
    try:
        with connect(request.app.state.settings, autocommit=True) as conn:
            outcome = leads.internal_create(conn, write.pending_action_id, write.payload_hash,
                                            write.lead.model_dump(), idempotency_key, write.workflow_execution_id)
    except psycopg.Error as exc:
        audit.update(result="error", error=type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": UNAVAILABLE, "code": "lead_write_unavailable"})
    audit.update(outcome.audit, idempotency=outcome.idempotency_outcome,
                 result="success" if outcome.status == 201 else "rejected")
    headers = {"Idempotency-Outcome": outcome.idempotency_outcome} if outcome.idempotency_outcome else None
    return JSONResponse(status_code=outcome.status, content=outcome.body, headers=headers)


@app.get("/tickets/{ticket_id}")
def get_ticket(
    ticket_id: UUID, request: Request, customer: AuthenticatedCustomer = Depends(require_customer)
) -> dict:
    request.state.audit.update(action="ticket.read", ticket_id=str(ticket_id))
    try:
        with connect(request.app.state.settings) as conn:
            ticket = tickets.get_owned_ticket(conn, ticket_id, customer.customer_id)
            exists_elsewhere = ticket is None and tickets.ticket_exists(conn, ticket_id)
    except psycopg.Error as exc:
        request.state.audit.update(result="error", error=type(exc).__name__)
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from None

    if ticket is None:
        # Other customer's ticket and unknown ticket get the SAME response (INV-03):
        # the client cannot learn that the ticket exists or who owns it.
        request.state.audit["result"] = "denied_not_owner" if exists_elsewhere else "not_found"
        raise HTTPException(status_code=404, detail="Ticket not found")

    request.state.audit["result"] = "allowed"
    return {
        "id": str(ticket.id),
        "customer_id": ticket.customer_id,
        "contact_name": ticket.contact_name,
        "subject": ticket.subject,
        "description": ticket.description,
        "priority": ticket.priority,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }
