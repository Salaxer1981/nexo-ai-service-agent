"""AGENT-01BF1 regressions (REAL PostgreSQL 17 + pgvector; TEST-ONLY scripted model; FakeN8n = TEST stand-in, NOT n8n).

AGENT01B-01: CONFIRMAR executes ONLY the exact prepared version the client presented (confirmation_token), re-checked
             under the conversation lock; a re-prepared / unseen newer version never executes.
AGENT01B-02: CANCELAR answers from the AUTHORITATIVE action state after the cancel attempt, never from cached state.
Races are made deterministic by holding the conversation advisory lock (observed in pg_locks) or by hooking the exact
point between "state loaded" and "service called"; no timing sleeps decide outcomes.
"""
import time
import threading
import uuid
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app import chat_actions, leads, ticket_actions
from conftest import bearer
from llm_fakes import intent
from test_chat_actions import (CRITICAL, LEAD, NORMAL, SHOWN_TOKEN, conv, counts, cx, n8n, prepared_lead,  # noqa: F401
                               prepared_ticket, q, say)

KINDS = {"ticket": {"fields": NORMAL, "changed": {**NORMAL, "priority": "critical"}, "table": "pending_ticket_actions",
                    "service": ticket_actions, "objects": "tickets"},
         "lead": {"fields": LEAD, "changed": {**LEAD, "need": "Automatizar consultas y además la facturación."},
                  "table": "pending_lead_actions", "service": leads, "objects": "leads"}}


def prepare(kind, client, token, c, use):
    return (prepared_ticket if kind == "ticket" else prepared_lead)(client, token, c, use, KINDS[kind]["fields"])


def wait_until_waiting(observer, lock_key, n=1):
    key = lock_key & 0xFFFFFFFFFFFFFFFF
    deadline = time.monotonic() + 30
    while observer.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted AND classid = %s::bigint::oid"
                           " AND objid = %s::bigint::oid", (key >> 32, key & 0xFFFFFFFF)).fetchone()[0] < n:
        assert time.monotonic() < deadline, "the turn never waited on the conversation lock"
        time.sleep(0.02)


def concurrent_reprepare(conn, kind, customer, c):
    """Exactly what propose() does for a correction turn that got the conversation lock first: prepare B through the
    existing service (superseding A) and point the conversation at B."""
    prepared = KINDS[kind]["service"].prepare(conn, customer, KINDS[kind]["changed"], c)
    b_id = UUID(prepared["pending_action_id"])
    chat_actions._save(conn, customer, c, chat_actions.State(action_kind=kind, action_id=b_id,
                       action_payload_hash=prepared["payload_hash"], action_status="pending"))
    return b_id, chat_actions.confirmation_token(b_id, prepared["payload_hash"])


# ===================================== AGENT01B-01: exact approved version =================================

@pytest.mark.parametrize("kind", ["ticket", "lead"])
def test_reprepare_during_confirm_never_executes_the_newer_version(cx, pg_server, app_db, n8n, kind):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    shown_a = prepare(kind, client, a, c, use)["pending_action"]["confirmation_token"]
    before = counts(pg_server, app_db)
    lock = chat_actions._lock_key("CUSTOMER_A", c)
    result = {}
    use()
    with pg_server.connect(app_db["name"]) as holder, pg_server.connect(app_db["name"]) as observer:
        holder.execute("SELECT pg_advisory_lock(%s)", (lock,))
        worker = threading.Thread(target=lambda: result.update(
            r=say(TestClient(app), a, c, "CONFIRMAR", confirmation_token=shown_a).json()))
        try:
            worker.start()
            wait_until_waiting(observer, lock)                    # the CONFIRMAR for A is admitted and waiting
            b_id, token_b = concurrent_reprepare(holder, kind, "CUSTOMER_A", c)  # a correction turn re-prepares B
        finally:
            holder.execute("SELECT pg_advisory_unlock(%s)", (lock,))
        worker.join(60)
    r = result["r"]
    assert r["status"] == "confirmation_review_required" and "no he ejecutado nada" in r["answer"]
    assert r["pending_action"]["confirmation_token"] == token_b and r["pending_action"]["summary"] == KINDS[kind]["changed"]
    after = counts(pg_server, app_db)
    assert after[KINDS[kind]["objects"]] == before[KINDS[kind]["objects"]]       # neither B nor A was created
    assert q(pg_server, app_db, f"SELECT status FROM {KINDS[kind]['table']} WHERE id = %s", b_id) == [("pending",)]
    assert n8n.calls == 0
    # the user reviews B and confirms THAT version: now (and only now) B executes
    body = say(client, a, c, "CONFIRMAR", confirmation_token=token_b).json()
    assert body["status"] == ("ticket_created" if kind == "ticket" else "lead_created")
    assert counts(pg_server, app_db)[KINDS[kind]["objects"]] == before[KINDS[kind]["objects"]] + 1


@pytest.mark.parametrize("kind", ["ticket", "lead"])
def test_lost_reprepare_response_cannot_execute_the_unseen_version(cx, pg_server, app_db, n8n, kind):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    shown_a = prepare(kind, client, a, c, use)["pending_action"]["confirmation_token"]
    use(intent("create_ticket", ticket={"priority": "critical"}) if kind == "ticket"
        else intent("create_lead", lead={"need": KINDS[kind]["changed"]["need"]}))
    r = client.post("/chat", json={"message": "una corrección"}, headers={**bearer(a), "X-Conversation-ID": c})
    assert r.json()["status"] == "awaiting_confirmation"   # B prepared... but this response never reaches the user
    before = counts(pg_server, app_db)
    use()
    for presented in (shown_a, None):                     # the user (still looking at A) confirms; or a token-less client
        body = say(client, a, c, "CONFIRMAR", confirmation_token=presented).json()
        assert body["status"] == "confirmation_review_required" and body["model"] is None
        assert body["pending_action"]["summary"] == KINDS[kind]["changed"]  # B is SHOWN for review, not executed
    assert counts(pg_server, app_db) == before and n8n.calls == 0


def test_forged_or_foreign_tokens_execute_nothing(cx, pg_server, app_db):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    real = prepare("ticket", client, a, c, use)["pending_action"]["confirmation_token"]
    other_c = conv()
    other = prepare("ticket", client, a, other_c, use)["pending_action"]["confirmation_token"]
    before = counts(pg_server, app_db)
    use()
    for bad in ("0" * 16, other):                        # invented token; the token of another conversation's action
        assert say(client, a, c, "CONFIRMAR", confirmation_token=bad).json()["status"] == "confirmation_review_required"
    assert client.post("/chat", json={"message": "CONFIRMAR", "confirmation_token": "not-hex"},
                       headers={**bearer(a), "X-Conversation-ID": c}).status_code == 422
    assert say(client, tokens["CUSTOMER_B"], c, "CONFIRMAR", confirmation_token=real).json()["status"] == "nothing_pending"
    assert counts(pg_server, app_db) == before


def test_pointer_to_another_conversations_action_fails_closed(cx, pg_server, app_db):
    """Defense in depth: a conversation pointer is dereferenced only with customer AND conversation predicates."""
    client, tokens, use = cx
    a, c_x, c_y = tokens["CUSTOMER_A"], conv(), conv()
    prepare("ticket", client, a, c_x, use)
    (action_id, payload_hash), = q(pg_server, app_db, "SELECT id, payload_hash FROM pending_ticket_actions WHERE conversation_id = %s", c_x)
    with pg_server.connect(app_db["name"]) as conn:  # a corrupted / forged pointer in conversation Y to X's action
        chat_actions._save(conn, "CUSTOMER_A", c_y, chat_actions.State(action_kind="ticket", action_id=action_id,
                           action_payload_hash=payload_hash, action_status="pending"))
    before = counts(pg_server, app_db)
    use()
    body = say(client, a, c_y, "CONFIRMAR", confirmation_token=chat_actions.confirmation_token(action_id, payload_hash)).json()
    assert body["status"] == "confirmation_invalid" and counts(pg_server, app_db) == before
    assert q(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE id = %s", action_id) == [("pending",)]


# ===================================== AGENT01B-02: authoritative cancellation ============================

def test_api_confirm_wins_against_chat_cancel_ticket(cx, pg_server, app_db, monkeypatch):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("ticket", client, a, c, use)
    (aid, ahash), = q(pg_server, app_db, "SELECT id, payload_hash FROM pending_ticket_actions WHERE conversation_id = %s", c)
    before = counts(pg_server, app_db)
    real_cancel, api = ticket_actions.cancel, {}

    def cancel_after_api_confirm(conn, customer_id, action_id):
        # CANCELAR has loaded state "pending"; at exactly this point the plain API confirmation wins
        r = TestClient(app).post("/tickets/confirm", json={"pending_action_id": str(aid), "payload_hash": ahash},
                                 headers={**bearer(a), "Idempotency-Key": "api-" + uuid.uuid4().hex})
        api["r"] = r
        return real_cancel(conn, customer_id, action_id)
    monkeypatch.setattr(ticket_actions, "cancel", cancel_after_api_confirm)
    use()
    body = say(client, a, c, "CANCELAR").json()
    assert api["r"].status_code == 201
    ticket_id = api["r"].json()["id"]
    assert body["status"] == "already_completed" and body["result"]["id"] == ticket_id
    assert "no puede cancelarse" in body["answer"] and "No se ha creado" not in body["answer"] and "no se ha creado" not in body["answer"]
    after = counts(pg_server, app_db)
    assert after["tickets"] == before["tickets"] + 1
    assert q(pg_server, app_db, "SELECT action_status FROM chat_conversations WHERE conversation_id = %s", c) == [("completed",)]
    assert q(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE id = %s", aid) == [("consumed",)]
    monkeypatch.setattr(ticket_actions, "cancel", real_cancel)
    body = say(client, a, c, "CONFIRMAR").json()          # the conversation stays coherent: same ticket, no duplicate
    assert body["status"] == "ticket_created" and body["result"]["id"] == ticket_id
    assert counts(pg_server, app_db)["tickets"] == before["tickets"] + 1


def test_workflow_completion_wins_against_chat_cancel_lead(cx, pg_server, app_db, n8n, monkeypatch):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("lead", client, a, c, use)
    (aid, ahash), = q(pg_server, app_db, "SELECT id, payload_hash FROM pending_lead_actions WHERE conversation_id = %s", c)
    before = counts(pg_server, app_db)
    real_cancel, api = leads.cancel, {}

    def cancel_after_workflow(conn, requested_by, action_id):
        # the API confirmation runs the (FakeN8n) workflow, which commits the lead, before CANCELAR's cancel attempt
        api["r"] = TestClient(app).post("/leads/confirm", json={"pending_action_id": str(aid), "payload_hash": ahash},
                                        headers={**bearer(a), "Idempotency-Key": "api-" + uuid.uuid4().hex,
                                                 "X-Conversation-ID": c})
        return real_cancel(conn, requested_by, action_id)
    monkeypatch.setattr(leads, "cancel", cancel_after_workflow)
    use()
    body = say(client, a, c, "CANCELAR").json()
    assert api["r"].status_code == 201
    lead_id = api["r"].json()["id"]
    assert body["status"] == "already_completed" and body["result"] == {"kind": "lead", "id": lead_id}
    assert "no puede cancelarse" in body["answer"] and "No he borrado" in body["answer"]
    assert counts(pg_server, app_db)["leads"] == before["leads"] + 1
    assert q(pg_server, app_db, "SELECT count(*) FROM leads WHERE id = %s", lead_id) == [(1,)]  # nothing reversed
    assert q(pg_server, app_db, "SELECT action_status FROM chat_conversations WHERE conversation_id = %s", c) == [("completed",)]


@pytest.mark.parametrize("status", ["superseded", "expired"])
def test_cancel_of_a_no_longer_pending_action_is_truthful(cx, pg_server, app_db, status):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("ticket", client, a, c, use)
    with pg_server.connect(app_db["name"]) as conn:
        conn.execute("UPDATE pending_ticket_actions SET status = %s WHERE conversation_id = %s", (status, c))
    before = counts(pg_server, app_db)
    use()
    body = say(client, a, c, "CANCELAR").json()
    assert body["status"] == "not_pending" and "con ella no se ha creado nada" in body["answer"]
    assert counts(pg_server, app_db) == before
    assert q(pg_server, app_db, "SELECT action_status FROM chat_conversations WHERE conversation_id = %s", c) == [(None,)]


# ===================================== race matrix ==========================================================

def test_race_chat_confirm_vs_chat_cancel_one_wins_loser_sees_truth(cx, pg_server, app_db):
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("ticket", client, a, c, use)
    before = counts(pg_server, app_db)
    lock, out = chat_actions._lock_key("CUSTOMER_A", c), {}
    use()
    with pg_server.connect(app_db["name"]) as holder, pg_server.connect(app_db["name"]) as observer:
        holder.execute("SELECT pg_advisory_lock(%s)", (lock,))
        t1 = threading.Thread(target=lambda: out.update(confirm=say(TestClient(app), a, c, "CONFIRMAR").json()))
        t2 = threading.Thread(target=lambda: out.update(cancel=say(TestClient(app), a, c, "CANCELAR").json()))
        try:
            t1.start(); wait_until_waiting(observer, lock, 1)
            t2.start(); wait_until_waiting(observer, lock, 2)
        finally:
            holder.execute("SELECT pg_advisory_unlock(%s)", (lock,))
        t1.join(60); t2.join(60)
    created = counts(pg_server, app_db)["tickets"] - before["tickets"]
    assert created in (0, 1)
    if created:   # CONFIRMAR won: CANCELAR reports the authoritative completion
        assert out["confirm"]["status"] == "ticket_created" and out["cancel"]["status"] == "already_completed"
        assert out["cancel"]["result"]["id"] == out["confirm"]["result"]["id"]
    else:         # CANCELAR won: CONFIRMAR finds nothing pending
        assert out["cancel"]["status"] == "cancelled" and out["confirm"]["status"] == "nothing_pending"


def test_race_cancel_during_interpretation_stale_proposal_not_published(cx, pg_server, app_db):
    """B: reprepare vs CANCELAR. The model is interpreting a correction (revision N) while CANCELAR commits (N+1):
    the stale proposal must not re-prepare anything."""
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("ticket", client, a, c, use)

    def model_while_user_cancels(system, user):
        assert say(TestClient(app), a, c, "CANCELAR").json()["status"] == "cancelled"
        return intent("create_ticket", ticket={"priority": "critical"})
    use(model_while_user_cancels)
    before = counts(pg_server, app_db)
    body = say(client, a, c, "En realidad es crítica").json()
    assert body["status"] == "conversation_changed" and "No he aplicado" in body["answer"]
    assert counts(pg_server, app_db) == before
    assert q(pg_server, app_db, "SELECT count(*) FROM pending_ticket_actions WHERE conversation_id = %s AND status = 'pending'", c) == [(0,)]


def test_race_confirm_during_interpretation_stale_proposal_not_published(cx, pg_server, app_db):
    """C (other order): CONFIRMAR executes A while the model interprets a correction; the correction is not applied."""
    from app.main import app
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("ticket", client, a, c, use)

    def model_while_user_confirms(system, user):
        assert say(TestClient(app), a, c, "CONFIRMAR").json()["status"] == "ticket_created"
        return intent("create_ticket", ticket={"priority": "critical"})
    use(model_while_user_confirms)
    before = counts(pg_server, app_db)
    body = say(client, a, c, "En realidad es crítica").json()
    assert body["status"] == "conversation_changed"
    assert counts(pg_server, app_db)["pending_ticket_actions"] == before["pending_ticket_actions"]  # nothing re-prepared


def test_reprepare_then_cancel_cancels_the_current_version(cx, pg_server, app_db):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    prepare("ticket", client, a, c, use)
    use(intent("create_ticket", ticket={"priority": "critical"}))
    assert say(client, a, c, "corrección").json()["status"] == "awaiting_confirmation"
    before = counts(pg_server, app_db)
    use()
    assert say(client, a, c, "CANCELAR").json()["status"] == "cancelled"
    assert q(pg_server, app_db, "SELECT status FROM pending_ticket_actions WHERE conversation_id = %s ORDER BY created_at", c) == [
        ("superseded",), ("cancelled",)]
    assert say(client, a, c, "CONFIRMAR").json()["status"] == "nothing_pending"
    assert counts(pg_server, app_db)["tickets"] == before["tickets"]


def test_revision_increments_on_every_state_change(cx, pg_server, app_db):
    client, tokens, use = cx
    a, c = tokens["CUSTOMER_A"], conv()
    rev = lambda: q(pg_server, app_db, "SELECT revision FROM chat_conversations WHERE conversation_id = %s", c)[0][0]
    use(intent("create_ticket", ticket={"subject": "Sin internet", "description": "No hay internet."}))
    say(client, a, c, "sin internet"); r1 = rev()
    use(intent("create_ticket", ticket={"contact_name": "Ana", "priority": "normal"}))
    say(client, a, c, "Ana, normal"); r2 = rev()
    use()
    say(client, a, c, "CONFIRMAR"); r3 = rev()
    assert r1 < r2 < r3
    use(intent("ticket_status"))
    say(client, a, c, "estado T-1001")  # read paths never change the revision
    assert rev() == r3
