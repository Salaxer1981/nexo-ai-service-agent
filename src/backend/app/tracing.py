"""Request traceability: request_id / conversation_id and one structured audit line per request.

Logged fields are observable facts only (request, action, result, error class, timing).
Headers, tokens, passwords, request bodies and model reasoning are never logged.
"""
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import Request

audit_logger = logging.getLogger("nexo.audit")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def safe_id(value: str | None) -> str | None:
    """Accept a client-supplied correlation ID only if it is short and harmless."""
    return value if value and _SAFE_ID.fullmatch(value) else None


async def trace_requests(request: Request, call_next):
    start = time.perf_counter()
    request_id = safe_id(request.headers.get("x-request-id")) or str(uuid.uuid4())
    raw_conversation = request.headers.get("x-conversation-id")
    # APP03A-01: "absent" and "supplied but invalid" are different states. conversation_id stays None
    # for both (an invalid value is never echoed into logs), so record whether the header was present.
    request.state.conversation_header_supplied = raw_conversation is not None
    conversation_id = safe_id(raw_conversation.strip()) if raw_conversation is not None else None
    request.state.request_id = request_id
    request.state.conversation_id = conversation_id
    request.state.audit = {}

    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        request.state.audit.setdefault("error", type(exc).__name__)
        raise
    finally:
        route = request.scope.get("route")
        event = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "request_id": request_id,
            "conversation_id": conversation_id,
            "method": request.method,
            "route": getattr(route, "path", request.url.path),
            "status": status_code,
            "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            **request.state.audit,
        }
        audit_logger.info(json.dumps(event, default=str))
