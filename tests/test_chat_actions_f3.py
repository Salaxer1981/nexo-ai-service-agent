"""AGENT-01BF3 regressions (REAL PostgreSQL 17 + pgvector; TEST-ONLY scripted model; FakeN8n = TEST stand-in, NOT n8n).

AGENT01BF2-01: the authoritative check of the pointed action and the re-prepare/publication are ONE transaction with
               the action row locked (SELECT ... FOR UPDATE); a concurrent confirmation WAITS (observed in pg_locks).
AGENT01BF2-02: CANCELAR validates the pointer before ANY cancel mutation (including other pending actions).
"""
import threading
import time
import uuid

import psycopg
from fastapi.testclient import TestClient

from app import chat_actions, leads, ticket_actions
from conftest import bearer
from llm_fakes import intent
from test_chat_actions import LEAD, NORMAL, conv, counts, cx, n8n, prepared_lead, prepared_ticket, q, say  # noqa: F401
from test_chat_actions_f2 import CHANGED_LEAD, action_of, chat_state

CORRECTION = {"ticket": ("create_ticket", {"ticket": {"priority": "critical"}}, "En realidad es crítica"),
              "lead": ("create_lead", {"lead": CHANGED_LEAD}, "Añadid la facturación")}


def someone_waits(observer, deadline_s=20) -> bool:
    """True as soon as any session waits on a lock (no timing assumption about WHEN; bounded so a test can't hang)."""
    deadline = time.monotonic() + deadline_s
    while time.monotonic() < deadline:
        if observer.execute("SELECT count(*) FROM pg_locks WHERE NOT granted").fetchone()[0]:
            return True
        time.sleep(0.02)
    return False


def correction(use, kind):
    name, fields, text = CORRECTION[kind]
    use(intent(name, **fields))
    return text


# ===================================== AGENT01BF2-01: proposal holds A's row lock ==========================

def _proposal_wins(kind, cx, pg_server, app_db, monkeypatch, api_path, body_of):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    # A must DIFFER from the correction (normal -> critical), otherwise the agent correctly takes the "unchanged" path.
    prepared_ticket(client, a, c, use, NORMAL) if kind == "ticket" else prepared_lead(client, a, c, use)
    table = "pending_ticket_actions" if kind == "ticket" else "pending_lead_actions"
    (a_id, a_hash, _), = action_of(pg_server, app_db, table, c)
    real_reconcile, seen = chat_actions.reconcile, {}

    def reconcile_then_concurrent_confirm(conn, customer_id, conversation_id, st, lock=False):
        # (works against code with or without the row lock, so the same test can show the old TOCTOU)
        result = (real_reconcile(conn, customer_id, conversation_id, st, lock=lock) if lock
                  else real_reconcile(conn, customer_id, conversation_id, st))
        if result[0] == "pending" and "api" not in seen:  # A is row-locked by THIS (still open) transaction
            def api():
                seen["api"] = TestClient(app).post(api_path, json=body_of(a_id, a_hash),
                                                   headers={**bearer(a), "Idempotency-Key": "api-" + uuid.uuid4().hex,
                                                            "X-Conversation-ID": c})
            seen["thread"] = threading.Thread(target=api)
            seen["thread"].start()
            with pg_server.connect(app_db["name"]) as observer:
                seen["api_waited"] = someone_waits(observer)  # the plain API confirmation is blocked on A's row lock
        return result
    monkeypatch.setattr(chat_actions, "reconcile", reconcile_then_concurrent_confirm)
    text = correction(use, kind)
    body = say(client, a, c, text).json()
    seen["thread"].join(60)
    return body, seen, a_id, c


def test_ticket_proposal_wins_and_api_confirm_waits_then_fails_safely(cx, pg_server, app_db, monkeypatch):
    before = counts(pg_server, app_db)
    body, seen, a_id, c = _proposal_wins("ticket", cx, pg_server, app_db, monkeypatch, "/tickets/confirm",
                                         lambda i, h: {"pending_action_id": str(i), "payload_hash": h})
    assert seen["api_waited"] is True
    assert body["status"] == "awaiting_confirmation" and body["pending_action"]["summary"]["priority"] == "critical"
    assert seen["api"].status_code == 409 and seen["api"].json()["code"] == "confirmation_invalid"  # A superseded first
    statuses = [r[2] for r in action_of(pg_server, app_db, "pending_ticket_actions", c)]
    assert statuses == ["superseded", "pending"]                        # never "A consumed AND B pending"
    assert counts(pg_server, app_db)["tickets"] == before["tickets"]


def test_lead_proposal_wins_and_api_confirm_waits_then_fails_safely(cx, pg_server, app_db, n8n, monkeypatch):
    before = counts(pg_server, app_db)
    body, seen, a_id, c = _proposal_wins("lead", cx, pg_server, app_db, monkeypatch, "/leads/confirm",
                                         lambda i, h: {"pending_action_id": str(i), "payload_hash": h})
    assert seen["api_waited"] is True
    assert body["status"] == "awaiting_confirmation" and body["pending_action"]["summary"]["need"] == CHANGED_LEAD["need"]
    assert seen["api"].status_code == 409 and seen["api"].json()["code"] == "confirmation_invalid"
    assert [r[2] for r in action_of(pg_server, app_db, "pending_lead_actions", c)] == ["superseded", "pending"]
    assert n8n.calls == 0 and counts(pg_server, app_db)["leads"] == before["leads"]  # the workflow was never reached


# ===================================== AGENT01BF2-01: confirmation holds A's row lock ======================

def _confirm_wins(kind, cx, pg_server, app_db, winner):
    """`winner(conn, a_id, a_hash, c)` runs the REAL service on A inside an uncommitted transaction (A row-locked)."""
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_ticket(client, a, c, use, NORMAL) if kind == "ticket" else prepared_lead(client, a, c, use)
    table = "pending_ticket_actions" if kind == "ticket" else "pending_lead_actions"
    (a_id, a_hash, _), = action_of(pg_server, app_db, table, c)
    text, out = correction(use, kind), {}
    with pg_server.connect(app_db["name"]) as holder, pg_server.connect(app_db["name"]) as observer:
        holder.autocommit = False
        holder.execute("SELECT 1")             # open the transaction; the service's own block becomes a savepoint
        winner(holder, a_id, a_hash, c)        # consumes/confirms A; row lock held, NOT committed yet
        t = threading.Thread(target=lambda: out.update(r=say(TestClient(app), a, c, text).json()))
        t.start()                              # model proposal computed from "A pending" (uncommitted change invisible)
        waited = someone_waits(observer)       # the proposal is blocked on A's row lock
        holder.commit()
        t.join(60)
    return out["r"], waited, a_id, c, client, a, use


def test_ticket_confirm_wins_and_stale_proposal_is_rejected(cx, pg_server, app_db):
    before = counts(pg_server, app_db)
    body, waited, a_id, c, client, a, use = _confirm_wins("ticket", cx, pg_server, app_db, lambda conn, i, h, c: ticket_actions.confirm(
        conn, "CUSTOMER_A", i, h, "api-" + uuid.uuid4().hex))
    assert waited is True
    assert body["status"] == "already_completed" and body["result"]["kind"] == "ticket"
    assert [r[2] for r in action_of(pg_server, app_db, "pending_ticket_actions", c)] == ["consumed"]  # NO B
    assert chat_state(pg_server, app_db, c)[:3] == ("ticket", a_id, "completed")
    assert counts(pg_server, app_db)["tickets"] == before["tickets"] + 1


def test_lead_confirm_wins_keeps_the_in_flight_pointer_and_recovers_through_n8n(cx, pg_server, app_db, n8n):
    before = counts(pg_server, app_db)
    body, waited, a_id, c, client, a, use = _confirm_wins("lead", cx, pg_server, app_db, lambda conn, i, h, c: leads.begin_confirm(
        conn, "CUSTOMER_A", i, h, chat_actions.confirmation_key(c, i)))  # the chat's confirm got A first; its n8n hop never ran
    assert waited is True
    assert body["status"] == "action_in_progress"
    assert [(r[0], r[2]) for r in action_of(pg_server, app_db, "pending_lead_actions", c)] == [(a_id, "confirmed")]  # NO B
    assert chat_state(pg_server, app_db, c)[:3] == ("lead", a_id, "pending")  # recovery pointer kept
    use()
    done = say(client, a, c, "CONFIRMAR").json()  # retry: same key -> redispatch through the (TEST) workflow
    assert done["status"] == "lead_created" and n8n.calls >= 1
    assert counts(pg_server, app_db)["leads"] == before["leads"] + 1


# ===================================== lock order: no deadlock with the API prepare path ===================

def test_concurrent_chat_reprepare_and_api_prepare_never_deadlock(cx, pg_server, app_db):
    from app.main import app
    client, tokens, use = cx
    a = tokens["CUSTOMER_A"]
    for i in range(5):
        c = conv()
        prepared_ticket(client, a, c, use, NORMAL)
        use(intent("create_ticket", ticket={"priority": "critical"}))
        barrier, out = threading.Barrier(2), {}

        def chat():
            barrier.wait(); out["chat"] = say(TestClient(app), a, c, "crítica")

        def api():
            barrier.wait()
            out["api"] = TestClient(app).post("/tickets/prepare", json={**NORMAL, "subject": f"API {i}"},
                                              headers={**bearer(a), "X-Conversation-ID": c})
        ts = [threading.Thread(target=chat), threading.Thread(target=api)]
        [t.start() for t in ts]; [t.join(60) for t in ts]
        assert out["chat"].status_code == 200 and out["api"].status_code == 201, (out["chat"].text, out["api"].text)
        assert q(pg_server, app_db, "SELECT count(*) FROM pending_ticket_actions WHERE conversation_id = %s AND status = 'pending'", c) == [(1,)]


# ===================================== AGENT01BF2-02: X/Z cancellation order ===============================

def test_cancel_with_corrupt_pointer_and_another_valid_pending_action_mutates_nothing(cx, pg_server, app_db, monkeypatch):
    client, tokens, use = cx
    a, c_x, c_y = tokens["CUSTOMER_A"], conv(), conv()
    prepared_ticket(client, a, c_x, use, NORMAL)                                   # X belongs to conversation X
    r = client.post("/tickets/prepare", json={**NORMAL, "subject": "Z"}, headers={**bearer(a), "X-Conversation-ID": c_y})
    assert r.status_code == 201                                                   # Z: a valid pending action of Y
    (x_id, x_hash, _), = action_of(pg_server, app_db, "pending_ticket_actions", c_x)
    (z_id, _, _), = action_of(pg_server, app_db, "pending_ticket_actions", c_y)
    with pg_server.connect(app_db["name"]) as conn:                               # Y's pointer corrupted to X
        chat_actions._save(conn, "CUSTOMER_A", c_y, chat_actions.State(action_kind="ticket", action_id=x_id,
                           action_payload_hash=x_hash, action_status="pending"))
    calls, real = [], ticket_actions.cancel
    monkeypatch.setattr(ticket_actions, "cancel", lambda conn, cust, aid: calls.append(aid) or real(conn, cust, aid))
    use()
    body = say(client, a, c_y, "CANCELAR").json()
    assert body["status"] == "not_pending" and "no he cancelado ni ejecutado nada" in body["answer"]
    assert calls == []                                                             # ZERO cancel-service calls
    assert q(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE id = %s", x_id) == [("pending",)]
    assert q(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE id = %s", z_id) == [("pending",)]


def test_cancel_advances_revision_before_mutation_even_if_chat_sync_fails(cx, pg_server, app_db, monkeypatch):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepared_ticket(client, a, c, use, NORMAL)
    rev = chat_state(pg_server, app_db, c)[3]
    real_save = chat_actions._save

    def failing(conn, cust, conv_id, st):
        if st.action_status == "cancelled":
            raise psycopg.OperationalError("connection lost after the cancel mutation")
        return real_save(conn, cust, conv_id, st)
    monkeypatch.setattr(chat_actions, "_save", failing)
    use()
    assert say(client, a, c, "CANCELAR").status_code == 503
    assert [r[2] for r in action_of(pg_server, app_db, "pending_ticket_actions", c)] == ["cancelled"]
    assert chat_state(pg_server, app_db, c)[2:] == ("pending", rev + 1)  # chat sync lost, revision already advanced
