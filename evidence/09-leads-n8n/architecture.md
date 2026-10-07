# APP-03B — Confirmed lead creation through n8n

Status: **local PASS** (220 tests; real PostgreSQL 17.11). The n8n hop is exercised locally with `FakeN8n`, a labelled
test stand-in, **not** n8n. **Real n8n execution = VM phase (pending).** HIGH RISK → independent audit before VM promotion.

## Requirement interpretation (PDF authoritative)
| Requirement | Source | Implementation |
|-------------|--------|----------------|
| Lead fields: company_name, contact_name, contact_email, need, generated id | REQ-API-03 (§6) | exactly these four fields + uuid; nothing else collected |
| Collect company, contact, need, **contact channel** | REQ-LEAD-01 (§4C) | the channel = `contact_email` (the only channel field the PDF specifies); no phone etc. invented |
| Request confirmation, then create **through n8n** | REQ-LEAD-02, REQ-CONF-03 (§4C) | prepare → confirm → n8n workflow → private write |
| Lead creation must pass through a workflow | REQ-RESP-03, REQ-N8N-01 (§3) | the only lead INSERT is behind the n8n service credential (see below) |
| API validates permissions, data, idempotency; stores records | REQ-RESP-04, REQ-API-02, REQ-IDEMP-01/02 | backend validates at prepare, confirm **and** private write |
| Don't promise discounts / prices / dates | REQ-LEAD-03 | API wording: "No price, discount, contract or date has been committed" |
| Workflow export without credentials | REQ-N8N-02 | `n8n/workflows/nexo-lead-create.json` references credential `nexo-lead-writer` by id/name only |
| Example addresses (`luis@example.test`) | REQ-API-03 | all tests/evidence use `@example.test` |
| **Authentication for leads: not specified** | — | **Decision (minimum safe prototype):** `/leads/prepare` and `/leads/confirm` require one of the existing test sessions (no anonymous write surface); the session is stored as `requested_by_customer_id` for isolation and audit. It isn't a customer relationship and isn't a lead field. A production system would use prospect sessions plus rate limiting |

## Flow and trust boundaries

```
 customer session (Bearer CUSTOMER_x)             private Docker network "automation"
 ─────────────────────────────────────            ──────────────────────────────────────────────────────────
 POST /leads/prepare ──► pending_lead_actions(pending)
 POST /leads/confirm ──► verify exact fingerprint, bind SHA-256(Idempotency-Key), status → confirmed
                     ──► POST http://n8n:5678/webhook/nexo-lead-create  {action id, key, payload_hash, lead}
                                         │  n8n workflow "nexo-lead-create":
                                         │   Webhook → "Envelope complete?" (IF) → HTTP Request → Respond
                                         ▼
                         POST http://backend:8000/internal/leads
                           Authorization: Bearer <n8n lead-writer token>   (credential stored in n8n only)
                           Idempotency-Key: <same key>   X-Request-ID: <same request id>
                           body: {action id, payload_hash, lead, workflow_execution_id = $execution.id}
                                         │  backend re-verifies: service credential (scope lead_write),
                                         │  action CONFIRMED, key matches, payload fingerprint matches
                                         ▼
                         ONE transaction: INSERT leads + action → consumed
 POST /leads/confirm ◄── reads the lead back FROM POSTGRESQL; success only if the row exists
```

- **Customer → backend:** customer bearer token (APP-01). Customer tokens are looked up in `api_credentials` only.
- **Backend → n8n:** private webhook on the `automation` network (not exposed beyond `127.0.0.1:5678`). Unauthenticated
  by design: the webhook can't create anything on its own, because the private write requires a *confirmed* action
  with the bound key and identical payload.
- **n8n → backend private write:** dedicated machine credential `n8n-lead-writer`, scope `lead_write`, stored in
  `service_credentials` (a different table, so customer tokens can never match). The backend receives **only the
  SHA-256** (`LEAD_WRITER_TOKEN_SHA256`). The raw token exists only in n8n's encrypted credential store. So the
  backend cannot impersonate n8n.
- **n8n → database:** impossible. n8n isn't on the `internal` network (N8N-01V1 proved `db` doesn't resolve from n8n),
  and the workflow has no database node.

## Why `/internal/leads`
The PDF's `POST /leads` capability is adapted (REQ-API-01 allows documented route changes) into
`/leads/prepare` + `/leads/confirm` (public, session) and **`/internal/leads`** (private, service credential). The
`internal` prefix marks the route as machine-to-machine: it isn't part of the public contract and is useless without
the n8n credential. There is **no** public `POST /leads` (tested: 404/405).

## State machine (`pending_lead_actions.status`)
`pending` →(confirm: fingerprint verified, key hash bound)→ `confirmed` →(private write, same txn as INSERT)→ `consumed`;
`pending` → `superseded` (re-prepare in the same conversation) | `expired` (30-min TTL). `confirmed` doesn't expire, so a
retry with the same key can always resume after an outage. A different key on a `confirmed` action → 409
`confirmation_in_progress`.

## Idempotency (one identity end-to-end)
The client's `Idempotency-Key` is bound (as SHA-256) to exactly one action at confirm (`UNIQUE (session, key hash)`),
forwarded unchanged by n8n, and re-checked by the private write. `leads.source_action_id` is `UNIQUE`, so there's one lead
per confirmed action. The raw key is never stored or logged (logs carry a 12-hex fingerprint).

## Failure / retry design
| Situation | Behavior |
|-----------|----------|
| n8n unreachable / timeout / 5xx | confirm reads PostgreSQL; no lead → **503 `lead_not_confirmed`**, action stays `confirmed`; same-key retry resumes |
| n8n can't reach `/internal/leads` | n8n answers 5xx → same as above |
| lead committed, response lost | confirm finds the committed lead → **201 replay**, same lead (`recovered_after_dispatch` in audit) |
| n8n delivers twice | second delivery → replay; one lead |
| workflow says success but no row | **502 `workflow_inconsistent`**, never success |
| workflow/backend reject (e.g. altered payload) | **502 `workflow_rejected`** (+ `upstream_code`), no lead |
| DB error inside the private write | transaction rolled back (no lead, action stays `confirmed`), retryable |

The action is never marked `consumed` before the lead row is committed in the same transaction, so nothing is
"used up" by a failed hop.

## Traceability
- `lead_prepare`, `lead_confirm` (session side): request_id, conversation_id, pending_action_id, `idempotency_key_fp`,
  `n8n_status`, `n8n_error`, `confirmation_result`, `idempotency`, `lead_id`, `workflow_execution_id`, duration.
- `lead_write` (private side): **same request_id** (n8n forwards `X-Request-ID`), `service: n8n-lead-writer`,
  pending_action_id, `idempotency_key_fp`, `workflow_execution_id` (= n8n `$execution.id`), lead_id, outcome.
- `leads.workflow_execution_id` persists which n8n execution delivered the write.
- Never logged: bearer tokens, the service token, DB password, raw Idempotency-Key, e-mail/company/need text (tested).

## VM proof plan (pending; not executed)
1. Start db + backend + n8n (N8N-01 config) with VM-generated secrets: customer tokens, DB password, n8n encryption key,
   and a random lead-writer token whose **SHA-256** goes to the backend env.
2. Create n8n credential `nexo-lead-writer` (Header Auth `Authorization: Bearer <token>`) with the supported CLI
   (`n8n import:credentials`), then import `nexo-lead-create.json` (`n8n import:workflow`) and activate/publish it via CLI.
3. Run the journey via `127.0.0.1:8000`: prepare → confirm → expect 201 with `workflow_execution_id` = a **real n8n
   execution id**; show the n8n execution (`n8n export`/executions list), the backend `lead_write` audit line with the same
   request_id, and the PostgreSQL row with the same `workflow_execution_id`.
4. Negative proofs: customer token on `/internal/leads` → 401; webhook call for an unconfirmed action → no lead; n8n
   stopped → 503 and no lead, then restart + same-key retry → one lead.
5. Secret hygiene (0 occurrences), full cleanup.
Uncertainties to resolve on the VM (n8n 2.42.3 specifics): credential import format, activation/publish CLI command,
IF/Respond node parameter schema, `$execution.id` format.
