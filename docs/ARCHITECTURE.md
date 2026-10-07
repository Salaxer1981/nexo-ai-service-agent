# Architecture

> **The LLM proposes; the backend authorizes and executes.**

**What the model does.** Grok returns one strict-JSON interpretation per turn: an intent plus draft fields. It has no
tools, no database connection, and no notion of who the customer is.

**What the backend owns:**
- **Identity:** from the bearer token only.
- **Data access:** read paths run in a PostgreSQL `READ ONLY` transaction.
- **Writes:** only through the existing services.
- **Confirmation:** a deterministic `CONFIRMAR` gate plus a version token.
- **Idempotency, audit, and truthful wording.**

## 1. Request path

```
Browser (React bundle; no credentials, no customer_id)
  │  POST /api/chat  {message, conversation_id?, confirmation_token?}   header X-Demo-Session: A|B
  ▼
web  (src/frontend/server/server.mjs, Node stdlib, 127.0.0.1:8080, network "web")
  │  allowlist: POST /chat, GET /health/ready only; drops browser Authorization/Cookie;
  │  adds  Authorization: Bearer <synthetic token A|B>  from its runtime environment
  ▼
backend  (FastAPI, uid 10001, 127.0.0.1:8000, networks internal + automation + web)
  │  sha256(token) → customer_id   ·   request_id / conversation_id   ·   one JSON audit line per request
  ├─► PostgreSQL 17 + pgvector (no host port; network "internal")
  ├─► OpenRouter (HTTPS): x-ai/grok-4.7 interpretation · openai/text-embedding-3-small embeddings
  └─► n8n 2.42.3 (network "automation") ─► POST /internal/leads (service credential) ─► PostgreSQL
```

## 2. Knowledge (RAG)

```
knowledge/*.md ── python -m app.rag_ingest ──► OpenRouter embeddings (1536 d) ──► pgvector (knowledge_chunks)
question ──► backend embeds query ──► cosine top-k ≥ 0.39 ──► sections as DATA ──► Grok answer (strict JSON)
         ──► grounding guard (citations + figures must come from the retrieved sections) ──► answer + references
```

**Indexing:**
- Each `##` section is one chunk. Its reference is `<file> § <section>`.
- Ingestion is atomic (all-or-nothing) and re-embeds only changed sections. The document version is the SHA-256 of
  its file.

**Answering safely:**
- **Below the threshold:** "no he encontrado información suficiente", with no model answer at all.
- **Retrieved text is data:** it's passed in the user turn, never in the system prompt, so injected instructions in a
  document authorize nothing.
- **Figures must be grounded:** an answer that cites an unretrieved source or a figure not in the sources is blocked.

**Ticket status never comes from RAG.** It comes from the ticket table (`business_api` source).

## 3. Ticket (confirmed action)

```
chat message ─► Grok proposes {intent: create_ticket, ticket: {contact, subject, description, priority}}
             ─► backend validates the draft ─► ticket service PREPARE (pending action, payload hash) ─► NO ticket yet
             ─► summary + confirmation_token = sha256("nexo:chat_confirm:v1:<action_id>:<payload_hash>")[:16]
UI "Confirm" ─► {"message":"CONFIRMAR","confirmation_token":<token of the summary shown>}
             ─► deterministic gate (whole message; NO model call) ─► token == current version? (under the conversation lock)
                   no  → confirmation_review_required: current summary shown again, nothing executed
                   yes → ticket service CONFIRM (idempotency key chat:<conversation>:<action>) ─► PostgreSQL
                         critical → pending handoff "critical_incident" (idempotent per ticket)
             ─► real T-reference + status from the committed row
```

**Version binding.** A correction re-prepares the action: the old version is superseded and a new token is issued. A
stale or missing token can never execute the new version. Cancelling is authoritative: success is reported only if the
action really moved from pending to cancelled; otherwise the backend reports `already_completed` or `cannot_cancel`.

**Lost response.** The create commits even if the client never receives the reply. Confirming again with the same token
replays the **same** ticket (idempotency key); it never creates a duplicate. This was validated on the VM by closing the
socket before reading the response, then retrying.

## 4. Lead (mandatory n8n)

```
chat ─► Grok proposes {intent: create_lead, lead: {company, contact, email, need}} (the e-mail must appear in the message)
     ─► leads PREPARE (no lead) ─► summary + token ─► UI "Confirm" ─► CONFIRMAR gate (no model call)
     ─► leads.begin_confirm (pending → confirmed) ─► HTTP POST n8n webhook (private network)
     ─► n8n workflow "nexo-lead-create" ─► POST backend /internal/leads (n8n service credential; customer tokens rejected)
     ─► the ONLY insert path for leads ─► PostgreSQL ─► n8n returns {lead_id, execution_id}
     ─► backend reads the row back ─► finish_confirm ─► "lead_created" + workflow execution id
```

**n8n down or failing.** The answer is 503 `lead_not_confirmed` ("no te digo que se haya creado"). The action stays
`confirmed`, and the chat keeps a pointer to it. Confirming again later completes the **same** action exactly once.

**The backend never inserts a lead itself.** It holds only the SHA-256 of the n8n service token; the raw token lives
only in n8n's encrypted credential store.

## 5. Handoff

```
explicit human request / data deletion / unsafe case ─► Grok intent request_human (+ reason)
critical ticket confirmed                              ─► automatic "critical_incident"
  ─► handoff service (idempotent key) ─► PostgreSQL handoffs(status = pending)
  ─► "pendiente de atención humana: todavía no lo ha recogido ninguna persona y no se garantiza un plazo"
```

No email or message is sent. The status is only ever `pending`: nothing claims that a person accepted it.

## 6. Identity, isolation and the evaluation client

- **Identity:** the backend resolves `customer_id` only as `sha256(bearer token)` → `customers`. Text, model output,
  headers and bodies never carry authority.
- **Isolation:** every read and write is owner-scoped. A foreign ticket and a nonexistent ticket get the same answer;
  the difference is recorded only in the audit (`denied_not_owner` / `not_found`).
- **Demo identity:** the web client's server-side boundary maps **demo session A or B** to the matching synthetic
  credential from its runtime environment. The browser, the JS bundle and the image hold none. Anyone who can reach the
  loopback web port acts as one of the two synthetic customers; that's by design, for evaluation only.

## 7. Reliability and failure behaviour

| Failure | Behaviour |
|---|---|
| OpenRouter timeout / 429 / 5xx | 503 `llm_unavailable`, `answer: null` |
| Malformed, truncated or extra-field output, or malformed usage metadata | 503 `llm_invalid_output` |
| Wrong served model | 503 `llm_model_mismatch` (no fallback models) |
| Database unavailable | 503 `database_unavailable`; readiness 503 |
| Write attempted on the read path | Refused by PostgreSQL (`READ ONLY`) → 503 |
| n8n down | 503 `lead_not_confirmed`; recoverable with the same action |
| Response lost after commit | Replay returns the same object (idempotency) |
| Container restart | Data in named volumes; services healthy again; validated |

## 8. Traceability

There's one JSON audit line per request. It carries:
- the request ID, conversation ID, customer, route and HTTP status;
- the intent, gate, command and outcome;
- the retrieval result and source IDs;
- for each model call: stage, served model and cost;
- the ticket lookup decision, the lead and workflow execution IDs, the idempotency-key fingerprint, the duration and
  the result.

A lead's chat line and the private writer's `/internal/leads` line share the **same request ID**, so the chain is:
message → retrieval → decision → confirmation → workflow → API → result. No secrets, message text, contact details or
model reasoning are logged.

## 9. Deployment and permissions (Docker)

**Images and runtime:**
- **Pinned images:** `pgvector/pgvector:0.8.7-pg17-bookworm`, `n8nio/n8n:2.42.3`, `python:3.12.15-slim-bookworm`,
  `node:22.16.0-alpine`. The web client's npm dependencies are locked.
- **Restart and health:** `restart: unless-stopped`, and every service has a healthcheck. The backend starts only after
  the database is healthy, and the web client only after the backend is.

**Users and privileges:**
- the backend runs as uid 10001, n8n as `node`, and web as `node` (read-only root, `cap_drop: ALL`,
  `no-new-privileges`);
- no container is privileged, and none mounts the Docker socket.

**Exposure:**
- Only loopback ports are published (8000, 5678, 8080); the database has none. Docker-published ports bypass `ufw`,
  which is why only loopback is used.
- Admin access to n8n goes through an SSH tunnel; n8n's owner account is created by the operator.

**Data sent to external services (OpenRouter / xAI):**
- the user's message;
- retrieved knowledge sections;
- minimal conversation context.

**Never sent:** customer IDs, tokens, database credentials or ticket rows.

## 10. Where to read more

- **Agent and actions design:** `evidence/11-agent/architecture.md`, `evidence/12-agent-actions/architecture.md`,
  `evidence/12-agent-actions/agent01bf{1,2,3}/root-cause-and-design.md`.
- **RAG design and calibration:** `evidence/10-rag/architecture.md`, `evidence/10-rag/calibration.json`.
- **Web runtime:** `src/frontend/README.md`, `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md`.
