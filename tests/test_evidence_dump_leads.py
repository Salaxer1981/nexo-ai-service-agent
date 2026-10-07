"""Opt-in: representative lead rows + audit lines for evidence (set NEXO_EVIDENCE_DIR).

Uses FakeN8n (NOT n8n): this evidence shows the backend side of the hop only.
"""
import json
import logging
import os
from pathlib import Path

import pytest

from conftest import bearer
from test_leads import DRAFT, fake_n8n, lapi  # noqa: F401  (fixtures)

OUT = os.environ.get("NEXO_EVIDENCE_DIR")


@pytest.mark.skipif(not OUT, reason="evidence dump only when NEXO_EVIDENCE_DIR is set")
def test_dump_lead_evidence(lapi, pg_server, app_db, caplog):  # noqa: F811
    client, tokens, fake = lapi
    a = bearer(tokens["CUSTOMER_A"])
    lines = ["# APP-03B representative lead evidence: LOCAL, throwaway PostgreSQL 17.11, synthetic data.",
             "# The n8n hop here is FakeN8n (a test stand-in), NOT n8n. Real n8n execution = VM phase.", ""]

    def step(label, r):
        b = r.json()
        shown = {k: b[k] for k in ("pending_action_id", "status", "id", "workflow_execution_id", "code") if k in b}
        lines.append(f"{label} -> HTTP {r.status_code} {r.headers.get('Idempotency-Outcome', '')} {json.dumps(shown)}")
        return b

    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        h = {**a, "X-Conversation-ID": "conv-evidence-lead"}
        p1 = step("1. prepare", client.post("/leads/prepare", json=DRAFT, headers=h))
        p2 = step("2. prepare again with changed need (same conversation) -> #1 superseded",
                  client.post("/leads/prepare", json={**DRAFT, "need": "Synthetic: automate enquiries and follow-ups."},
                              headers=h))
        body = lambda p: {"pending_action_id": p["pending_action_id"], "payload_hash": p["payload_hash"]}
        step("3. confirm superseded #1", client.post("/leads/confirm", json=body(p1),
                                                     headers={**h, "Idempotency-Key": "evidence-lk1"}))
        step("4. confirm #2 (key evidence-lk2) -> workflow -> /internal/leads",
             client.post("/leads/confirm", json=body(p2),
                         headers={**h, "Idempotency-Key": "evidence-lk2", "X-Request-ID": "req-evidence-lead"}))
        step("5. retry same key", client.post("/leads/confirm", json=body(p2), headers={**h, "Idempotency-Key": "evidence-lk2"}))
        step("6. reuse consumed #2 with new key", client.post("/leads/confirm", json=body(p2),
                                                              headers={**h, "Idempotency-Key": "evidence-lk3"}))
        step("7. CUSTOMER_A token calls /internal/leads directly", client.post("/internal/leads", headers={
            **a, "Idempotency-Key": "evidence-lk2"}, json={**body(p2), "lead": DRAFT, "workflow_execution_id": "direct"}))
    lines.append(f"FakeN8n calls: {fake.calls}")

    with pg_server.connect(app_db["name"]) as conn:
        for title, sql in {
            "pending_lead_actions (conv-evidence-lead)":
                "SELECT id, requested_by_customer_id, status, left(payload_hash,16)||'…' AS payload_hash,"
                " confirm_key_sha256 IS NOT NULL AS key_bound, consumed_at IS NOT NULL AS consumed"
                " FROM pending_lead_actions WHERE conversation_id = 'conv-evidence-lead' ORDER BY created_at",
            "leads created from those actions":
                "SELECT l.id, l.company_name, l.contact_email, l.requested_by_customer_id, l.source_action_id,"
                " l.workflow_execution_id FROM leads l JOIN pending_lead_actions p ON p.id = l.source_action_id"
                " WHERE p.conversation_id = 'conv-evidence-lead'",
            "service_credentials (no raw token stored)":
                "SELECT name, scope, left(token_sha256, 12)||'…' AS token_sha256_prefix FROM service_credentials",
            "schema version": "SELECT max(version) FROM schema_migrations",
        }.items():
            cur = conn.execute(sql)
            lines += ["", f"## {title}", " | ".join(c.name for c in cur.description)]
            lines += [" | ".join(str(v) for v in row) for row in cur.fetchall()]
    lines += ["", "## audit lines (nexo.audit) for this scenario"]
    lines += [r.getMessage() for r in caplog.records if r.name == "nexo.audit"]
    Path(OUT, "postgres-and-trace-evidence.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
