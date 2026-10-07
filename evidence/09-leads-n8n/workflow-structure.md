# n8n workflow structure: n8n/workflows/nexo-lead-create.json (version-controlled, exported WITHOUT credentials)

name: nexo-lead-create   id: NexoLeadCreate01   active in repo: False (activation is a deployment step)

## Nodes
- Lead webhook  [n8n-nodes-base.webhook v2]  POST /webhook/nexo-lead-create  responseMode=responseNode
- Envelope complete?  [n8n-nodes-base.if v2]  AND of notEmpty(pending_action_id, idempotency_key, payload_hash, lead)
- Create lead in backend  [n8n-nodes-base.httpRequest v4.2]  POST http://backend:8000/internal/leads  auth=httpHeaderAuth credential={'id': 'NexoLeadWriter01', 'name': 'nexo-lead-writer'}  headers=['Idempotency-Key', 'X-Request-ID']  fullResponse+neverError
- Return backend result  [n8n-nodes-base.respondToWebhook v1.1]  responseCode=={{ $json.statusCode }}
- Reject incomplete envelope  [n8n-nodes-base.respondToWebhook v1.1]  responseCode=400

## Connections
- Lead webhook --[main]--> Envelope complete?
- Envelope complete? --[true]--> Create lead in backend
- Envelope complete? --[false]--> Reject incomplete envelope
- Create lead in backend --[main]--> Return backend result

## Request body sent to the backend (HTTP Request node, jsonBody expression)
={{ JSON.stringify({ pending_action_id: $json.body.pending_action_id, payload_hash: $json.body.payload_hash, lead: $json.body.lead, workflow_execution_id: $execution.id }) }}

Credential: referenced by id/name only (NexoLeadWriter01 / nexo-lead-writer); the token is created inside n8n at deployment.
No database, code, email, SSH or SaaS nodes. Static checks: tests/test_lead_workflow_static.py (6 tests).
