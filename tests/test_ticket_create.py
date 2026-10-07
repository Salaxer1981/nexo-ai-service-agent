"""APP-02: confirmed, idempotent ticket creation against real PostgreSQL.

Numbered comments refer to the 23 required cases of the APP-02 brief.
"""
import hashlib
import json
import logging
import threading
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import ticket_actions
from app.config import load_settings
from app.db import connect
from conftest import bearer

DRAFT = {
    "contact_name": "Ana (synthetic)",
    "subject": "Synthetic: no internet in the whole office",
    "description": "Synthetic test: the whole office has had no internet for twenty minutes.",
    "priority": "critical",
}


# --- helpers ---------------------------------------------------------------------------

def _key() -> str:
    return f"test-{uuid.uuid4()}"


def _prepare(client, token, draft=None, conversation=None, **kwargs):
    headers = {**bearer(token), **({"X-Conversation-ID": conversation} if conversation else {})}
    return client.post("/tickets/prepare", json=draft or DRAFT, headers=headers, **kwargs)


def _confirm(client, token, action_id, payload_hash, key, **extra_headers):
    headers = {**bearer(token), **({"Idempotency-Key": key} if key else {}), **extra_headers}
    return client.post("/tickets/confirm", headers=headers,
                       json={"pending_action_id": action_id, "payload_hash": payload_hash})


def _row(pg_server, app_db, sql, params=()):
    with pg_server.connect(app_db["name"]) as conn:
        return conn.execute(sql, params).fetchone()


def _count(pg_server, app_db, sql="SELECT count(*) FROM tickets", params=()):
    return _row(pg_server, app_db, sql, params)[0]


def _action_status(pg_server, app_db, action_id):
    return _count(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE id = %s", (action_id,))


def _independent_hash(customer_id, data):
    """Re-implements the documented canonical form independently of the app code."""
    doc = {"v": "ticket-v1", "customer_id": customer_id, **data}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


# --- prepare ---------------------------------------------------------------------------

# 1
def test_prepare_creates_no_ticket(api, pg_server, app_db):
    client, tokens = api
    before = _count(pg_server, app_db)
    r = _prepare(client, tokens["CUSTOMER_A"])
    assert r.status_code == 201
    assert _count(pg_server, app_db) == before
    assert _action_status(pg_server, app_db, r.json()["pending_action_id"]) == "pending"


# 2
def test_prepare_returns_summary_bound_to_exact_data(api):
    client, tokens = api
    body = _prepare(client, tokens["CUSTOMER_A"]).json()
    assert body["status"] == "pending" and body["confirmation_required"] is True
    assert body["summary"] == {"customer_id": "CUSTOMER_A", **DRAFT}
    assert body["payload_hash"] == _independent_hash("CUSTOMER_A", DRAFT)
    for value in DRAFT.values():
        assert value in body["summary_text"]
    # Deterministic: same data -> same fingerprint; outer whitespace is normalized.
    padded = {k: f"  {v}  " if k != "priority" else v for k, v in DRAFT.items()}
    again = _prepare(client, tokens["CUSTOMER_A"], padded).json()
    assert again["payload_hash"] == body["payload_hash"]
    assert again["pending_action_id"] != body["pending_action_id"]
    # Bound to the owner: identical data for another customer has a different fingerprint.
    other = _prepare(client, tokens["CUSTOMER_B"]).json()
    assert other["payload_hash"] != body["payload_hash"]


# --- confirm ---------------------------------------------------------------------------

# 3 + 4
def test_confirm_creates_exactly_one_ticket_owned_by_caller(api, pg_server, app_db):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    before = _count(pg_server, app_db)
    r = _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], _key())
    assert r.status_code == 201
    assert r.headers["Idempotency-Outcome"] == "created"
    ticket = r.json()
    assert _count(pg_server, app_db) == before + 1
    assert {k: ticket[k] for k in DRAFT} == DRAFT
    assert ticket["customer_id"] == "CUSTOMER_A" and ticket["status"] == "open"
    owner, source = _row(pg_server, app_db, "SELECT customer_id, source_action_id::text FROM tickets"
                         " WHERE id = %s", (ticket["id"],))
    assert (owner, source) == ("CUSTOMER_A", prepared["pending_action_id"])
    assert _action_status(pg_server, app_db, prepared["pending_action_id"]) == "consumed"
    # The real identifier is queryable by the owner only.
    assert client.get(f"/tickets/{ticket['id']}", headers=bearer(tokens["CUSTOMER_A"])).status_code == 200
    assert client.get(f"/tickets/{ticket['id']}", headers=bearer(tokens["CUSTOMER_B"])).status_code == 404


# 5
def test_customer_a_cannot_confirm_customer_b_action(api, pg_server, app_db):
    client, tokens = api
    prepared_b = _prepare(client, tokens["CUSTOMER_B"]).json()
    before = _count(pg_server, app_db)
    foreign = _confirm(client, tokens["CUSTOMER_A"], prepared_b["pending_action_id"],
                       prepared_b["payload_hash"], _key())
    unknown = _confirm(client, tokens["CUSTOMER_A"], str(uuid.uuid4()), prepared_b["payload_hash"], _key())
    assert foreign.status_code == unknown.status_code == 404
    assert foreign.json() == unknown.json() == {"detail": "Pending action not found"}
    for leaked in ("CUSTOMER_B", DRAFT["subject"], DRAFT["contact_name"]):
        assert leaked not in foreign.text
    assert _count(pg_server, app_db) == before
    assert _action_status(pg_server, app_db, prepared_b["pending_action_id"]) == "pending"
    # B can still confirm its own action.
    ok = _confirm(client, tokens["CUSTOMER_B"], prepared_b["pending_action_id"], prepared_b["payload_hash"], _key())
    assert ok.status_code == 201 and ok.json()["customer_id"] == "CUSTOMER_B"


# 6
def test_customer_id_input_cannot_override_authentication(api, pg_server, app_db):
    client, tokens = api
    token_a = tokens["CUSTOMER_A"]
    before_actions = _count(pg_server, app_db, "SELECT count(*) FROM pending_ticket_actions")
    in_body = client.post("/tickets/prepare", json={**DRAFT, "customer_id": "CUSTOMER_B"}, headers=bearer(token_a))
    assert in_body.status_code == 422  # unknown fields are refused, never interpreted
    assert _count(pg_server, app_db, "SELECT count(*) FROM pending_ticket_actions") == before_actions

    spoof_headers = {"X-Customer-Id": "CUSTOMER_B"}
    prepared = client.post("/tickets/prepare", json=DRAFT, params={"customer_id": "CUSTOMER_B"},
                           headers={**bearer(token_a), **spoof_headers}).json()
    assert prepared["summary"]["customer_id"] == "CUSTOMER_A"
    body_spoof = client.post("/tickets/confirm", headers={**bearer(token_a), "Idempotency-Key": _key()},
                             json={"pending_action_id": prepared["pending_action_id"],
                                   "payload_hash": prepared["payload_hash"], "customer_id": "CUSTOMER_B"})
    assert body_spoof.status_code == 422
    r = _confirm(client, token_a, prepared["pending_action_id"], prepared["payload_hash"], _key(), **spoof_headers)
    assert r.status_code == 201 and r.json()["customer_id"] == "CUSTOMER_A"


# 7, 8, 9, 10
@pytest.mark.parametrize("field,new_value", [
    ("contact_name", "Someone Else (synthetic)"),
    ("subject", "Synthetic: different subject"),
    ("description", "Synthetic: different description."),
    ("priority", "normal"),
])
def test_changing_any_field_invalidates_previous_confirmation(api, pg_server, app_db, field, new_value):
    client, tokens = api
    token = tokens["CUSTOMER_A"]
    conversation = f"conv-{uuid.uuid4().hex[:8]}"
    changed = {**DRAFT, field: new_value}
    before = _count(pg_server, app_db)

    old = _prepare(client, token, DRAFT, conversation).json()
    new = _prepare(client, token, changed, conversation).json()  # the data changed: re-prepared
    assert new["payload_hash"] != old["payload_hash"]
    assert _action_status(pg_server, app_db, old["pending_action_id"]) == "superseded"

    stale = _confirm(client, token, old["pending_action_id"], old["payload_hash"], _key())
    assert stale.status_code == 409 and stale.json()["code"] == "confirmation_invalid"
    swapped = _confirm(client, token, old["pending_action_id"], new["payload_hash"], _key())
    assert swapped.status_code == 409
    assert _count(pg_server, app_db) == before

    # A fingerprint for modified data never confirms an action prepared with other data.
    lone = _prepare(client, token, DRAFT, f"conv-{uuid.uuid4().hex[:8]}").json()
    mismatch = _confirm(client, token, lone["pending_action_id"], _independent_hash("CUSTOMER_A", changed), _key())
    assert mismatch.status_code == 409 and mismatch.json()["code"] == "confirmation_mismatch"
    assert _count(pg_server, app_db) == before

    # Only the new cycle creates a ticket, with the new data.
    ok = _confirm(client, token, new["pending_action_id"], new["payload_hash"], _key())
    assert ok.status_code == 201 and ok.json()[field] == new_value
    assert _count(pg_server, app_db) == before + 1


# --- idempotency -----------------------------------------------------------------------

# 11 + 12
def test_same_key_same_action_returns_same_ticket_without_duplicates(api, pg_server, app_db):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    key = _key()
    before = _count(pg_server, app_db)
    responses = [_confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"],
                          prepared["payload_hash"], key) for _ in range(3)]
    assert [r.status_code for r in responses] == [201, 201, 201]
    assert [r.headers["Idempotency-Outcome"] for r in responses] == ["created", "replay", "replay"]
    assert responses[0].json() == responses[1].json() == responses[2].json()
    assert _count(pg_server, app_db) == before + 1


# 13
def test_same_key_with_different_request_conflicts(api, pg_server, app_db):
    client, tokens = api
    token = tokens["CUSTOMER_A"]
    first = _prepare(client, token, conversation="c-1").json()
    second = _prepare(client, token, {**DRAFT, "subject": "Synthetic: another"}, conversation="c-2").json()
    key = _key()
    assert _confirm(client, token, first["pending_action_id"], first["payload_hash"], key).status_code == 201
    before = _count(pg_server, app_db)
    other_action = _confirm(client, token, second["pending_action_id"], second["payload_hash"], key)
    assert other_action.status_code == 409
    assert other_action.json()["code"] == "idempotency_key_conflict"
    assert other_action.headers["Idempotency-Outcome"] == "conflict"
    other_hash = _confirm(client, token, first["pending_action_id"], second["payload_hash"], key)
    assert other_hash.status_code == 409 and other_hash.json()["code"] == "idempotency_key_conflict"
    assert _count(pg_server, app_db) == before
    assert _action_status(pg_server, app_db, second["pending_action_id"]) == "pending"


def test_idempotency_keys_are_scoped_per_customer(api):
    client, tokens = api
    key = _key()
    a = _prepare(client, tokens["CUSTOMER_A"]).json()
    b = _prepare(client, tokens["CUSTOMER_B"]).json()
    ra = _confirm(client, tokens["CUSTOMER_A"], a["pending_action_id"], a["payload_hash"], key)
    rb = _confirm(client, tokens["CUSTOMER_B"], b["pending_action_id"], b["payload_hash"], key)
    assert ra.status_code == rb.status_code == 201
    assert ra.json()["customer_id"] == "CUSTOMER_A" and rb.json()["customer_id"] == "CUSTOMER_B"


# 14
def test_retry_after_lost_response_returns_committed_ticket(api, pg_server, app_db, monkeypatch):
    client, tokens = api
    from app.main import app

    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    key = _key()
    before = _count(pg_server, app_db)
    real_confirm = ticket_actions.confirm

    def commit_then_lose_response(*args, **kwargs):
        real_confirm(*args, **kwargs)  # the ticket IS committed here ...
        raise ConnectionResetError("simulated: response lost after commit")  # ... the caller never hears

    monkeypatch.setattr(ticket_actions, "confirm", commit_then_lose_response)
    with TestClient(app, raise_server_exceptions=False) as lossy:
        lost = _confirm(lossy, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], key)
    assert lost.status_code == 500 and "ticket" not in lost.text.lower()
    committed_id = _count(pg_server, app_db, "SELECT id::text FROM tickets WHERE source_action_id = %s",
                          (prepared["pending_action_id"],))
    assert _count(pg_server, app_db) == before + 1

    monkeypatch.setattr(ticket_actions, "confirm", real_confirm)
    retry = _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], key)
    assert retry.status_code == 201
    assert retry.headers["Idempotency-Outcome"] == "replay"
    assert retry.json()["id"] == committed_id
    assert _count(pg_server, app_db) == before + 1


# 15
def test_consumed_confirmation_cannot_create_another_ticket(api, pg_server, app_db):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    first = _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], _key())
    before = _count(pg_server, app_db)
    reuse = _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], _key())
    assert reuse.status_code == 409
    assert reuse.json()["code"] == "confirmation_already_used"
    assert reuse.json()["ticket_id"] == first.json()["id"]
    assert _count(pg_server, app_db) == before


def test_database_rejects_second_ticket_for_same_action(pg_server, app_db, api):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], _key())
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO tickets (customer_id, contact_name, subject, description, priority,"
                         " source_action_id) VALUES ('CUSTOMER_A', 'x', 'x', 'x', 'normal', %s)",
                         (prepared["pending_action_id"],))


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_confirmations_create_one_ticket(api, pg_server, app_db, same_key):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    settings = load_settings()
    keys = [_key()] * 2 if same_key else [_key(), _key()]
    results, barrier = [None, None], threading.Barrier(2)
    before = _count(pg_server, app_db)

    def worker(i):
        with connect(settings, autocommit=True) as conn:
            barrier.wait()
            results[i] = ticket_actions.confirm(conn, "CUSTOMER_A", uuid.UUID(prepared["pending_action_id"]),
                                                prepared["payload_hash"], keys[i])

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads), "a confirmation worker hung"
    assert None not in results
    assert _count(pg_server, app_db) == before + 1
    statuses = sorted(r.status for r in results)
    if same_key:
        assert statuses == [201, 201]
        assert results[0].body["id"] == results[1].body["id"]
        assert sorted(r.idempotency_outcome for r in results) == ["created", "replay"]
    else:
        assert statuses == [201, 409]
        assert [r for r in results if r.status == 409][0].body["code"] == "confirmation_already_used"


# 16
@pytest.mark.parametrize("key", [None, "", "has space", "x" * 129, "bad/char"])
def test_missing_or_invalid_idempotency_key_is_rejected(api, pg_server, app_db, key):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    before = _count(pg_server, app_db)
    headers = {**bearer(tokens["CUSTOMER_A"]), **({"Idempotency-Key": key} if key is not None else {})}
    r = client.post("/tickets/confirm", headers=headers,
                    json={"pending_action_id": prepared["pending_action_id"], "payload_hash": prepared["payload_hash"]})
    assert r.status_code == 400
    assert _count(pg_server, app_db) == before
    assert _action_status(pg_server, app_db, prepared["pending_action_id"]) == "pending"


# 17
@pytest.mark.parametrize("priority", ["urgent", "high", "medium", "low", "Critical", "", None])
def test_invalid_priority_is_rejected(api, pg_server, app_db, priority):
    client, tokens = api
    before = _count(pg_server, app_db, "SELECT count(*) FROM pending_ticket_actions")
    r = _prepare(client, tokens["CUSTOMER_A"], {**DRAFT, "priority": priority})
    assert r.status_code == 422
    assert _count(pg_server, app_db, "SELECT count(*) FROM pending_ticket_actions") == before


# 18 + 19
@pytest.mark.parametrize("priority", ["normal", "critical"])
def test_canonical_priorities_create_tickets(api, priority):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_B"], {**DRAFT, "priority": priority}).json()
    r = _confirm(client, tokens["CUSTOMER_B"], prepared["pending_action_id"], prepared["payload_hash"], _key())
    assert r.status_code == 201 and r.json()["priority"] == priority


def test_plain_confirmed_flag_cannot_bypass_binding(api, pg_server, app_db):
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    before = _count(pg_server, app_db)
    flag = client.post("/tickets/confirm", headers={**bearer(tokens["CUSTOMER_A"]), "Idempotency-Key": _key()},
                       json={"pending_action_id": prepared["pending_action_id"], "confirmed": True})
    direct = client.post("/tickets", headers={**bearer(tokens["CUSTOMER_A"]), "Idempotency-Key": _key()},
                         json={**DRAFT, "confirmed": True})
    assert flag.status_code == 422
    assert direct.status_code in (404, 405)
    assert _count(pg_server, app_db) == before


# 20
def test_no_ticket_when_confirmation_validation_fails(api, pg_server, app_db):
    client, tokens = api
    token = tokens["CUSTOMER_A"]
    before = _count(pg_server, app_db)
    expired = _prepare(client, token, conversation="c-exp").json()
    with pg_server.connect(app_db["name"]) as conn:
        conn.execute("UPDATE pending_ticket_actions SET expires_at = now() - interval '1 second' WHERE id = %s",
                     (expired["pending_action_id"],))
    r = _confirm(client, token, expired["pending_action_id"], expired["payload_hash"], _key())
    assert r.status_code == 409 and r.json()["code"] == "confirmation_invalid"
    assert _action_status(pg_server, app_db, expired["pending_action_id"]) == "expired"

    fresh = _prepare(client, token, conversation="c-bad").json()
    for bad_hash in ("0" * 64, "f" * 64):
        assert _confirm(client, token, fresh["pending_action_id"], bad_hash, _key()).status_code == 409
    assert _confirm(client, token, str(uuid.uuid4()), fresh["payload_hash"], _key()).status_code == 404
    assert _count(pg_server, app_db) == before


# 21
def test_database_unavailable_never_reports_success(pg_server, app_db, monkeypatch):
    from app.main import app
    from conftest import _free_port

    env = {**app_db["env"], "POSTGRES_PORT": str(_free_port())}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with TestClient(app) as client:
        prep = client.post("/tickets/prepare", json=DRAFT, headers=bearer(app_db["tokens"]["CUSTOMER_A"]))
        conf = client.post("/tickets/confirm", headers={**bearer(app_db["tokens"]["CUSTOMER_A"]),
                                                        "Idempotency-Key": _key()},
                           json={"pending_action_id": str(uuid.uuid4()), "payload_hash": "a" * 64})
    assert prep.status_code == conf.status_code == 503
    for r in (prep, conf):
        assert "id" not in r.json() and "created" not in r.text.lower()


def test_failure_inside_transaction_rolls_back_ticket(api, pg_server, app_db):
    """A DB error after the ticket INSERT must leave no ticket and no false success."""
    client, tokens = api
    prepared = _prepare(client, tokens["CUSTOMER_A"]).json()
    key = _key()
    before = _count(pg_server, app_db)
    with pg_server.connect(app_db["name"]) as conn:
        conn.execute("CREATE OR REPLACE FUNCTION fail_idem() RETURNS trigger LANGUAGE plpgsql AS"
                     " $$ BEGIN RAISE EXCEPTION 'simulated database failure'; END; $$")
        conn.execute("DROP TRIGGER IF EXISTS fail_idem ON idempotency_keys")
        conn.execute("CREATE TRIGGER fail_idem BEFORE INSERT ON idempotency_keys"
                     " FOR EACH ROW EXECUTE FUNCTION fail_idem()")
    try:
        failed = _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], key)
        assert failed.status_code == 503
        assert "retry with the same Idempotency-Key" in failed.json()["detail"]
        assert "simulated" not in failed.text
        assert _count(pg_server, app_db) == before  # the ticket INSERT was rolled back
        assert _action_status(pg_server, app_db, prepared["pending_action_id"]) == "pending"
    finally:
        with pg_server.connect(app_db["name"]) as conn:
            conn.execute("DROP TRIGGER IF EXISTS fail_idem ON idempotency_keys")
            conn.execute("DROP FUNCTION IF EXISTS fail_idem()")
    ok = _confirm(client, tokens["CUSTOMER_A"], prepared["pending_action_id"], prepared["payload_hash"], key)
    assert ok.status_code == 201 and ok.headers["Idempotency-Outcome"] == "created"
    assert _count(pg_server, app_db) == before + 1


# --- traceability ----------------------------------------------------------------------

def _events(caplog):
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "nexo.audit"]


# 22
def test_audit_log_records_ids_and_outcomes(api, caplog):
    client, tokens = api
    token = tokens["CUSTOMER_A"]
    key = _key()
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        prepared = _prepare(client, token, conversation="conv-audit").json()
        created = _confirm(client, token, prepared["pending_action_id"], prepared["payload_hash"], key,
                           **{"X-Conversation-ID": "conv-audit", "X-Request-ID": "req-audit-1"}).json()
        _confirm(client, token, prepared["pending_action_id"], prepared["payload_hash"], key)
        other = _prepare(client, token, conversation="conv-audit-2").json()
        _confirm(client, token, other["pending_action_id"], other["payload_hash"], key)
    prep_event, created_event, replay_event, _, conflict_event = _events(caplog)

    assert prep_event["action"] == "ticket_prepare" and prep_event["result"] == "prepared"
    assert prep_event["pending_action_id"] == prepared["pending_action_id"]
    assert prep_event["conversation_id"] == "conv-audit"
    expected = {
        "request_id": "req-audit-1", "conversation_id": "conv-audit", "action": "ticket_confirm",
        "pending_action_id": prepared["pending_action_id"], "confirmation_result": "confirmed",
        "idempotency": "created", "ticket_id": created["id"], "result": "success", "status": 201,
        "customer_id": "CUSTOMER_A"}
    assert expected.items() <= created_event.items()
    assert replay_event["idempotency"] == "replay" and replay_event["ticket_id"] == created["id"]
    assert conflict_event["idempotency"] == "conflict" and conflict_event["status"] == 409
    assert all(isinstance(e["duration_ms"], float) for e in _events(caplog))


# 23
def test_audit_log_contains_no_credentials_or_ticket_content(api, app_db, caplog):
    client, tokens = api
    with caplog.at_level(logging.DEBUG):
        p = _prepare(client, tokens["CUSTOMER_A"]).json()
        _confirm(client, tokens["CUSTOMER_A"], p["pending_action_id"], p["payload_hash"], _key())
        _confirm(client, tokens["CUSTOMER_B"], p["pending_action_id"], p["payload_hash"], _key())
        _confirm(client, tokens["CUSTOMER_A"], p["pending_action_id"], p["payload_hash"], None)
    text = caplog.text
    for secret in (tokens["CUSTOMER_A"], tokens["CUSTOMER_B"], app_db["env"]["POSTGRES_PASSWORD"]):
        assert secret not in text
    assert "Bearer " not in text and "authorization" not in text.lower()
    # Data minimization: ticket content is persisted in the DB, not copied into logs.
    assert DRAFT["description"] not in text and DRAFT["contact_name"] not in text
