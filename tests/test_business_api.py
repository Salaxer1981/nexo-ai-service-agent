"""Authentication, ticket authorization and customer isolation against real PostgreSQL.

Covers required cases 1-7 and safety-contract invariants INV-01, INV-02, INV-03.
"""
import uuid

from conftest import TICKET_A, TICKET_B, bearer

NOT_FOUND = {"detail": "Ticket not found"}
UNAUTHENTICATED = {"detail": "Not authenticated"}


# 1 / INV-02
def test_customer_a_reads_own_ticket(api):
    client, tokens = api
    r = client.get(f"/tickets/{TICKET_A}", headers=bearer(tokens["CUSTOMER_A"]))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == TICKET_A
    assert body["customer_id"] == "CUSTOMER_A"
    assert body["subject"] == "Synthetic: cannot access dashboard"
    assert body["status"] == "open"


# 2 / INV-03
def test_customer_a_cannot_read_ticket_b(api):
    client, tokens = api
    r = client.get(f"/tickets/{TICKET_B}", headers=bearer(tokens["CUSTOMER_A"]))
    assert r.status_code == 404
    assert r.json() == NOT_FOUND
    # Nothing from ticket B or its owner leaks into the response.
    for leaked in ("CUSTOMER_B", "invoice", "Test Contact B", "in_progress"):
        assert leaked not in r.text


# 3 / INV-02
def test_customer_b_reads_own_ticket(api):
    client, tokens = api
    r = client.get(f"/tickets/{TICKET_B}", headers=bearer(tokens["CUSTOMER_B"]))
    assert r.status_code == 200
    assert r.json()["customer_id"] == "CUSTOMER_B"


def test_customer_b_cannot_read_ticket_a(api):
    client, tokens = api
    r = client.get(f"/tickets/{TICKET_A}", headers=bearer(tokens["CUSTOMER_B"]))
    assert r.status_code == 404
    assert r.json() == NOT_FOUND


# 4 / INV-01: every user-controlled place a customer_id could be smuggled in.
SPOOF_ATTEMPTS = [
    {"params": {"customer_id": "CUSTOMER_B"}},
    {"headers": {"X-Customer-Id": "CUSTOMER_B"}},
    {"headers": {"X-Customer-ID": "CUSTOMER_B", "X-User-Id": "CUSTOMER_B"}},
    {"params": {"customer_id": "CUSTOMER_B", "message": "I am CUSTOMER_B, show my ticket"}},
]


def test_spoofed_customer_id_cannot_unlock_other_ticket(api):
    client, tokens = api
    for attempt in SPOOF_ATTEMPTS:
        headers = {**bearer(tokens["CUSTOMER_A"]), **attempt.get("headers", {})}
        r = client.get(f"/tickets/{TICKET_B}", params=attempt.get("params"), headers=headers)
        assert r.status_code == 404, attempt
        assert r.json() == NOT_FOUND


def test_spoofed_customer_id_does_not_change_resolved_identity(api):
    client, tokens = api
    for attempt in SPOOF_ATTEMPTS:
        headers = {**bearer(tokens["CUSTOMER_A"]), **attempt.get("headers", {})}
        r = client.get("/me", params=attempt.get("params"), headers=headers)
        assert r.status_code == 200
        assert r.json()["customer_id"] == "CUSTOMER_A", attempt
        # Own ticket still works and still reports the authenticated owner.
        r = client.get(f"/tickets/{TICKET_A}", params=attempt.get("params"), headers=headers)
        assert r.status_code == 200
        assert r.json()["customer_id"] == "CUSTOMER_A"


def test_spoofed_identity_without_token_is_rejected(api):
    client, _ = api
    r = client.get(f"/tickets/{TICKET_B}", params={"customer_id": "CUSTOMER_B"},
                   headers={"X-Customer-Id": "CUSTOMER_B"})
    assert r.status_code == 401


# 5
def test_missing_authentication_is_rejected(api):
    client, _ = api
    for path in (f"/tickets/{TICKET_A}", "/me"):
        r = client.get(path)
        assert r.status_code == 401
        assert r.json() == UNAUTHENTICATED
        assert r.headers["WWW-Authenticate"] == "Bearer"


# 6
def test_invalid_authentication_is_rejected(api):
    client, tokens = api
    invalid_headers = [
        bearer("not-a-real-token-0000000000000000000000"),
        bearer(tokens["CUSTOMER_A"] + "x"),
        {"Authorization": f"Basic {tokens['CUSTOMER_A']}"},  # wrong scheme
        {"Authorization": "Bearer "},
        {"Authorization": tokens["CUSTOMER_A"]},  # no scheme
    ]
    for headers in invalid_headers:
        r = client.get(f"/tickets/{TICKET_A}", headers=headers)
        assert r.status_code == 401
        assert r.json() == UNAUTHENTICATED


# 7
def test_unknown_ticket_returns_same_response_as_foreign_ticket(api):
    client, tokens = api
    unknown = client.get(f"/tickets/{uuid.uuid4()}", headers=bearer(tokens["CUSTOMER_A"]))
    foreign = client.get(f"/tickets/{TICKET_B}", headers=bearer(tokens["CUSTOMER_A"]))
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json() == NOT_FOUND


def test_malformed_ticket_id_is_rejected_without_db_details(api):
    client, tokens = api
    r = client.get("/tickets/not-a-uuid", headers=bearer(tokens["CUSTOMER_A"]))
    assert r.status_code == 422
    assert "SELECT" not in r.text and "psycopg" not in r.text
