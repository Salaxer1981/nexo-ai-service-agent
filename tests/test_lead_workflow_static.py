"""Static checks of the version-controlled n8n lead workflow (n8n/workflows/nexo-lead-create.json).

These prove the workflow's STRUCTURE (what it would do). They are not proof that n8n executed it;
that is the VM phase.
"""
import json
import re
from urllib.parse import urlparse

import yaml

from app.config import DEFAULT_N8N_LEAD_WEBHOOK_URL
from conftest import ROOT

PATH = ROOT / "n8n" / "workflows" / "nexo-lead-create.json"
RAW = PATH.read_text(encoding="utf-8")
WF = json.loads(RAW)
NODES = {n["name"]: n for n in WF["nodes"]}


def _by_type(node_type):
    return [n for n in WF["nodes"] if n["type"] == node_type]


def test_workflow_identity_and_small_node_set():
    assert WF["name"] == "nexo-lead-create" and WF["id"] == "NexoLeadCreate01"
    assert {n["type"] for n in WF["nodes"]} == {
        "n8n-nodes-base.webhook", "n8n-nodes-base.if", "n8n-nodes-base.httpRequest", "n8n-nodes-base.respondToWebhook"}
    assert WF["active"] is False  # activation is an explicit deployment step


def test_no_database_or_code_nodes():
    forbidden = re.compile(r"postgres|mysql|sql|mongo|redis|code|function|executeCommand|ssh|email|slack", re.I)
    assert not [n["type"] for n in WF["nodes"] if forbidden.search(n["type"].split(".")[-1])]


def test_webhook_matches_backend_dispatch_url_and_compose():
    [hook] = _by_type("n8n-nodes-base.webhook")
    p = hook["parameters"]
    assert p["httpMethod"] == "POST" and p["responseMode"] == "responseNode"
    assert urlparse(DEFAULT_N8N_LEAD_WEBHOOK_URL).path == f"/webhook/{p['path']}" == "/webhook/nexo-lead-create"
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert compose["services"]["backend"]["environment"]["N8N_LEAD_WEBHOOK_URL"] == DEFAULT_N8N_LEAD_WEBHOOK_URL
    assert urlparse(DEFAULT_N8N_LEAD_WEBHOOK_URL).hostname == "n8n"  # private Docker DNS name


def test_http_request_calls_the_private_lead_write_route():
    [http] = _by_type("n8n-nodes-base.httpRequest")
    p = http["parameters"]
    assert p["method"] == "POST" and p["url"] == "http://backend:8000/internal/leads"
    assert p["authentication"] == "genericCredentialType" and p["genericAuthType"] == "httpHeaderAuth"
    headers = {h["name"]: h["value"] for h in p["headerParameters"]["parameters"]}
    assert headers["Idempotency-Key"] == "={{ $json.body.idempotency_key }}"   # same key end-to-end
    assert headers["X-Request-ID"] == "={{ $json.headers['x-request-id'] }}"     # correlation
    for part in ("pending_action_id", "payload_hash", "lead:", "workflow_execution_id: $execution.id"):
        assert part in p["jsonBody"]
    assert p["options"]["response"]["response"] == {"fullResponse": True, "neverError": True}


def test_credential_is_referenced_not_embedded():
    [http] = _by_type("n8n-nodes-base.httpRequest")
    assert http["credentials"] == {"httpHeaderAuth": {"id": "NexoLeadWriter01", "name": "nexo-lead-writer"}}
    assert "Bearer" not in RAW and "token" not in RAW.lower().replace("idempotency", "")
    assert not re.search(r"[A-Za-z0-9_-]{40,}", RAW)  # no long token-like literal anywhere
    assert "password" not in RAW.lower()


def test_flow_wiring_and_envelope_check():
    c = WF["connections"]
    assert c["Lead webhook"]["main"][0][0]["node"] == "Envelope complete?"
    assert c["Envelope complete?"]["main"][0][0]["node"] == "Create lead in backend"     # true branch
    assert c["Envelope complete?"]["main"][1][0]["node"] == "Reject incomplete envelope"  # false branch
    assert c["Create lead in backend"]["main"][0][0]["node"] == "Return backend result"
    conditions = NODES["Envelope complete?"]["parameters"]["conditions"]
    checked = {re.search(r"\$json\.body\.(\w+)", x["leftValue"]).group(1) for x in conditions["conditions"]}
    assert checked == {"pending_action_id", "idempotency_key", "payload_hash", "lead"}
    assert conditions["combinator"] == "and"
    assert NODES["Return backend result"]["parameters"]["options"]["responseCode"] == "={{ $json.statusCode }}"
    assert NODES["Reject incomplete envelope"]["parameters"]["options"]["responseCode"] == 400
