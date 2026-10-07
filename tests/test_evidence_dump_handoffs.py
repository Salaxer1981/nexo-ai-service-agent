"""Opt-in: representative handoff rows + audit lines for evidence (set NEXO_EVIDENCE_DIR). No credentials."""
import json
import logging
import os
from pathlib import Path

import pytest

from conftest import bearer

OUT = os.environ.get("NEXO_EVIDENCE_DIR")


@pytest.mark.skipif(not OUT, reason="evidence dump only when NEXO_EVIDENCE_DIR is set")
def test_dump_handoff_evidence(api, pg_server, app_db, caplog):
    client, tokens = api
    lines = ["# APP-03A representative handoff evidence (throwaway PostgreSQL 17.11, synthetic data)", ""]
    body = {"conversation_id": "conv-evidence-h1", "reason": "critical_incident",
            "summary": "Synthetic: whole office without internet; customer asked to escalate."}

    def post(label, token, payload, key, **headers):
        r = client.post("/handoffs", json=payload, headers={**bearer(token), "Idempotency-Key": key, **headers})
        shown = {k: r.json().get(k) for k in ("id", "customer_id", "status", "code") if k in r.json()}
        lines.append(f"{label} -> HTTP {r.status_code} {r.headers.get('Idempotency-Outcome', '')} {json.dumps(shown)}")
        return r

    with caplog.at_level(logging.INFO, logger="nexo.audit"):
        first = post("1. CUSTOMER_A creates handoff (key evidence-h1)", tokens["CUSTOMER_A"], body, "evidence-h1",
                     **{"X-Request-ID": "req-evidence-h1", "X-Conversation-ID": "conv-evidence-h1"})
        post("2. retry same key + same request", tokens["CUSTOMER_A"], body, "evidence-h1")
        post("3. same key + different summary", tokens["CUSTOMER_A"], {**body, "summary": "Synthetic: changed."}, "evidence-h1")
        post("4. CUSTOMER_B, human_requested (key evidence-h2)", tokens["CUSTOMER_B"],
             {"conversation_id": "conv-evidence-h2", "reason": "human_requested",
              "summary": "Synthetic: customer asks to speak to a person."}, "evidence-h2")
    lines += ["", "## first response body (contract)", json.dumps(first.json(), indent=2)]

    with pg_server.connect(app_db["name"]) as conn:
        cur = conn.execute("SELECT id, customer_id, conversation_id, reason, status, idempotency_key,"
                           " left(request_hash, 16) || '…' AS request_hash, created_at FROM handoffs"
                           " WHERE idempotency_key LIKE 'evidence-%' ORDER BY created_at")
        lines += ["", "## handoffs rows", " | ".join(c.name for c in cur.description)]
        lines += [" | ".join(str(v) for v in row) for row in cur.fetchall()]
        version = conn.execute("SELECT max(version) FROM schema_migrations").fetchone()[0]
    lines += ["", f"schema version: {version}", "", "## audit lines (nexo.audit)"]
    lines += [r.getMessage() for r in caplog.records if r.name == "nexo.audit"]
    Path(OUT, "database-and-trace-evidence.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
