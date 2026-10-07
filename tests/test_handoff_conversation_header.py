"""APP03A-01: a supplied-but-invalid X-Conversation-ID must be rejected, not treated as absent."""
import json
import logging
import uuid

import pytest

from conftest import bearer

BODY_CONV = "conv-header-check"


def _body():
    return {"conversation_id": BODY_CONV, "reason": "human_requested", "summary": "Synthetic: header rule check."}


def _post(client, token, headers=None, key=None):
    h = {**bearer(token), "Idempotency-Key": key or f"hc-{uuid.uuid4()}", **(headers or {})}
    return client.post("/handoffs", json=_body(), headers=h)


def _count(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        return conn.execute("SELECT count(*) FROM handoffs").fetchone()[0]


# Cases 1 and 2 (+ normalization of a valid value)
@pytest.mark.parametrize("headers", [
    {},                                              # 1. header absent
    {"X-Conversation-ID": BODY_CONV},                # 2. valid and equal
    {"X-Conversation-ID": f"  {BODY_CONV}  "},       # valid after normalization (outer whitespace)
], ids=["absent", "valid-equal", "valid-equal-padded"])
def test_absent_or_matching_header_is_accepted(api, pg_server, app_db, headers):
    client, tokens = api
    before = _count(pg_server, app_db)
    r = _post(client, tokens["CUSTOMER_A"], headers)
    assert r.status_code == 201 and r.json()["conversation_id"] == BODY_CONV
    assert r.json()["customer_id"] == "CUSTOMER_A"
    assert _count(pg_server, app_db) == before + 1


# Cases 3-6, plus other malformed values
@pytest.mark.parametrize("value,expected_detail", [
    ("conv-different", "must match"),        # 3. valid but different
    ("", "is invalid"),                      # 4. empty
    ("   ", "is invalid"),                   # 5. whitespace only
    ("bad value", "is invalid"),             # 6. malformed (inner space)
    ("bad/value", "is invalid"),
    ("x" * 65, "is invalid"),
], ids=["different", "empty", "whitespace", "inner-space", "slash", "too-long"])
def test_mismatched_or_invalid_header_is_rejected_and_persists_nothing(api, pg_server, app_db, caplog,
                                                                       value, expected_detail):
    client, tokens = api
    before = _count(pg_server, app_db)
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        r = _post(client, tokens["CUSTOMER_A"], {"X-Conversation-ID": value, "X-Request-ID": "req-hc-1"})
    assert r.status_code == 400 and expected_detail in r.json()["detail"]
    assert _count(pg_server, app_db) == before
    # Traceability: request id still returned and audited, with a rejection outcome and no handoff id.
    assert r.headers["X-Request-ID"] == "req-hc-1"
    event = [json.loads(rec.getMessage()) for rec in caplog.records if rec.name == "nexo.audit"][-1]
    assert event["request_id"] == "req-hc-1" and event["action"] == "handoff_create"
    assert event["result"] == "rejected" and event["status"] == 400
    assert event["error"] in ("InvalidConversationHeader", "ConversationMismatch")
    assert "handoff_id" not in event and "idempotency" not in event
    if expected_detail == "is invalid" and value.strip():
        assert value not in caplog.text  # the raw invalid header is not echoed into logs


def test_invalid_header_rejected_before_idempotency_key_is_consumed(api, pg_server, app_db):
    """A rejected request must not 'use up' its Idempotency-Key: the corrected retry creates the handoff."""
    client, tokens = api
    key = f"hc-{uuid.uuid4()}"
    before = _count(pg_server, app_db)
    assert _post(client, tokens["CUSTOMER_A"], {"X-Conversation-ID": "bad value"}, key).status_code == 400
    ok = _post(client, tokens["CUSTOMER_A"], {"X-Conversation-ID": BODY_CONV}, key)
    assert ok.status_code == 201 and ok.headers["Idempotency-Outcome"] == "created"
    replay = _post(client, tokens["CUSTOMER_A"], {}, key)
    assert replay.status_code == 201 and replay.headers["Idempotency-Outcome"] == "replay"
    assert replay.json()["id"] == ok.json()["id"]
    assert _count(pg_server, app_db) == before + 1


def test_unauthenticated_request_with_invalid_header_is_still_401(api, pg_server, app_db):
    client, _ = api
    before = _count(pg_server, app_db)
    r = client.post("/handoffs", json=_body(), headers={"X-Conversation-ID": "bad value", "Idempotency-Key": "k-1"})
    assert r.status_code == 401
    assert _count(pg_server, app_db) == before


def test_ownership_unchanged_with_valid_header(api):
    client, tokens = api
    r = _post(client, tokens["CUSTOMER_B"], {"X-Conversation-ID": BODY_CONV, "X-Customer-Id": "CUSTOMER_A"})
    assert r.status_code == 201 and r.json()["customer_id"] == "CUSTOMER_B"
