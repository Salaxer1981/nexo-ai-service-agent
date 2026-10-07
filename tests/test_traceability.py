"""request_id / conversation_id tracing and credential hygiene (required case 12)."""
import json
import logging

import pytest

from app.config import ConfigError
from app.provision_auth import hash_token, read_tokens
from conftest import TICKET_A, TICKET_B, bearer


def _audit_events(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "nexo.audit"]


def test_request_id_is_generated_and_returned(api, caplog):
    client, tokens = api
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        r = client.get(f"/tickets/{TICKET_A}", headers=bearer(tokens["CUSTOMER_A"]))
    request_id = r.headers["X-Request-ID"]
    assert len(request_id) == 36
    event = _audit_events(caplog)[-1]
    assert event["request_id"] == request_id
    assert event["route"] == "/tickets/{ticket_id}"
    assert event["action"] == "ticket.read"
    assert event["result"] == "allowed"
    assert event["customer_id"] == "CUSTOMER_A"
    assert event["status"] == 200
    assert isinstance(event["duration_ms"], float)


def test_client_request_and_conversation_ids_are_propagated(api, caplog):
    client, tokens = api
    headers = {**bearer(tokens["CUSTOMER_A"]), "X-Request-ID": "req-123", "X-Conversation-ID": "conv-abc"}
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        r = client.get(f"/tickets/{TICKET_A}", headers=headers)
    assert r.headers["X-Request-ID"] == "req-123"
    event = _audit_events(caplog)[-1]
    assert (event["request_id"], event["conversation_id"]) == ("req-123", "conv-abc")


def test_unsafe_correlation_ids_are_replaced(api, caplog):
    client, _ = api
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        r = client.get("/health", headers={"X-Request-ID": "bad id\nwith newline", "X-Conversation-ID": "x" * 200})
    assert r.headers["X-Request-ID"] != "bad id\nwith newline"
    assert _audit_events(caplog)[-1]["conversation_id"] is None


def test_denials_are_audited_distinctly_but_answered_identically(api, caplog):
    client, tokens = api
    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        client.get(f"/tickets/{TICKET_B}", headers=bearer(tokens["CUSTOMER_A"]))
        client.get("/tickets/00000000-0000-4000-8000-000000000000", headers=bearer(tokens["CUSTOMER_A"]))
        client.get(f"/tickets/{TICKET_A}")
    results = [e.get("result") for e in _audit_events(caplog)]
    assert results == ["denied_not_owner", "not_found", "unauthenticated"]


# 12
def test_no_credentials_in_logs_or_responses(api, app_db, caplog):
    client, tokens = api
    password = app_db["env"]["POSTGRES_PASSWORD"]
    secrets_ = [tokens["CUSTOMER_A"], tokens["CUSTOMER_B"], password]
    texts = []
    with caplog.at_level(logging.DEBUG):
        for headers in (bearer(tokens["CUSTOMER_A"]), bearer(tokens["CUSTOMER_B"]), bearer("wrong" * 10), {}):
            for path in (f"/tickets/{TICKET_A}", f"/tickets/{TICKET_B}", "/me", "/health/ready"):
                r = client.get(path, headers=headers)
                texts.append(r.text)
                texts.append(json.dumps(dict(r.headers)))
    texts.append(caplog.text)
    blob = "\n".join(texts)
    for secret in secrets_:
        assert secret not in blob
        assert hash_token(secret) not in blob
    assert "Bearer " not in caplog.text
    assert "authorization" not in caplog.text.lower()


def test_credentials_are_stored_only_as_hashes(pg_server, app_db):
    with pg_server.connect(app_db["name"]) as conn:
        stored = [r[0] for r in conn.execute("SELECT token_sha256 FROM api_credentials ORDER BY customer_id")]
    tokens = app_db["tokens"]
    assert stored == [hash_token(tokens["CUSTOMER_A"]), hash_token(tokens["CUSTOMER_B"])]
    for token in tokens.values():
        assert token not in stored


@pytest.mark.parametrize("env", [
    {},
    {"AUTH_TOKEN_CUSTOMER_A": "short", "AUTH_TOKEN_CUSTOMER_B": "y" * 40},
    {"AUTH_TOKEN_CUSTOMER_A": "z" * 40, "AUTH_TOKEN_CUSTOMER_B": "z" * 40},
])
def test_weak_or_missing_tokens_are_refused_without_echoing_values(env):
    with pytest.raises(ConfigError) as exc:
        read_tokens(env)
    for value in env.values():
        assert value not in str(exc.value)
