# AGENT-01B — Stateful confirmed actions from chat

Labels used in this evidence:
- **REAL PostgreSQL** 17.11 + pgvector 0.8.7 (local);
- **FakeN8n** = a TEST-ONLY local stand-in that calls the real private `/internal/leads` with the service credential.
  It is NOT n8n; real n8n is proven only in VM validation;
- **REAL OpenRouter model** = `x-ai/grok-4.7` (opt-in live smoke).

No real-n8n agent end-to-end claim is made here.

## 1. Requirement interpretation (PDF wins)
| PDF | Implementation |
|-----|----------------|
| §4B incident: collect data, classify and suggest priority, show a summary, ask for confirmation before creating; return the real id; API failure ⇒ don't claim creation; changed data ⇒ ask again | chat collects the 4 `TicketDraft` fields (contact_name, subject, description, priority); the model suggests the priority using the KB policy; backend `ticket_actions.prepare` stores the exact draft; the summary shown is built from the stored values; only the literal **CONFIRMAR** runs `ticket_actions.confirm`; the real id + `T-` reference are returned; failures answer "not confirmed" (503) with exactly-once retry; changed data ⇒ re-prepare (old version superseded) |
| §4C lead: company, contact, need and contact channel; confirmation; create via n8n; no discounts/prices/dates | exactly the 4 approved fields (channel = e-mail, which must be literally typed by the customer); CONFIRMAR ⇒ `leads.confirm_via_workflow` = the same code as `POST /leads/confirm` (n8n → `/internal/leads` → PostgreSQL); the summary and answer say no price/discount/contract/date is committed |
| §4D «¿En qué estado está mi ticket T-1001?»; customer_id in chat ≠ authentication | short immutable references (`T-1001`…), resolved ONLY within the authenticated customer's tickets (R-14 resolved) |
| §4E escalation: critical incident, explicit human request, or case that can't be resolved safely; persist as pending; never claim a person is attending | `handoffs.create` (APP-03A) with reasons `critical_incident` (backend, after a critical ticket is confirmed), `human_requested` / `unsafe_to_resolve` (model enum); APP-03A's truthful wording; **no confirmation** (the PDF requires it only for tickets and leads) |
| §5 support policy: total company outage ⇒ critical; one person not fully blocked ⇒ normal; critical incidents escalated to a human; no resolution time guaranteed | the policy text is in the interpretation prompt; the priority is shown in the summary and confirmed by the user; on confirmation of a `critical` ticket a `critical_incident` handoff is created (idempotent per ticket); no SLA wording anywhere |

## 2. Command/query separation
```
POST /chat (Bearer → customer_id; conversation_id from body/header or generated)
 ├─ message is exactly CONFIRMAR/CONFIRM/CANCELAR/CANCEL (trim + casefold)?  ── deterministic GATE, NO model call
 │      └─ chat_actions.confirm / cancel   (COMMAND, write)
 └─ otherwise: READ-ONLY session (PostgreSQL READ ONLY)
        ├─ load conversation state + context (customer's own collected values)
        ├─ LLM interpretation → {intent enum, ticket{4 nullable}, lead{4 nullable}, handoff_reason enum|null}
        │      re-validated field by field (API draft rules; e-mail must be typed by the customer; extra keys ⇒ 503)
        ├─ knowledge_question → RAG (unchanged, read-only)
        ├─ ticket_status      → tickets service by UUID or T-reference, customer-scoped (read-only)
        └─ create_ticket / create_lead / request_human → ActionProposal (no ids, no keys, no identity)
               └─ chat_actions.propose (COMMAND, write): collect → ticket_actions/leads.prepare | handoffs.create
```
- The READ side never receives a write-capable connection.
- The LLM never receives any connection, id or key.
- `chat_actions` is the only chat code that writes, and only through the existing services:
  - `ticket_actions.prepare/confirm/cancel`;
  - `leads.prepare/confirm_via_workflow/cancel`;
  - `handoffs.create`.

## 3. Conversation state (resolves R-39 minimally)
`chat_conversations`, PK `(customer_id, conversation_id)`. Another customer reusing a conversation id gets a different row.
| Column | Meaning |
|--------|---------|
| `collecting_kind`, `draft` | the fields collected so far for an action that is **not prepared yet** (customer's own values; cleared when prepared or cancelled) |
| `action_kind`, `action_id`, `action_payload_hash`, `action_status` (pending/completed/cancelled) | a **pointer** to the prepared action; the authoritative payload stays in `pending_*_actions` |
No transcripts or model output are stored. CHECK constraints keep the pointer all-or-nothing, and keep a draft only
while collecting.

## 4. Confirmation protocol
1. The agent shows the exact stored summary and says «Para ejecutarlo responde CONFIRMAR. Para descartarlo, responde CANCELAR.»
2. Only the **whole** message `CONFIRMAR`/`CONFIRM` (case-insensitive, trimmed) is a confirmation. «vale», «sí», «ok»,
   «CONFIRMAR!», «confirmar por favor» and «CONFIRMAR <anything>» are not; those go to the model, which has no confirm
   field and can at most re-show the pending action.
3. On CONFIRMAR, under the conversation's advisory lock:
   1. authenticated customer;
   2. this conversation's state;
   3. the pointed action;
   4. if the action tables show any **other** pending action in this conversation, nothing is executed (`action_ambiguous`);
   5. the existing confirm service, with the deterministic key `chat:<conversation_id>:<action_id>` (customer-scoped by the
      services), which re-checks ownership, status, expiry and payload fingerprint;
   6. the authoritative created object is returned.
4. Nothing pending ⇒ `nothing_pending`, no mutation, no model call.

## 5. Idempotency and failures
- **Lost response:** CONFIRMAR again → same key → existing replay semantics → **same ticket/lead** (ticket:
  `idempotency_keys`; lead: `confirm_key_sha256` + `UNIQUE source_action_id`). A critical ticket's handoff key is
  `chat-ticket-handoff:<ticket_id>`, so it is also replayed. A human handoff's key is `chat-handoff:<conversation>:<reason>`;
  another wording in the same conversation gets "already pending" with the same id.
- **DB failure after the ticket commit:** 503 `action_not_confirmed` ("no te digo que se haya creado"); the next CONFIRMAR
  replays the same ticket.
- **n8n down:** 503 `lead_not_confirmed` (honest); the action stays `confirmed` and can't be cancelled; the next CONFIRMAR
  resumes with the same key.
- **n8n committed but its answer was lost:** recovered from PostgreSQL.
- **Workflow rejected:** "no se ha creado nada".
- **Expired, superseded or cancelled action:** `confirmation_invalid`, nothing created.
- **LLM down:** 503 `llm_unavailable` before any prepare.
- **DB down:** 503 with a truthful message.

## 6. Cancellation and re-prepare
- **CANCELAR (deterministic):** cancels every `pending` ticket/lead action of this customer + conversation through new
  owner-scoped service functions (`status='cancelled'`, a new terminal state in migration 0008). The existing confirm
  logic rejects every status other than `pending`, so a cancelled action can never be confirmed: not from chat and not
  from the plain API (tested). A lead already handed to n8n (`confirmed`) can't be cancelled (truthful answer).
- **Changed data:** the merged values are re-prepared through the existing prepare, which supersedes the previous pending
  action of the conversation; the old version can't be executed (tested via the API too). The same data sends nothing new.
- **Never** is an already-created object modified by chat.

## 7. Model trust boundary
| The model may propose | The backend owns |
|-----------------------|------------------|
| intent (6-value enum); ticket/lead candidate values (each validated with the API's draft rules; e-mail must appear in the customer's message); handoff reason `human_requested` / `unsafe_to_resolve` | authenticated customer; conversation state; which action; validation; **confirmation (gate)**; service selection (fixed mapping, no dynamic dispatch); idempotency keys; `critical_incident` escalation; handoff summary (built from the customer's own words); all DB and n8n execution |

Any extra key, at the top level or inside `ticket`/`lead`, returns 503 `llm_invalid_output` with no side effect (tested):
`confirmation`, `confirm`, `customer_id`, `action_id`, `pending_action_id`, `idempotency_key`, `tool`, `url`, `sql`,
`ticket_id`, `lead_id`. So does a reason outside the enum.

## 8. Short ticket references (R-14)
The PDF's journey D uses «T-1001», and §6 asks for at least one ticket per customer. Migration 0008 adds
`tickets.reference`:
- **Format:** `T-` + a sequence starting at 1001. Existing tickets are numbered by creation, so seed A = **T-1001** and
  seed B = **T-1002**.
- **Integrity:** UNIQUE, CHECK on the format, and immutable (trigger).
- **Lookup:** `tickets.resolve_reference(ref, customer_id)` searches only the customer's tickets. Another customer's
  reference looks exactly like a nonexistent one; the audit alone distinguishes `denied_not_owner` / `not_found`.
- **Ownership:** the UUID ownership check (`get_owned_ticket`) is unchanged and still applied.
- **API:** the HTTP API responses are unchanged. Chat answers show both the reference and the UUID.

## 9. AGENT01A-01 (LOW) closed
`llm.parse_completion` now validates optional `usage` metadata:
- an object;
- non-negative integer token counts (bool rejected);
- a finite non-negative cost;
- a `completion_tokens_details` object.

Anything else is `llm_invalid_output` (503), never a 500. Focused tests cover 11 malformed shapes plus the well-formed
and absent cases.

## 10. OpenRouter data boundary
- **Sent:** the user's message, and the `context` (the action being collected and **the customer's own previously
  supplied values**, so corrections can be merged); for knowledge answers, accepted public passages.
- **Not sent:** authenticated identity, tokens, DB or service credentials, ticket rows, pending action ids, payload
  hashes, idempotency keys.
- **Confirmation and cancellation turns send nothing at all** (no model call).
- An e-mail address or UUID the user types travels inside their message.

## 11. Audit (safe facts only)
Per turn:
- request_id, conversation_id, customer_id; message length + fingerprint;
- intent, `gate`, `chat_command` (prepare/confirm/cancel/handoff), `outcome`;
- `action_kind`, `action_fp` (sha256 prefix of the action id), `idempotency_key_fp` (never the raw key);
- created `ticket_id`/`ticket_reference`, `lead_id` + `workflow_execution_id`, `handoff_id`;
- the service outcome, missing/rejected field names, model usage/cost/ms.

Never logged: secrets, Authorization, raw keys, lead contact details, ticket or lead free text, raw messages, reasoning
(tested).
