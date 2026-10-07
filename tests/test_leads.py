"""APP-03B: confirmed lead creation through n8n, against real PostgreSQL 17.

IMPORTANT: `FakeN8n` below is NOT n8n. It is a controlled HTTP stand-in that reproduces the
workflow's contract (webhook -> envelope check -> POST /internal/leads with the service credential ->
return the backend result) so the backend's real network hop can be tested locally. It proves the
backend side only. Real n8n execution is proven in the VM phase.
"""
import hashlib
import json
import logging
import re
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app import leads
from app.config import load_settings
from app.db import connect
from conftest import ROOT, _free_port, bearer

DRAFT = {"company_name": "Asesoria Ejemplo (synthetic)", "contact_name": "Luis (synthetic)",
         "contact_email": "Luis@Example.TEST", "need": "Synthetic: automate client enquiries for an 18-person firm."}
NORMALIZED = {**DRAFT, "contact_email": "luis@example.test"}


class FakeN8n:
    """Stand-in for the n8n workflow (NOT n8n). Modes simulate the failure cases of the brief."""

    def __init__(self, app, service_token):
        self.app, self.service_token = app, service_token
        self.mode, self.calls, self.executions = "forward", 0, 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                fake.calls += 1
                envelope = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, body = fake.handle(envelope, self.headers.get("X-Request-ID", ""))
                if status is None:  # simulate "response lost": close without answering
                    self.close_connection = True
                    return
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/webhook/nexo-lead-create"

    def forward(self, envelope, request_id, lead=None):
        """What the workflow's HTTP Request node does: call the private endpoint with the service token."""
        self.executions += 1
        r = TestClient(self.app, raise_server_exceptions=False).post(
            "/internal/leads",
            headers={"Authorization": f"Bearer {self.service_token}", "Idempotency-Key": envelope["idempotency_key"],
                     "X-Request-ID": request_id},
            json={"pending_action_id": envelope["pending_action_id"], "payload_hash": envelope["payload_hash"],
                  "lead": lead or envelope["lead"], "workflow_execution_id": f"fake-exec-{self.executions}"})
        return r.status_code, r.json()

    def handle(self, envelope, request_id):
        if not all(envelope.get(k) for k in ("pending_action_id", "idempotency_key", "payload_hash", "lead")):
            return 400, {"code": "invalid_envelope"}
        if self.mode == "forward":
            return self.forward(envelope, request_id)
        if self.mode == "fail_500":  # n8n itself fails before calling the backend
            return 500, {"message": "Workflow could not be started"}
        if self.mode == "internal_unreachable":  # n8n's HTTP node cannot reach /internal/leads
            return 500, {"message": "connect ECONNREFUSED backend:8000"}
        if self.mode == "commit_then_drop":  # backend commits, the answer never reaches the backend caller
            self.forward(envelope, request_id)
            return None, None
        if self.mode == "duplicate":  # n8n retries its HTTP request: two deliveries
            self.forward(envelope, request_id)
            return self.forward(envelope, request_id)
        if self.mode == "tamper":  # a modified lead must be refused by the backend
            return self.forward(envelope, request_id, lead={**envelope["lead"], "need": "Tampered need"})
        if self.mode == "success_without_write":  # claims success but never wrote
            return 201, {"id": str(uuid.uuid4()), "idempotency": "created"}
        raise AssertionError(self.mode)


@pytest.fixture(scope="module")
def fake_n8n(app_db):
    from app.main import app
    fake = FakeN8n(app, app_db["service_token"])
    yield fake
    fake.server.shutdown()


@pytest.fixture
def lapi(app_db, fake_n8n, monkeypatch):
    from app.main import app
    for k, v in {**app_db["env"], "N8N_LEAD_WEBHOOK_URL": fake_n8n.url}.items():
        monkeypatch.setenv(k, v)
    fake_n8n.mode, fake_n8n.calls = "forward", 0
    with TestClient(app) as client:
        yield client, app_db["tokens"], fake_n8n


def _key():
    return f"lk-{uuid.uuid4()}"


def _conv():
    return f"lconv-{uuid.uuid4().hex[:10]}"


def _prepare(client, token, draft=None, conversation=None):
    headers = {**bearer(token), **({"X-Conversation-ID": conversation} if conversation else {})}
    return client.post("/leads/prepare", json=draft or DRAFT, headers=headers)


def _confirm(client, token, prepared, key, **headers):
    h = {**bearer(token), **({"Idempotency-Key": key} if key is not None else {}), **headers}
    return client.post("/leads/confirm", headers=h,
                       json={"pending_action_id": prepared["pending_action_id"], "payload_hash": prepared["payload_hash"]})


def _q(pg_server, app_db, sql, params=()):
    with pg_server.connect(app_db["name"]) as conn:
        return conn.execute(sql, params).fetchone()


def _leads(pg_server, app_db):
    return _q(pg_server, app_db, "SELECT count(*) FROM leads")[0]


def _status(pg_server, app_db, action_id):
    return _q(pg_server, app_db, "SELECT status FROM pending_lead_actions WHERE id = %s", (action_id,))[0]


def _independent_hash(requested_by, lead):
    doc = {"v": "lead-v1", "requested_by": requested_by, **lead}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


# ===================================== prepare ==========================================

def test_prepare_creates_no_lead_and_binds_exact_data(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    before = _leads(pg_server, app_db)
    r = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv())
    assert r.status_code == 201
    p = r.json()
    assert p["status"] == "pending" and p["confirmation_required"] is True
    assert p["summary"] == NORMALIZED  # e-mail lower-cased deterministically
    assert p["payload_hash"] == _independent_hash("CUSTOMER_A", NORMALIZED)
    assert all(v in p["summary_text"] for v in NORMALIZED.values())
    assert _leads(pg_server, app_db) == before and fake.calls == 0
    assert _status(pg_server, app_db, p["pending_action_id"]) == "pending"


@pytest.mark.parametrize("bad", [
    {"contact_email": "not-an-email"}, {"contact_email": "a b@example.test"}, {"company_name": ""},
    {"need": "x" * 2001}, {"customer_id": "CUSTOMER_B"}, {"confirmed": True}, {"phone": "600000000"},
])
def test_prepare_rejects_invalid_or_unknown_fields(lapi, pg_server, app_db, bad):
    client, tokens, _ = lapi
    before = _q(pg_server, app_db, "SELECT count(*) FROM pending_lead_actions")[0]
    assert _prepare(client, tokens["CUSTOMER_A"], {**DRAFT, **bad}).status_code == 422
    assert _q(pg_server, app_db, "SELECT count(*) FROM pending_lead_actions")[0] == before


def test_prepare_requires_auth_and_valid_conversation_header(lapi):
    client, tokens, _ = lapi
    assert client.post("/leads/prepare", json=DRAFT).status_code == 401
    r = client.post("/leads/prepare", json=DRAFT, headers={**bearer(tokens["CUSTOMER_A"]), "X-Conversation-ID": "bad value"})
    assert r.status_code == 400


# ===================================== confirm ==========================================

def test_confirm_creates_lead_only_through_the_workflow(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    before = _leads(pg_server, app_db)
    r = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert r.status_code == 201 and r.headers["Idempotency-Outcome"] == "created"
    lead = r.json()
    assert {k: lead[k] for k in NORMALIZED} == NORMALIZED
    assert lead["requested_by_customer_id"] == "CUSTOMER_A"
    assert lead["workflow_execution_id"].startswith("fake-exec-")
    assert "No price, discount, contract or date has been committed" in lead["status_message"]
    assert fake.calls == 1 and _leads(pg_server, app_db) == before + 1
    row = _q(pg_server, app_db, "SELECT requested_by_customer_id, source_action_id::text, workflow_execution_id"
                                " FROM leads WHERE id = %s", (lead["id"],))
    assert row == ("CUSTOMER_A", p["pending_action_id"], lead["workflow_execution_id"])
    assert _status(pg_server, app_db, p["pending_action_id"]) == "consumed"


def test_same_key_replays_without_calling_n8n_again(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p, key = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json(), _key()
    first = _confirm(client, tokens["CUSTOMER_A"], p, key)
    calls, before = fake.calls, _leads(pg_server, app_db)
    for _ in range(2):
        again = _confirm(client, tokens["CUSTOMER_A"], p, key)
        assert again.status_code == 201 and again.headers["Idempotency-Outcome"] == "replay"
        assert again.json()["id"] == first.json()["id"]
    assert fake.calls == calls and _leads(pg_server, app_db) == before


def test_same_key_different_action_conflicts(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    a = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    b = _prepare(client, tokens["CUSTOMER_A"], {**DRAFT, "need": "Synthetic: other need"}, conversation=_conv()).json()
    key = _key()
    assert _confirm(client, tokens["CUSTOMER_A"], a, key).status_code == 201
    calls, before = fake.calls, _leads(pg_server, app_db)
    r = _confirm(client, tokens["CUSTOMER_A"], b, key)
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_conflict"
    assert r.headers["Idempotency-Outcome"] == "conflict"
    assert fake.calls == calls and _leads(pg_server, app_db) == before
    assert _status(pg_server, app_db, b["pending_action_id"]) == "pending"


def test_consumed_action_with_new_key_is_rejected(lapi, pg_server, app_db):
    client, tokens, _ = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    first = _confirm(client, tokens["CUSTOMER_A"], p, _key()).json()
    before = _leads(pg_server, app_db)
    r = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert r.status_code == 409 and r.json()["code"] == "confirmation_already_used"
    assert r.json()["lead_id"] == first["id"] and _leads(pg_server, app_db) == before


@pytest.mark.parametrize("field,value", [("company_name", "Other Co (synthetic)"), ("contact_name", "Ana (synthetic)"),
                                         ("contact_email", "ana@example.test"), ("need", "Synthetic: changed need")])
def test_changing_any_field_requires_new_confirmation(lapi, pg_server, app_db, field, value):
    client, tokens, _ = lapi
    conv = _conv()
    before = _leads(pg_server, app_db)
    old = _prepare(client, tokens["CUSTOMER_A"], conversation=conv).json()
    new = _prepare(client, tokens["CUSTOMER_A"], {**DRAFT, field: value}, conversation=conv).json()
    assert _status(pg_server, app_db, old["pending_action_id"]) == "superseded"
    r = _confirm(client, tokens["CUSTOMER_A"], old, _key())
    assert r.status_code == 409 and r.json()["code"] == "confirmation_invalid"
    mismatch = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    wrong = {**mismatch, "payload_hash": _independent_hash("CUSTOMER_A", {**NORMALIZED, field: value.lower()
                                                                           if field == "contact_email" else value})}
    r = _confirm(client, tokens["CUSTOMER_A"], wrong, _key())
    assert r.status_code == 409 and r.json()["code"] == "confirmation_mismatch"
    assert _leads(pg_server, app_db) == before
    ok = _confirm(client, tokens["CUSTOMER_A"], new, _key())
    assert ok.status_code == 201 and ok.json()[field] == (value.lower() if field == "contact_email" else value)
    assert _leads(pg_server, app_db) == before + 1


def test_other_session_cannot_confirm_and_nothing_leaks(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    calls, before = fake.calls, _leads(pg_server, app_db)
    foreign = _confirm(client, tokens["CUSTOMER_B"], p, _key())
    unknown = _confirm(client, tokens["CUSTOMER_B"], {**p, "pending_action_id": str(uuid.uuid4())}, _key())
    assert foreign.status_code == unknown.status_code == 404 and foreign.json() == unknown.json()
    assert "Asesoria" not in foreign.text and "luis" not in foreign.text.lower()
    assert fake.calls == calls and _leads(pg_server, app_db) == before
    assert _confirm(client, tokens["CUSTOMER_A"], p, _key()).status_code == 201


@pytest.mark.parametrize("key", [None, "", "has space", "x" * 129])
def test_missing_or_invalid_key_rejected_before_n8n(lapi, pg_server, app_db, key):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    assert _confirm(client, tokens["CUSTOMER_A"], p, key).status_code == 400
    assert fake.calls == 0 and _status(pg_server, app_db, p["pending_action_id"]) == "pending"


def test_expired_action_cannot_be_confirmed(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    with pg_server.connect(app_db["name"]) as conn:
        conn.execute("UPDATE pending_lead_actions SET expires_at = now() - interval '1 second' WHERE id = %s",
                     (p["pending_action_id"],))
    r = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert r.status_code == 409 and r.json()["code"] == "confirmation_invalid" and fake.calls == 0
    assert _status(pg_server, app_db, p["pending_action_id"]) == "expired"


# ================================ distributed failures ====================================

@pytest.mark.parametrize("mode", ["unreachable", "fail_500", "internal_unreachable"])
def test_failed_hop_never_reports_success_and_is_retryable(lapi, pg_server, app_db, monkeypatch, mode):
    client, tokens, fake = lapi
    p, key = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json(), _key()
    before = _leads(pg_server, app_db)
    if mode == "unreachable":
        monkeypatch.setattr(client.app.state, "settings",
                            load_settings({**app_db["env"], "N8N_LEAD_WEBHOOK_URL":
                                           f"http://127.0.0.1:{_free_port()}/webhook/nexo-lead-create"}))
    else:
        fake.mode = mode
    r = _confirm(client, tokens["CUSTOMER_A"], p, key)
    assert r.status_code == 503 and r.json()["code"] == "lead_not_confirmed"
    assert "id" not in r.json() and _leads(pg_server, app_db) == before
    assert _status(pg_server, app_db, p["pending_action_id"]) == "confirmed"  # NOT consumed: retryable
    # A different key cannot hijack an in-flight confirmation.
    other = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert other.status_code == 409 and other.json()["code"] == "confirmation_in_progress"
    # Automation back: the same key resumes and creates exactly one lead.
    monkeypatch.undo()
    for k, v in {**app_db["env"], "N8N_LEAD_WEBHOOK_URL": fake.url}.items():
        monkeypatch.setenv(k, v)
    client.app.state.settings = load_settings()
    fake.mode = "forward"
    ok = _confirm(client, tokens["CUSTOMER_A"], p, key)
    assert ok.status_code == 201 and ok.headers["Idempotency-Outcome"] == "created"
    assert _leads(pg_server, app_db) == before + 1


def test_committed_but_response_lost_recovers_same_lead(lapi, pg_server, app_db, caplog):
    client, tokens, fake = lapi
    p, key = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json(), _key()
    before = _leads(pg_server, app_db)
    fake.mode = "commit_then_drop"
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        r = _confirm(client, tokens["CUSTOMER_A"], p, key)
    assert r.status_code == 201 and r.headers["Idempotency-Outcome"] == "replay"
    assert _leads(pg_server, app_db) == before + 1
    confirm_event = [json.loads(x.getMessage()) for x in caplog.records if x.name == "nexo.audit"
                     and json.loads(x.getMessage()).get("action") == "lead_confirm"][-1]
    assert confirm_event["confirmation_result"] == "recovered_after_dispatch" and confirm_event["n8n_status"] is None
    fake.mode = "forward"
    again = _confirm(client, tokens["CUSTOMER_A"], p, key)
    assert again.json()["id"] == r.json()["id"] and _leads(pg_server, app_db) == before + 1


def test_duplicate_workflow_delivery_creates_one_lead(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    before = _leads(pg_server, app_db)
    fake.mode = "duplicate"
    r = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert r.status_code == 201 and _leads(pg_server, app_db) == before + 1


def test_tampered_payload_is_refused_end_to_end(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    before = _leads(pg_server, app_db)
    fake.mode = "tamper"
    r = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert r.status_code == 502 and r.json()["code"] == "workflow_rejected"
    assert r.json()["upstream_code"] == "payload_mismatch" and _leads(pg_server, app_db) == before


def test_workflow_success_without_persisted_lead_is_not_success(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    before = _leads(pg_server, app_db)
    fake.mode = "success_without_write"
    r = _confirm(client, tokens["CUSTOMER_A"], p, _key())
    assert r.status_code == 502 and r.json()["code"] == "workflow_inconsistent"
    assert _leads(pg_server, app_db) == before


def test_database_failure_in_lead_write_rolls_back_and_is_retryable(lapi, pg_server, app_db):
    client, tokens, fake = lapi
    p, key = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json(), _key()
    before = _leads(pg_server, app_db)
    with pg_server.connect(app_db["name"]) as conn:
        conn.execute("CREATE OR REPLACE FUNCTION fail_lead() RETURNS trigger LANGUAGE plpgsql AS"
                     " $$ BEGIN RAISE EXCEPTION 'simulated database failure'; END; $$")
        conn.execute("DROP TRIGGER IF EXISTS fail_lead ON leads")
        conn.execute("CREATE TRIGGER fail_lead AFTER INSERT ON leads FOR EACH ROW EXECUTE FUNCTION fail_lead()")
    try:
        r = _confirm(client, tokens["CUSTOMER_A"], p, key)
        assert r.status_code == 503 and _leads(pg_server, app_db) == before
        assert _status(pg_server, app_db, p["pending_action_id"]) == "confirmed"
    finally:
        with pg_server.connect(app_db["name"]) as conn:
            conn.execute("DROP TRIGGER IF EXISTS fail_lead ON leads")
            conn.execute("DROP FUNCTION IF EXISTS fail_lead()")
    ok = _confirm(client, tokens["CUSTOMER_A"], p, key)
    assert ok.status_code == 201 and _leads(pg_server, app_db) == before + 1


def test_concurrent_workflow_deliveries_create_one_lead(lapi, pg_server, app_db):
    client, tokens, _ = lapi
    p, key = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json(), _key()
    with connect(client.app.state.settings, autocommit=True) as conn:  # confirm without dispatching
        assert leads.begin_confirm(conn, "CUSTOMER_A", uuid.UUID(p["pending_action_id"]), p["payload_hash"], key).envelope
    before, results, barrier = _leads(pg_server, app_db), [None] * 6, threading.Barrier(6)

    def worker(i):
        with connect(client.app.state.settings, autocommit=True) as conn:
            barrier.wait()
            results[i] = leads.internal_create(conn, uuid.UUID(p["pending_action_id"]), p["payload_hash"],
                                               DRAFT, key, f"race-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert not any(t.is_alive() for t in threads) and None not in results
    assert sorted(r.idempotency_outcome for r in results) == ["created"] + ["replay"] * 5
    assert len({r.body["id"] for r in results}) == 1 and _leads(pg_server, app_db) == before + 1


# ================================ bypass prevention =======================================

def _confirmed_action(client, tokens):
    """A prepared AND confirmed action (dispatch suppressed), the strongest target for a bypass attempt."""
    p, key = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json(), _key()
    with connect(client.app.state.settings, autocommit=True) as conn:
        leads.begin_confirm(conn, "CUSTOMER_A", uuid.UUID(p["pending_action_id"]), p["payload_hash"], key)
    return p, key


def _internal(client, auth_token, p, key, lead=None, payload_hash=None):
    headers = {"Idempotency-Key": key, **({"Authorization": f"Bearer {auth_token}"} if auth_token else {})}
    return client.post("/internal/leads", headers=headers, json={
        "pending_action_id": p["pending_action_id"], "payload_hash": payload_hash or p["payload_hash"],
        "lead": lead or DRAFT, "workflow_execution_id": "direct-attempt"})


@pytest.mark.parametrize("who", ["none", "customer_a", "customer_b", "random"])
def test_private_write_rejects_anything_but_the_service_credential(lapi, pg_server, app_db, who):
    client, tokens, _ = lapi
    p, key = _confirmed_action(client, tokens)
    token = {"none": None, "customer_a": tokens["CUSTOMER_A"], "customer_b": tokens["CUSTOMER_B"],
             "random": "x" * 43}[who]
    before = _leads(pg_server, app_db)
    r = _internal(client, token, p, key)
    assert r.status_code == 401 and _leads(pg_server, app_db) == before


def test_service_credential_cannot_create_unconfirmed_or_altered_leads(lapi, pg_server, app_db):
    client, tokens, _ = lapi
    svc = app_db["service_token"]
    before = _leads(pg_server, app_db)
    pending = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    r = _internal(client, svc, pending, _key())
    assert r.status_code == 409 and r.json()["code"] == "action_not_confirmed"  # confirmation cannot be skipped
    p, key = _confirmed_action(client, tokens)
    assert _internal(client, svc, p, _key()).json()["code"] == "idempotency_key_conflict"
    assert _internal(client, svc, p, key, lead={**DRAFT, "need": "Altered"}).json()["code"] == "payload_mismatch"
    r = _internal(client, svc, {**p, "pending_action_id": str(uuid.uuid4())}, key)
    assert r.status_code == 404
    assert client.post("/internal/leads", headers={"Authorization": f"Bearer {svc}"},
                       json={"pending_action_id": p["pending_action_id"], "payload_hash": p["payload_hash"],
                             "lead": DRAFT, "workflow_execution_id": "x"}).status_code == 400  # no key
    assert _leads(pg_server, app_db) == before
    ok = _internal(client, svc, p, key)  # the legitimate n8n call
    assert ok.status_code == 201 and _leads(pg_server, app_db) == before + 1


def test_no_public_direct_lead_route(lapi, pg_server, app_db):
    client, tokens, _ = lapi
    before = _leads(pg_server, app_db)
    for path in ("/leads", "/lead", "/leads/create"):
        r = client.post(path, json=DRAFT, headers={**bearer(tokens["CUSTOMER_A"]), "Idempotency-Key": _key()})
        assert r.status_code in (404, 405)
    assert _leads(pg_server, app_db) == before


def test_only_the_private_write_path_inserts_leads():
    app_dir = ROOT / "src" / "backend" / "app"
    inserting = [f.name for f in app_dir.rglob("*.py") if "INSERT INTO leads" in f.read_text(encoding="utf-8")]
    assert inserting == ["leads.py"]
    source = (app_dir / "leads.py").read_text(encoding="utf-8")
    functions = re.split(r"\ndef ", source)
    assert [f.split("(")[0] for f in functions if "INSERT INTO leads" in f] == ["internal_create"]
    main = (app_dir / "main.py").read_text(encoding="utf-8")
    assert main.count("leads.internal_create(") == 1
    route = main.split('@app.post("/internal/leads")')[1].split("\n@app.")[0]
    assert 'Depends(require_service("lead_write"))' in route and "leads.internal_create(" in route
    confirm_route = main.split('@app.post("/leads/confirm")')[1].split("\n@app.")[0]
    assert "internal_create" not in confirm_route and "INSERT" not in confirm_route


def test_database_enforces_one_lead_per_action_and_valid_email(lapi, pg_server, app_db):
    client, tokens, _ = lapi
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=_conv()).json()
    lead = _confirm(client, tokens["CUSTOMER_A"], p, _key()).json()
    with pg_server.connect(app_db["name"]) as conn:
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute("INSERT INTO leads (company_name, contact_name, contact_email, need, requested_by_customer_id,"
                         " source_action_id, workflow_execution_id) VALUES ('x','x','a@b.test','x','CUSTOMER_A',%s,'x')",
                         (p["pending_action_id"],))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE leads SET contact_email = 'not-an-email' WHERE id = %s", (lead["id"],))


# ================================ traceability ============================================

def test_confirm_and_private_write_are_correlated_without_secrets(lapi, app_db, caplog):
    client, tokens, _ = lapi
    conv, key = _conv(), _key()
    p = _prepare(client, tokens["CUSTOMER_A"], conversation=conv).json()
    with caplog.at_level(logging.DEBUG):
        lead = _confirm(client, tokens["CUSTOMER_A"], p, key,
                        **{"X-Request-ID": "req-lead-1", "X-Conversation-ID": conv}).json()
    events = [json.loads(r.getMessage()) for r in caplog.records if r.name == "nexo.audit"]
    write = next(e for e in events if e.get("action") == "lead_write")
    confirm = next(e for e in events if e.get("action") == "lead_confirm")
    # Same request id on both sides of the workflow hop: the write came through the workflow call.
    assert write["request_id"] == confirm["request_id"] == "req-lead-1"
    assert write["service"] == "n8n-lead-writer" and write["idempotency"] == "created"
    assert write["lead_id"] == confirm["lead_id"] == lead["id"]
    assert write["workflow_execution_id"] == confirm["workflow_execution_id"] == lead["workflow_execution_id"]
    assert confirm["conversation_id"] == conv and confirm["n8n_status"] == 201
    assert confirm["idempotency_key_fp"] == write["idempotency_key_fp"] == hashlib.sha256(key.encode()).hexdigest()[:12]
    text = caplog.text
    for secret in (tokens["CUSTOMER_A"], tokens["CUSTOMER_B"], app_db["service_token"],
                   app_db["env"]["POSTGRES_PASSWORD"], key):
        assert secret not in text
    for personal in (NORMALIZED["contact_email"], NORMALIZED["need"], NORMALIZED["company_name"]):
        assert personal not in text  # contact payload is persisted, not logged
    assert "Bearer " not in text
