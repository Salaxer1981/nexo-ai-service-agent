"""AGENT-01BF2 regressions (REAL PostgreSQL 17 + pgvector; TEST-ONLY scripted model; FakeN8n = TEST stand-in, NOT n8n).

AGENT01BF1-01: a model proposal that started from a pending action is published only if the AUTHORITATIVE action is
               still pending (customer AND conversation AND action); otherwise it is rejected and chat state is
               synchronized; a recovery pointer is never replaced.
AGENT01BF1-02: CANCELAR proves conversation membership BEFORE any cancel mutation.
Races run deterministically INSIDE the scripted model call, i.e. exactly while an older interpretation is in flight.
"""
import uuid
from uuid import UUID

import psycopg
from fastapi.testclient import TestClient

from app import chat_actions, leads, ticket_actions
from conftest import bearer
from llm_fakes import intent
from test_chat_actions import LEAD, NORMAL, conv, counts, cx, n8n, prepared_lead, prepared_ticket, q, say  # noqa: F401

CHANGED_LEAD = {"need": "Automatizar consultas y además la facturación."}


def action_of(pg_server, app_db, table, c):
    rows = q(pg_server, app_db, f"SELECT id, payload_hash, status FROM {table} WHERE conversation_id = %s ORDER BY created_at", c)
    return rows


def chat_state(pg_server, app_db, c):
    return q(pg_server, app_db, "SELECT action_kind, action_id, action_status, revision FROM chat_conversations WHERE conversation_id = %s", c)[0]


def failing_completed_save(real_save):
    def save(conn, customer_id, conversation_id, st):
        if st.action_status == "completed":  # the business commit happened; the chat sync is what gets lost
            raise psycopg.OperationalError("connection lost before the chat state was synchronized")
        return real_save(conn, customer_id, conversation_id, st)
    return save


# ===================================== T1: ticket committed, response lost, stale proposal ================

def test_t1_ticket_commit_then_lost_response_vs_stale_model_proposal(cx, pg_server, app_db, monkeypatch):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_ticket(client, a, c, use, NORMAL)
    (a_id, _, _), = action_of(pg_server, app_db, "pending_ticket_actions", c)
    before, real_save, inner = counts(pg_server, app_db), chat_actions._save, {}

    def model_meanwhile(system, user):  # the correction turn read state N and is now waiting on the model...
        monkeypatch.setattr(chat_actions, "_save", failing_completed_save(real_save))
        inner["confirm"] = say(TestClient(app), a, c, "CONFIRMAR")  # ...the user confirms A; ticket commits; sync lost
        monkeypatch.setattr(chat_actions, "_save", real_save)
        return intent("create_ticket", ticket={"priority": "critical"})
    use(model_meanwhile)
    body = say(client, a, c, "En realidad es crítica").json()
    assert inner["confirm"].status_code == 503 and inner["confirm"].json()["code"] == "action_not_confirmed"
    (ticket_id, ref), = q(pg_server, app_db, "SELECT id, reference FROM tickets WHERE source_action_id = %s", a_id)
    assert body["status"] == "already_completed" and body["result"] == {"kind": "ticket", "id": str(ticket_id), "reference": ref}
    assert [r[2] for r in action_of(pg_server, app_db, "pending_ticket_actions", c)] == ["consumed"]  # NO action B
    kind, pointer, status, _ = chat_state(pg_server, app_db, c)
    assert (kind, pointer, status) == ("ticket", a_id, "completed")  # recovered, pointer to A preserved
    use()
    again = say(client, a, c, "CONFIRMAR").json()  # retry still returns A
    assert again["status"] == "ticket_created" and again["result"]["id"] == str(ticket_id)
    assert counts(pg_server, app_db)["tickets"] == before["tickets"] + 1


# ===================================== T2: lead confirmed, n8n fails, stale proposal ======================

def test_t2_lead_confirmed_and_n8n_failure_vs_stale_model_proposal(cx, pg_server, app_db, n8n):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_lead(client, a, c, use)
    (a_id, _, _), = action_of(pg_server, app_db, "pending_lead_actions", c)
    before, inner = counts(pg_server, app_db), {}

    def model_meanwhile(system, user):
        n8n.mode = "fail_500"  # TEST-ONLY FakeN8n: the workflow fails after the action became 'confirmed'
        inner["confirm"] = say(TestClient(app), a, c, "CONFIRMAR")
        return intent("create_lead", lead=CHANGED_LEAD)
    use(model_meanwhile)
    body = say(client, a, c, "Añadid también la facturación").json()
    assert inner["confirm"].status_code == 503 and inner["confirm"].json()["code"] == "lead_not_confirmed"
    assert body["status"] == "action_in_progress" and body["next_step"]["awaiting"] == "CONFIRMAR"
    assert [(r[0], r[2]) for r in action_of(pg_server, app_db, "pending_lead_actions", c)] == [(a_id, "confirmed")]  # no B
    assert chat_state(pg_server, app_db, c)[:3] == ("lead", a_id, "pending")  # A stays the retry/recovery pointer
    assert counts(pg_server, app_db)["leads"] == before["leads"]
    n8n.mode = "forward"
    use()
    done = say(client, a, c, "CONFIRMAR").json()  # recovery through the existing APP-03B retry path
    assert done["status"] == "lead_created"
    assert say(client, a, c, "CONFIRMAR").json()["result"]["id"] == done["result"]["id"]
    assert counts(pg_server, app_db)["leads"] == before["leads"] + 1
    assert len(action_of(pg_server, app_db, "pending_lead_actions", c)) == 1  # no second lead action ever existed


def test_in_flight_lead_pointer_is_never_replaced_even_with_a_current_basis(cx, pg_server, app_db, n8n):
    """Section 12: once the action left 'pending', no proposal (stale OR current revision) may replace its pointer."""
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_lead(client, a, c, use)
    (a_id, _, _), = action_of(pg_server, app_db, "pending_lead_actions", c)
    n8n.mode = "fail_500"
    use()
    assert say(client, a, c, "CONFIRMAR").status_code == 503
    with pg_server.connect(app_db["name"]) as conn:  # simulate the lost chat sync on top: chat still says 'pending'
        conn.execute("UPDATE chat_conversations SET action_status = 'pending' WHERE conversation_id = %s", (c,))
    use(intent("create_lead", lead=CHANGED_LEAD))
    body = say(client, a, c, "Cambia la necesidad").json()
    assert body["status"] == "action_in_progress"
    assert chat_state(pg_server, app_db, c)[1] == a_id and len(action_of(pg_server, app_db, "pending_lead_actions", c)) == 1
    n8n.mode = "forward"


# ===================================== T3: plain API completion during interpretation =====================

def test_t3_plain_api_ticket_completion_vs_stale_model_proposal(cx, pg_server, app_db):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_ticket(client, a, c, use, NORMAL)
    (a_id, a_hash, _), = action_of(pg_server, app_db, "pending_ticket_actions", c)
    before, inner = counts(pg_server, app_db), {}

    def model_meanwhile(system, user):
        inner["api"] = TestClient(app).post("/tickets/confirm", json={"pending_action_id": str(a_id), "payload_hash": a_hash},
                                            headers={**bearer(a), "Idempotency-Key": "api-" + uuid.uuid4().hex})
        return intent("create_ticket", ticket={"priority": "critical"})
    use(model_meanwhile)
    rev_before = chat_state(pg_server, app_db, c)[3]
    body = say(client, a, c, "En realidad es crítica").json()
    assert inner["api"].status_code == 201  # the API path does not touch chat state: revision alone can't see it
    assert body["status"] == "already_completed" and body["result"]["id"] == inner["api"].json()["id"]
    assert [r[2] for r in action_of(pg_server, app_db, "pending_ticket_actions", c)] == ["consumed"]
    kind, pointer, status, rev_after = chat_state(pg_server, app_db, c)
    assert (kind, pointer, status) == ("ticket", a_id, "completed") and rev_after == rev_before + 1  # synchronized
    assert counts(pg_server, app_db)["tickets"] == before["tickets"] + 1


def test_t3_plain_api_lead_completion_vs_stale_model_proposal(cx, pg_server, app_db, n8n):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_lead(client, a, c, use)
    (a_id, a_hash, _), = action_of(pg_server, app_db, "pending_lead_actions", c)
    before, inner = counts(pg_server, app_db), {}

    def model_meanwhile(system, user):
        inner["api"] = TestClient(app).post("/leads/confirm", json={"pending_action_id": str(a_id), "payload_hash": a_hash},
                                            headers={**bearer(a), "Idempotency-Key": "api-" + uuid.uuid4().hex,
                                                     "X-Conversation-ID": c})
        return intent("create_lead", lead=CHANGED_LEAD)
    use(model_meanwhile)
    body = say(client, a, c, "Añadid la facturación").json()
    assert inner["api"].status_code == 201
    assert body["status"] == "already_completed" and body["result"] == {"kind": "lead", "id": inner["api"].json()["id"]}
    assert len(action_of(pg_server, app_db, "pending_lead_actions", c)) == 1
    assert chat_state(pg_server, app_db, c)[:3] == ("lead", a_id, "completed")
    assert counts(pg_server, app_db)["leads"] == before["leads"] + 1


# ===================================== section 7: revision invalidated before business mutation ===========

def test_failed_confirm_still_invalidates_the_revision(cx, pg_server, app_db, monkeypatch):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_ticket(client, a, c, use, NORMAL)
    rev = chat_state(pg_server, app_db, c)[3]
    monkeypatch.setattr(chat_actions, "_save", failing_completed_save(chat_actions._save))
    use()
    assert say(client, a, c, "CONFIRMAR").status_code == 503
    assert chat_state(pg_server, app_db, c)[2:] == ("pending", rev + 1)  # sync lost, but the revision already moved


# ===================================== T4/T5: cross-conversation pointer + CANCELAR ========================

def _corrupt_pointer(pg_server, app_db, kind, table, c_x, c_y):
    (x_id, x_hash, _), = action_of(pg_server, app_db, table, c_x)
    with pg_server.connect(app_db["name"]) as conn:
        chat_actions._save(conn, "CUSTOMER_A", c_y, chat_actions.State(action_kind=kind, action_id=x_id,
                           action_payload_hash=x_hash, action_status="pending"))
    return x_id


def _spy(monkeypatch, module):
    calls, real = [], module.cancel

    def spy(conn, customer_id, action_id):
        calls.append(action_id)
        return real(conn, customer_id, action_id)
    monkeypatch.setattr(module, "cancel", spy)
    return calls


def test_t4_cancel_with_cross_conversation_ticket_pointer_mutates_nothing(cx, pg_server, app_db, monkeypatch):
    client, tokens, use = cx
    a, c_x, c_y = tokens["CUSTOMER_A"], conv(), conv()
    prepared_ticket(client, a, c_x, use, NORMAL)
    x_id = _corrupt_pointer(pg_server, app_db, "ticket", "pending_ticket_actions", c_x, c_y)
    calls = _spy(monkeypatch, ticket_actions)
    use()
    body = say(client, a, c_y, "CANCELAR").json()
    assert body["status"] == "not_pending" and "no he cancelado" in body["answer"]
    assert calls == [] and q(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE id = %s", x_id) == [("pending",)]
    assert say(client, a, c_x, "CONFIRMAR").json()["status"] == "ticket_created"  # X intact and still usable in X


def test_t5_cancel_with_cross_conversation_lead_pointer_mutates_nothing(cx, pg_server, app_db, monkeypatch):
    client, tokens, use = cx
    a, c_x, c_y = tokens["CUSTOMER_A"], conv(), conv()
    prepared_lead(client, a, c_x, use)
    x_id = _corrupt_pointer(pg_server, app_db, "lead", "pending_lead_actions", c_x, c_y)
    calls = _spy(monkeypatch, leads)
    use()
    body = say(client, a, c_y, "CANCELAR").json()
    assert body["status"] == "not_pending"
    assert calls == [] and q(pg_server, app_db, "SELECT status FROM pending_lead_actions WHERE id = %s", x_id) == [("pending",)]
