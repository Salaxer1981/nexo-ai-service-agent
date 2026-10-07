"""APP-03A: idempotent human handoffs against real PostgreSQL. Numbers = required cases."""
import json
import logging
import re
import threading
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import handoffs
from app.config import load_settings
from app.db import connect
from conftest import _free_port, bearer

# Phrases a pending handoff must never use: they would claim a person is already on it.
FORBIDDEN_CLAIMS = re.compile(
    r"\b(is|are) (now )?(attending|handling|working on|looking into)|\bassigned to\b|\ban? (agent|person|human)"
    r" (is|will) (now )?(handl|attend|contact|call)|\bin progress\b|\bbeing (handled|attended)\b", re.I)


def _key() -> str:
    return f"h-{uuid.uuid4()}"


def _body(conversation=None, reason="human_requested", summary="Synthetic: customer asks to talk to a person."):
    return {"conversation_id": conversation or f"conv-{uuid.uuid4().hex[:10]}", "reason": reason, "summary": summary}


def _post(client, token, body, key, **headers):
    h = {**bearer(token), **({"Idempotency-Key": key} if key is not None else {}), **headers}
    return client.post("/handoffs", json=body, headers=h)


def _count(pg_server, app_db, sql="SELECT count(*) FROM handoffs", params=()):
    with pg_server.connect(app_db["name"]) as conn:
        return conn.execute(sql, params).fetchone()[0]


# 1 + 2 + 3
@pytest.mark.parametrize("reason", ["critical_incident", "human_requested", "unsafe_to_resolve"])
def test_valid_handoff_persists_pending_for_authenticated_customer(api, pg_server, app_db, reason):
    client, tokens = api
    body = _body(reason=reason)
    before = _count(pg_server, app_db)
    r = _post(client, tokens["CUSTOMER_A"], body, _key())
    assert r.status_code == 201 and r.headers["Idempotency-Outcome"] == "created"
    h = r.json()
    uuid.UUID(h["id"])
    assert (h["customer_id"], h["conversation_id"], h["reason"], h["summary"], h["status"]) == \
           ("CUSTOMER_A", body["conversation_id"], reason, body["summary"], "pending")
    assert _count(pg_server, app_db) == before + 1
    with pg_server.connect(app_db["name"]) as conn:
        row = conn.execute("SELECT customer_id, conversation_id, reason, status FROM handoffs WHERE id = %s",
                           (h["id"],)).fetchone()
    assert row == ("CUSTOMER_A", body["conversation_id"], reason, "pending")


# 4
def test_spoofed_customer_id_cannot_override_auth(api, pg_server, app_db):
    client, tokens = api
    before = _count(pg_server, app_db)
    in_body = _post(client, tokens["CUSTOMER_A"], {**_body(), "customer_id": "CUSTOMER_B"}, _key())
    assert in_body.status_code == 422
    assert _count(pg_server, app_db) == before
    spoof = client.post("/handoffs", json=_body(), params={"customer_id": "CUSTOMER_B"},
                        headers={**bearer(tokens["CUSTOMER_A"]), "Idempotency-Key": _key(),
                                 "X-Customer-Id": "CUSTOMER_B"})
    assert spoof.status_code == 201 and spoof.json()["customer_id"] == "CUSTOMER_A"
    b = _post(client, tokens["CUSTOMER_B"], _body(), _key())
    assert b.status_code == 201 and b.json()["customer_id"] == "CUSTOMER_B"


def test_status_cannot_be_set_by_client(api, pg_server, app_db):
    client, tokens = api
    before = _count(pg_server, app_db)
    for extra in ({"status": "in_progress"}, {"status": "pending"}, {"assigned_to": "someone"}):
        assert _post(client, tokens["CUSTOMER_A"], {**_body(), **extra}, _key()).status_code == 422
    assert _count(pg_server, app_db) == before
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE handoffs SET status = 'in_progress' WHERE true")


# 5
@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer " + "x" * 40}, {"Authorization": "Basic abc"}])
def test_missing_or_invalid_auth_is_rejected(api, pg_server, app_db, headers):
    client, _ = api
    before = _count(pg_server, app_db)
    r = client.post("/handoffs", json=_body(), headers={**headers, "Idempotency-Key": _key()})
    assert r.status_code == 401
    assert _count(pg_server, app_db) == before


@pytest.mark.parametrize("bad", [
    {"reason": "angry_customer"}, {"reason": ""}, {"summary": ""}, {"summary": "x" * 2001},
    {"conversation_id": "has space"}, {"conversation_id": ""},
])
def test_invalid_fields_are_rejected(api, pg_server, app_db, bad):
    client, tokens = api
    before = _count(pg_server, app_db)
    assert _post(client, tokens["CUSTOMER_A"], {**_body(), **bad}, _key()).status_code == 422
    assert _count(pg_server, app_db) == before


def test_conversation_header_must_match_body(api, pg_server, app_db):
    client, tokens = api
    before = _count(pg_server, app_db)
    r = _post(client, tokens["CUSTOMER_A"], _body(conversation="conv-body"), _key(), **{"X-Conversation-ID": "conv-other"})
    assert r.status_code == 400
    ok = _post(client, tokens["CUSTOMER_A"], _body(conversation="conv-same"), _key(), **{"X-Conversation-ID": "conv-same"})
    assert ok.status_code == 201
    assert _count(pg_server, app_db) == before + 1


# 6 + 8
def test_same_key_same_request_replays_without_duplicate(api, pg_server, app_db):
    client, tokens = api
    body, key = _body(reason="critical_incident"), _key()
    before = _count(pg_server, app_db)
    responses = [_post(client, tokens["CUSTOMER_A"], body, key) for _ in range(3)]
    assert [r.status_code for r in responses] == [201, 201, 201]
    assert [r.headers["Idempotency-Outcome"] for r in responses] == ["created", "replay", "replay"]
    assert responses[0].json() == responses[1].json() == responses[2].json()
    assert _count(pg_server, app_db) == before + 1
    # Whitespace-only differences are the same effective request.
    padded = _post(client, tokens["CUSTOMER_A"], {**body, "summary": f"  {body['summary']}  "}, key)
    assert padded.status_code == 201 and padded.json()["id"] == responses[0].json()["id"]


# 7
@pytest.mark.parametrize("change", [{"reason": "unsafe_to_resolve"}, {"summary": "Synthetic: different."},
                                    {"conversation_id": "conv-different"}])
def test_same_key_different_request_conflicts(api, pg_server, app_db, change):
    client, tokens = api
    body, key = _body(), _key()
    first = _post(client, tokens["CUSTOMER_A"], body, key)
    before = _count(pg_server, app_db)
    r = _post(client, tokens["CUSTOMER_A"], {**body, **change}, key)
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_conflict"
    assert r.headers["Idempotency-Outcome"] == "conflict"
    assert first.json()["id"] not in r.text  # the conflicting request learns nothing about the original
    assert _count(pg_server, app_db) == before


def test_keys_are_scoped_per_customer(api):
    client, tokens = api
    key = _key()
    a = _post(client, tokens["CUSTOMER_A"], _body(), key)
    b = _post(client, tokens["CUSTOMER_B"], _body(), key)
    assert a.status_code == b.status_code == 201
    assert a.json()["id"] != b.json()["id"] and b.json()["customer_id"] == "CUSTOMER_B"


def test_concurrent_same_key_creates_one_handoff(api, pg_server, app_db):
    settings, key = load_settings(), _key()
    body = _body(reason="critical_incident")
    results, barrier = [None] * 6, threading.Barrier(6)
    before = _count(pg_server, app_db)

    def worker(i):
        with connect(settings, autocommit=True) as conn:
            barrier.wait()
            results[i] = handoffs.create(conn, "CUSTOMER_A", body["conversation_id"], body["reason"], body["summary"], key)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not any(t.is_alive() for t in threads) and None not in results
    assert _count(pg_server, app_db) == before + 1
    assert sorted(r.idempotency_outcome for r in results) == ["created"] + ["replay"] * 5
    assert len({r.handoff_id for r in results}) == 1


# 8 (response loss)
def test_retry_after_lost_response_returns_same_handoff(api, pg_server, app_db, monkeypatch):
    client, tokens = api
    from app.main import app

    body, key = _body(reason="critical_incident"), _key()
    before = _count(pg_server, app_db)
    real_create = handoffs.create

    def commit_then_lose_response(*args, **kwargs):
        real_create(*args, **kwargs)
        raise ConnectionResetError("simulated: response lost after commit")

    monkeypatch.setattr(handoffs, "create", commit_then_lose_response)
    with TestClient(app, raise_server_exceptions=False) as lossy:
        lost = _post(lossy, tokens["CUSTOMER_A"], body, key)
    assert lost.status_code == 500
    committed = _count(pg_server, app_db, "SELECT id::text FROM handoffs WHERE customer_id = 'CUSTOMER_A'"
                                          " AND idempotency_key = %s", (key,))
    monkeypatch.setattr(handoffs, "create", real_create)
    retry = _post(client, tokens["CUSTOMER_A"], body, key)
    assert retry.status_code == 201 and retry.headers["Idempotency-Outcome"] == "replay"
    assert retry.json()["id"] == committed
    assert _count(pg_server, app_db) == before + 1


@pytest.mark.parametrize("key", [None, "", "has space", "x" * 129, "bad/char"])
def test_missing_or_invalid_idempotency_key_is_rejected(api, pg_server, app_db, key):
    client, tokens = api
    before = _count(pg_server, app_db)
    assert _post(client, tokens["CUSTOMER_A"], _body(), key).status_code == 400
    assert _count(pg_server, app_db) == before


# 9
def test_database_unavailable_never_reports_success(pg_server, app_db, monkeypatch):
    from app.main import app

    for k, v in {**app_db["env"], "POSTGRES_PORT": str(_free_port())}.items():
        monkeypatch.setenv(k, v)
    with TestClient(app) as client:
        r = _post(client, app_db["tokens"]["CUSTOMER_A"], _body(), _key())
    assert r.status_code == 503
    assert "id" not in r.json() and "pending" not in r.text


def test_failure_inside_transaction_leaves_no_handoff(api, pg_server, app_db):
    client, tokens = api
    body, key = _body(), _key()
    before = _count(pg_server, app_db)
    with pg_server.connect(app_db["name"]) as conn:
        conn.execute("CREATE OR REPLACE FUNCTION fail_handoff() RETURNS trigger LANGUAGE plpgsql AS"
                     " $$ BEGIN RAISE EXCEPTION 'simulated database failure'; END; $$")
        conn.execute("DROP TRIGGER IF EXISTS fail_handoff ON handoffs")
        conn.execute("CREATE TRIGGER fail_handoff AFTER INSERT ON handoffs FOR EACH ROW EXECUTE FUNCTION fail_handoff()")
    try:
        failed = _post(client, tokens["CUSTOMER_A"], body, key)
        assert failed.status_code == 503 and "retry with the same Idempotency-Key" in failed.json()["detail"]
        assert "simulated" not in failed.text and "pending" not in failed.text
        assert _count(pg_server, app_db) == before
    finally:
        with pg_server.connect(app_db["name"]) as conn:
            conn.execute("DROP TRIGGER IF EXISTS fail_handoff ON handoffs")
            conn.execute("DROP FUNCTION IF EXISTS fail_handoff()")
    ok = _post(client, tokens["CUSTOMER_A"], body, key)
    assert ok.status_code == 201 and ok.headers["Idempotency-Outcome"] == "created"
    assert _count(pg_server, app_db) == before + 1


# 10 + 11
def test_audit_log_has_ids_and_no_secrets(api, app_db, caplog):
    client, tokens = api
    body, key = _body(conversation="conv-handoff-audit", reason="critical_incident"), _key()
    with caplog.at_level(logging.DEBUG):
        created = _post(client, tokens["CUSTOMER_A"], body, key,
                        **{"X-Request-ID": "req-handoff-1", "X-Conversation-ID": "conv-handoff-audit"}).json()
        _post(client, tokens["CUSTOMER_A"], body, key)
        _post(client, tokens["CUSTOMER_A"], {**body, "summary": "Synthetic: changed."}, key)
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "nexo.audit"]
    first = events[0]
    expected = {"request_id": "req-handoff-1", "conversation_id": "conv-handoff-audit", "action": "handoff_create",
                "reason": "critical_incident", "handoff_id": created["id"], "idempotency": "created",
                "result": "success", "status": 201, "customer_id": "CUSTOMER_A"}
    assert expected.items() <= first.items() and isinstance(first["duration_ms"], float)
    assert [e["idempotency"] for e in events] == ["created", "replay", "conflict"]
    text = caplog.text
    for secret in (tokens["CUSTOMER_A"], tokens["CUSTOMER_B"], app_db["env"]["POSTGRES_PASSWORD"]):
        assert secret not in text
    assert "Bearer " not in text and "authorization" not in text.lower()
    assert body["summary"] not in text  # summary content is persisted, not logged


# 12
def test_response_never_claims_a_human_is_attending(api):
    client, tokens = api
    r = _post(client, tokens["CUSTOMER_A"], _body(reason="critical_incident"), _key())
    h = r.json()
    assert h["status"] == "pending"
    assert "pending human attention" in h["status_message"]
    assert "not yet been picked up" in h["status_message"]
    assert not FORBIDDEN_CLAIMS.search(r.text), FORBIDDEN_CLAIMS.search(r.text)
    assert not FORBIDDEN_CLAIMS.search(handoffs.STATUS_MESSAGE)
    assert set(h) == {"id", "customer_id", "conversation_id", "reason", "summary", "status", "status_message",
                      "created_at", "updated_at"}  # no assignee / ETA fields exist


def test_forbidden_claims_detector_works():
    for claim in ("A human is attending your case", "Assigned to Maria", "An agent will contact you shortly",
                  "Your request is in progress", "being handled now"):
        assert FORBIDDEN_CLAIMS.search(claim), claim
