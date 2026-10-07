"""APP02-01 regression: concurrent prepare() must never leave two pending actions in one group.

Deterministic interleaving (no timing guesses):
  - A test-only trigger makes every INSERT into pending_ticket_actions wait on a GATE advisory
    lock (shared) that the test holds exclusively.
  - T1 runs prepare(): it takes its group lock, runs the supersede UPDATE, then blocks inside
    its INSERT on the GATE: exactly the audited critical point.
  - T2 then runs prepare() for the same group. The test inspects pg_locks to see WHAT T2 waits
    on: with the fix, the group lock (before its UPDATE); with the bug, the GATE (after its
    UPDATE already ran and found nothing to supersede).
  - The GATE is released and the final state is asserted.
"""
import threading
import time
import uuid

import psycopg
import pytest

from app import ticket_actions
from app.config import load_settings
from app.db import connect
from conftest import bearer

GATE = 7_270_020_001  # test-only advisory key, unrelated to app keys
DATA = {"contact_name": "Test Contact (synthetic)", "subject": "Synthetic: race",
        "description": "Synthetic concurrency test.", "priority": "normal"}
ITERATIONS = 5


def _split(key: int) -> tuple[int, int]:
    """pg_locks shows a bigint advisory key as (classid = high 32 bits, objid = low 32 bits)."""
    unsigned = key & 0xFFFFFFFFFFFFFFFF
    return unsigned >> 32, unsigned & 0xFFFFFFFF


def _waiting(conn) -> list[tuple[int, int]]:
    return sorted(conn.execute(
        "SELECT classid::bigint, objid::bigint FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
        " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())").fetchall())


def _wait_until(predicate, what: str, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for: {what}")


@pytest.fixture
def gate(pg_server, app_db, api):
    """Install the INSERT gate trigger and hold the GATE lock; always cleaned up."""
    control = pg_server.connect(app_db["name"])
    control.execute(
        "CREATE OR REPLACE FUNCTION test_insert_gate() RETURNS trigger LANGUAGE plpgsql AS"
        f" $$ BEGIN PERFORM pg_advisory_xact_lock_shared({GATE}); RETURN NEW; END; $$")
    control.execute("DROP TRIGGER IF EXISTS test_insert_gate ON pending_ticket_actions")
    control.execute("CREATE TRIGGER test_insert_gate BEFORE INSERT ON pending_ticket_actions"
                    " FOR EACH ROW EXECUTE FUNCTION test_insert_gate()")
    try:
        yield control
    finally:
        control.execute("SELECT pg_advisory_unlock_all()")
        control.execute("DROP TRIGGER IF EXISTS test_insert_gate ON pending_ticket_actions")
        control.execute("DROP FUNCTION IF EXISTS test_insert_gate()")
        control.close()


class Prepare(threading.Thread):
    def __init__(self, customer_id: str, conversation_id: str | None):
        super().__init__(daemon=True)
        self.customer_id, self.conversation_id = customer_id, conversation_id
        self.result, self.error = None, None
        self.settings = load_settings()

    def run(self):
        try:
            with connect(self.settings, autocommit=True) as conn:
                self.result = ticket_actions.prepare(conn, self.customer_id, DATA, self.conversation_id)
        except Exception as exc:  # surfaced by the test, never swallowed
            self.error = exc


def _finish(*threads):
    for t in threads:
        t.join(30)
    assert not any(t.is_alive() for t in threads), "a prepare() call hung"
    for t in threads:
        assert t.error is None, f"prepare() failed: {t.error!r}"


def _statuses(control, ids) -> dict[str, str]:
    rows = control.execute("SELECT id::text, status FROM pending_ticket_actions WHERE id = ANY(%s::uuid[])",
                           (list(ids),)).fetchall()
    return dict(rows)


def _race_pair(control, first: Prepare, second: Prepare) -> tuple[int, int]:
    """Run the critical interleaving; return the advisory key (split) the SECOND call waited on."""
    control.execute("SELECT pg_advisory_lock(%s)", (GATE,))
    first.start()
    _wait_until(lambda: _waiting(control) == [_split(GATE)], "first prepare blocked inside its INSERT")
    second.start()

    def two_waiting():
        waits = _waiting(control)
        return waits if len(waits) == 2 else None

    second_wait = list(_wait_until(two_waiting, "second prepare blocked"))
    second_wait.remove(_split(GATE))  # one of the two waits is the first call's GATE wait
    control.execute("SELECT pg_advisory_unlock(%s)", (GATE,))
    _finish(first, second)
    return second_wait[0]


def test_concurrent_prepare_same_group_is_serialized(api, pg_server, app_db, gate):
    client, tokens = api
    for _ in range(ITERATIONS):
        conversation = f"race-{uuid.uuid4().hex[:12]}"
        t1, t2 = Prepare("CUSTOMER_A", conversation), Prepare("CUSTOMER_A", conversation)
        waited_on = _race_pair(gate, t1, t2)

        first_id, second_id = t1.result["pending_action_id"], t2.result["pending_action_id"]
        assert _statuses(gate, [first_id, second_id]) == {first_id: "superseded", second_id: "pending"}
        # The second call waited on the GROUP lock, i.e. BEFORE its supersede UPDATE.
        assert waited_on == _split(ticket_actions.prepare_lock_key("CUSTOMER_A", conversation))
        pending = gate.execute("SELECT count(*) FROM pending_ticket_actions WHERE customer_id = 'CUSTOMER_A'"
                               " AND conversation_id = %s AND status = 'pending'", (conversation,)).fetchone()[0]
        assert pending == 1

        before = gate.execute("SELECT count(*) FROM tickets").fetchone()[0]
        headers = lambda: {**bearer(tokens["CUSTOMER_A"]), "Idempotency-Key": f"k-{uuid.uuid4()}"}
        stale = client.post("/tickets/confirm", headers=headers(),
                            json={"pending_action_id": first_id, "payload_hash": t1.result["payload_hash"]})
        assert stale.status_code == 409 and stale.json()["code"] == "confirmation_invalid"
        winner = client.post("/tickets/confirm", headers=headers(),
                             json={"pending_action_id": second_id, "payload_hash": t2.result["payload_hash"]})
        assert winner.status_code == 201
        again = client.post("/tickets/confirm", headers=headers(),
                            json={"pending_action_id": first_id, "payload_hash": t1.result["payload_hash"]})
        assert again.status_code == 409
        assert gate.execute("SELECT count(*) FROM tickets").fetchone()[0] == before + 1


@pytest.mark.parametrize("second_group", ["other_customer", "other_conversation", "no_conversation"])
def test_different_groups_do_not_block_or_supersede_each_other(api, gate, second_group):
    for _ in range(ITERATIONS):
        conversation = f"race-{uuid.uuid4().hex[:12]}"
        t1 = Prepare("CUSTOMER_A", conversation)
        t2 = {"other_customer": Prepare("CUSTOMER_B", conversation),
              "other_conversation": Prepare("CUSTOMER_A", f"race-{uuid.uuid4().hex[:12]}"),
              "no_conversation": Prepare("CUSTOMER_A", None)}[second_group]
        waited_on = _race_pair(gate, t1, t2)
        # The second call was NOT held by the first group's lock: it reached its own INSERT.
        assert waited_on == _split(GATE)
        ids = [t1.result["pending_action_id"], t2.result["pending_action_id"]]
        assert set(_statuses(gate, ids).values()) == {"pending"}


def test_many_concurrent_prepares_leave_exactly_one_pending(api, gate):
    gate.execute("DROP TRIGGER IF EXISTS test_insert_gate ON pending_ticket_actions")  # free-running race
    for _ in range(20):
        conversation = f"race-{uuid.uuid4().hex[:12]}"
        threads = [Prepare("CUSTOMER_A", conversation) for _ in range(6)]
        for t in threads:
            t.start()
        _finish(*threads)
        rows = gate.execute("SELECT status, count(*) FROM pending_ticket_actions WHERE conversation_id = %s"
                            " GROUP BY status", (conversation,)).fetchall()
        assert dict(rows) == {"pending": 1, "superseded": 5}


def test_database_allows_only_one_pending_action_per_group(pg_server, app_db):
    insert = ("INSERT INTO pending_ticket_actions (customer_id, conversation_id, contact_name, subject,"
              " description, priority, payload_hash, expires_at)"
              " VALUES ('CUSTOMER_A', %s, 'x', 'x', 'x', 'normal', repeat('a', 64), now() + interval '1 hour')")
    for conversation in (f"idx-{uuid.uuid4().hex[:12]}", None):
        with pg_server.connect(app_db["name"]) as conn:
            if conversation is None:
                conn.execute("UPDATE pending_ticket_actions SET status = 'superseded'"
                             " WHERE customer_id = 'CUSTOMER_A' AND conversation_id IS NULL AND status = 'pending'")
            conn.execute(insert, (conversation,))
            with pytest.raises(psycopg.errors.UniqueViolation):
                conn.execute(insert, (conversation,))


def test_lock_key_is_deterministic_and_group_specific():
    key = ticket_actions.prepare_lock_key
    assert key("CUSTOMER_A", "c1") == key("CUSTOMER_A", "c1")
    assert -(2 ** 63) <= key("CUSTOMER_A", "c1") < 2 ** 63
    distinct = {key("CUSTOMER_A", "c1"), key("CUSTOMER_B", "c1"), key("CUSTOMER_A", "c2"),
                key("CUSTOMER_A", None), key("CUSTOMER_B", None)}
    assert len(distinct) == 5
