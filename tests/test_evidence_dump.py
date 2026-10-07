"""Opt-in: write representative database state for evidence (set NEXO_EVIDENCE_DIR).

Runs a scripted scenario through the real API and dumps the resulting rows. Contains no
credentials: tokens and passwords are never selected or printed.
"""
import os
from pathlib import Path

import pytest

from conftest import bearer

OUT = os.environ.get("NEXO_EVIDENCE_DIR")
DRAFT = {"contact_name": "Ana (synthetic)", "subject": "Synthetic: no internet in the whole office",
         "description": "Synthetic test: whole office without internet for twenty minutes.", "priority": "critical"}


@pytest.mark.skipif(not OUT, reason="evidence dump only when NEXO_EVIDENCE_DIR is set")
def test_dump_representative_db_state(api, pg_server, app_db):
    client, tokens = api
    a = bearer(tokens["CUSTOMER_A"])
    lines = ["# APP-02 representative database evidence (throwaway PostgreSQL 17.11, synthetic data)", ""]

    def step(text, response):
        lines.append(f"{text} -> HTTP {response.status_code}"
                     f" {response.headers.get('Idempotency-Outcome', '')} {response.json().get('code', '')}".rstrip())

    first = client.post("/tickets/prepare", json={**DRAFT, "priority": "normal"},
                        headers={**a, "X-Conversation-ID": "conv-evidence"})
    step("1. prepare (priority normal)", first)
    second = client.post("/tickets/prepare", json=DRAFT, headers={**a, "X-Conversation-ID": "conv-evidence"})
    step("2. prepare again with priority critical (same conversation) -> first is superseded", second)
    p1, p2 = first.json(), second.json()
    step("3. confirm superseded action #1",
         client.post("/tickets/confirm", headers={**a, "Idempotency-Key": "evidence-k0"},
                     json={"pending_action_id": p1["pending_action_id"], "payload_hash": p1["payload_hash"]}))
    body = {"pending_action_id": p2["pending_action_id"], "payload_hash": p2["payload_hash"]}
    step("4. confirm action #2 with key evidence-k1",
         client.post("/tickets/confirm", headers={**a, "Idempotency-Key": "evidence-k1"}, json=body))
    step("5. retry same key evidence-k1",
         client.post("/tickets/confirm", headers={**a, "Idempotency-Key": "evidence-k1"}, json=body))
    step("6. reuse consumed action #2 with new key evidence-k2",
         client.post("/tickets/confirm", headers={**a, "Idempotency-Key": "evidence-k2"}, json=body))
    step("7. CUSTOMER_B tries CUSTOMER_A's action #2",
         client.post("/tickets/confirm", headers={**bearer(tokens["CUSTOMER_B"]), "Idempotency-Key": "evidence-k3"},
                     json=body))

    queries = {
        "schema_migrations": "SELECT version FROM schema_migrations ORDER BY version",
        "pending_ticket_actions (this scenario)":
            "SELECT id, customer_id, conversation_id, priority, status, left(payload_hash, 16) || '…' AS payload_hash,"
            " consumed_at IS NOT NULL AS consumed FROM pending_ticket_actions"
            " WHERE conversation_id = 'conv-evidence' ORDER BY created_at",
        "tickets (seed + created from this scenario)":
            "SELECT t.id, t.customer_id, t.priority, t.status, t.source_action_id FROM tickets t"
            " LEFT JOIN pending_ticket_actions p ON p.id = t.source_action_id"
            " WHERE t.source_action_id IS NULL OR p.conversation_id = 'conv-evidence' ORDER BY t.created_at",
        "idempotency_keys (this scenario)":
            "SELECT customer_id, operation, idempotency_key, left(request_hash, 16) || '…' AS request_hash,"
            " pending_action_id, ticket_id, response_status FROM idempotency_keys"
            " WHERE idempotency_key LIKE 'evidence-%' ORDER BY created_at",
        "tickets per source action (must be <= 1)":
            "SELECT source_action_id, count(*) FROM tickets WHERE source_action_id IS NOT NULL"
            " GROUP BY 1 HAVING count(*) > 1",
    }
    with pg_server.connect(app_db["name"]) as conn:
        for title, sql in queries.items():
            cur = conn.execute(sql)
            lines += ["", f"## {title}", " | ".join(c.name for c in cur.description)]
            rows = cur.fetchall()
            lines += [" | ".join(str(v) for v in row) for row in rows] or ["(no rows)"]
    Path(OUT, "database-evidence.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
