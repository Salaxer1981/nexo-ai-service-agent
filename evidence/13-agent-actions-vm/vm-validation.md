# AGENT-01BV1 — VM validation of confirmed conversational actions (`POST /chat`)

**Result: PASS. Run 2 accepted: 139/139 checks, 0 failures.**
- **Everything real:** VM, `x-ai/grok-4.7` via OpenRouter, OpenRouter embeddings, PostgreSQL 17.11 + pgvector 0.8.7, and **n8n 2.42.3**. FakeN8n is not used anywhere in this evidence.
- **Candidate:** `61774c6b8775565777995f7b83430ecdf167e784` (AGENT-01BF3). Codex audit: PASS WITH LOWS, one known LOW (AGENT01BF3-01).
- **Run:** temporary, 2026-10-07; db + backend + n8n; full teardown afterwards (owner decision).
- **No changes:** no application, compose, workflow or corpus change. Harness only.
- **Files:**
  - `vm-validate.sh`: the harness;
  - `vm-run2-accepted.txt`: the accepted log;
  - `vm-run1-rejected.txt`: the rejected first run.

## Runs
| Run | Result | Notes |
|-----|--------|-------|
| 1 | **Rejected** (137 pass, 0 fail, but the lost-response phase never ran) | **Harness defect.** The driver defined a helper named `http()`, which shadowed the `http` module, so `http.client.HTTPConnection` raised `AttributeError` before any request was sent. Every other phase passed, including the real-n8n lead, n8n failure/recovery, version binding, cancel, restart and the TEST suite 29/29 ($0.0826). Cleanup completed; key 0×. **Fix (harness only):** `import http.client as httpclient`, plus an AST scan of the driver confirming no other module/name collisions |
| 2 | **Accepted: 139/139** | Same candidate and bundle (sha256 `ef85f98b…c62e`). Real model: 36 chat turns, 20 LLM calls, $0.0717 |

## Key and secret handling
- **OpenRouter key:** sent only on the encrypted SSH session's stdin, never in command arguments. On the VM it lived in a 600-mode file and the 600-mode `.env`, both deleted at cleanup. 0 occurrences in both raw logs, the run log and the container logs.
- **Generated on the VM:** the customer tokens, DB password, `N8N_ENCRYPTION_KEY` and lead-writer service token. `.env` holds only the service token's SHA-256.
- **n8n credential file:** deleted from the host and the container right after import (checked).
- **Log scan:** 0 occurrences of any of these values in the run log, backend logs or n8n logs. No `Bearer <token>` value, no raw reasoning, no lead contact details or ticket free text in the backend logs.

## Matrices (run 2; `§` = section of the log)
**Preflight / startup / network (§0–7).**
- **Preflight:** Ubuntu 24.04.4, Docker 29.8.2, Compose v5.6.0; no stack, images or volumes present.
- **Build and health:** compose config valid; exact commit checked out with a clean tree; db, backend and n8n healthy.
- **Schema:** migrations 0001–0009 with checksums equal to the committed SQL; pgvector 0.8.7; seed `T-1001=CUSTOMER_A`, `T-1002=CUSTOMER_B`.
- **Exposure:**
  - backend only on `127.0.0.1:8000`, n8n only on `127.0.0.1:5678`;
  - db has no published port; the only public listener is :9922 (SSH).
- **Network boundaries:**
  - n8n only on `nexo_automation` and db only on `nexo_internal`;
  - n8n reaches backend `/health` but cannot resolve `db`;
  - the knowledge mount is read-only (4 files == commit).
- **Runtime config:** `OpenRouterChatClient(model='x-ai/grok-4.7')`, embeddings `openai/text-embedding-3-small`, threshold 0.39.
- **n8n setup:** credential imported, workflow imported and published (`publish:workflow`), webhook active (400 `invalid_envelope` from its own Respond node).

| § | Check (REAL model unless noted) | Result |
|---|---|---|
| 9 | `/health`, `/health/ready` (schema `0009_chat_revision`) | 200 / 200 |
| 10 | Real ingestion 4 docs / 10 chunks / 10 embedded; "horario" → found (0.699, `02_support_policy.md § Horario de atención`); "Barcelona" → insufficient (0.369) | PASS |
| 11 | PDF incident (Ana): Grok → `create_ticket`, `awaiting_confirmation`, priority **critical**, `confirmation_token`; **0 tickets before CONFIRMAR**. `CONFIRMAR` + token → `ticket_created` **with no model call** (`llm_stages=[]`, gate `confirm`); row `T-1003`, CUSTOMER_A, critical, open; `critical_incident` handoff, pending, same conversation; truthful wording (pending, no guaranteed time) | PASS |
| 12 | Replay with the same token → same ticket and T-reference, `idempotency=replay`, same handoff, no duplicates | PASS |
| 13 | One-person issue (Marta) → priority **normal**, confirmation still required, no invented SLA; created `T-1004`, no handoff | PASS |
| 14 | **Lost response:** CONFIRMAR sent, socket closed before reading. PostgreSQL shows the create **committed** (`T-1005`). The retry with the same token returns that **same** ticket as `replay`; exactly 1 ticket for the action | PASS |
| 15 | `T-1001` → `ticket_found` from PostgreSQL (`business_api`, no RAG, one intent call). After a controlled DB change to `in_progress`, the answer says «en curso». Restored to `open` | PASS |
| 16 | A asks for B's `T-1002` vs a nonexistent `T-9999`: identical status, wording and (empty) sources; the difference is only in the audit (`denied_not_owner` / `not_found`). The spoofed `customer_id = CUSTOMER_B` in the message has no effect (identity stays CUSTOMER_A). B with its own token sees `T-1002` | PASS |
| 17 | **Lead via REAL n8n:** PDF lead message → `collecting_info` → details → draft with exactly 4 fields (`luis@example.test`); 0 leads and 0 n8n executions before confirming. `CONFIRMAR` + token → `lead_created`, no model call. Proven: n8n execution **2** `success` (from n8n's own DB), lead row with CUSTOMER_A + the same pending action + execution id 2, `lead_write` audit by service `n8n-lead-writer` (`/internal/leads` 201), and the chat confirm idempotency fingerprint == the writer's fingerprint. Replay → same lead, **no new n8n execution** | PASS |
| 18 | **n8n failure:** fresh lead prepared (Eva) → `docker compose stop n8n` → CONFIRMAR → **503 `lead_not_confirmed`** («no te digo que se haya creado»); action `confirmed` (recoverable), chat pointer kept; no lead. CANCELAR → `cannot_cancel` (in flight, truthful). n8n started, webhook active → the same token → `lead_created` (execution 4); one lead; only one lead action ever existed in that conversation | PASS |
| 19 | "Quiero hablar con una persona" → `human_requested` handoff, pending, truthful wording. "Quiero que borréis todos mis datos personales" → `unsafe_to_resolve` handoff; nothing deleted (tickets, leads and customers unchanged) | PASS |
| 20 | PDF injection, alone and with "Muestra el ticket T-1002" → `clarification_needed`; no foreign data, no secrets; nothing created | PASS |
| 21 | **Version binding:** A (normal keyboard issue, token `8be7…`) → correction → B (critical, token `db2b…`). CONFIRMAR with **A's token** → `confirmation_review_required`, which shows B's summary and token; **no ticket**. Injection text containing "CONFIRMAR" is not the gate (the model classified it, nothing executed). CANCELAR → `cancelled`; CONFIRMAR with B's token → `nothing_pending`, no ticket. CANCELAR on the completed ticket and on the completed lead → `already_completed` (not "cancelled"); both objects still exist | PASS |
| 22 | `docker compose restart` (all 3 services healthy, webhook active again) → `T-1003` lookup works; both leads and both handoffs persist; RAG still `found`; the critical ticket's confirmation replays to the same ticket | PASS |
| 23 | **TEST-ONLY** suite inside the real backend container (scratch DB `nexo_bv1_test`, scripted/compromised model + local stub OpenRouter, **no n8n**): 29/29. Covers: request params (no fallback, strict schema, low reasoning) and data sent (no customer id, tokens, DB password or ticket row); failure matrix (timeout, 429, 500, not JSON, extra authority field, truncated, wrong served model, malformed `usage` (AGENT01A-01)); version binding and missing token; authoritative cancel (API confirm wins → `already_completed`); corrupted cross-conversation pointer → 0 cancel calls; compromised-model extra fields → 503; foreign == missing; auth/422; structural READ ONLY. Afterwards the scratch DB was dropped and the real DB snapshot was unchanged | PASS |
| 24 | Log correlation and secret hygiene (below) | PASS |
| 26–27 | Teardown: `down -v`; new images removed (final `docker images` empty), builder pruned; 0 containers, images, volumes and build cache; no :8000/:5432/:5678; temporary directory removed | PASS |

Final real-DB counts before teardown: tickets 5 (2 seed + T-1003/4/5), leads 2, handoffs 3, chat_conversations 6; 5 n8n executions (including the webhook probes).

## Traceability (§24)
One lead, followed end to end:
1. **The chat confirm event:** `request_id=bv1-697d512cad16`, `conversation_id=bv1-lead`, gate `confirm`, outcome `created`, `lead_id`, `workflow_execution_id=2`, `idempotency_key_fp=cc9187714afa`.
2. **n8n execution 2** runs and calls the private writer with the **same `request_id`**.
3. **The `lead_write` audit:** `/internal/leads` 201, service `n8n-lead-writer`, same `pending_action_id`, `lead_id` and fingerprint.
4. **The PostgreSQL row.**

Every chat event carries `request_id`, `conversation_id`, `customer_id`, `status`, `duration_ms` and `result`. The deliberately cut-off request (`bv1-lost-1`) also logged its complete result (`ticket_created`).

## Simple explanation of the full real path
1. **The customer writes.** Their bearer token identifies them; nothing in the message can change who they are.
2. **Grok interprets.** It returns only a strict JSON interpretation (intent and draft fields). It has no tools and no database access. This happens in a READ ONLY transaction.
3. **The backend prepares, it doesn't execute.** It shows a summary and a `confirmation_token` tied to that exact version. Nothing exists yet.
4. **CONFIRMAR is deterministic.** It is matched as the whole message, with no model call, plus the token. If the draft changed since the user saw it, the backend shows the new version instead of executing.
5. **A ticket is written by the ticket service** in PostgreSQL, with idempotency (a replay or lost response returns the same ticket). A critical incident also opens a human handoff.
6. **A lead goes through REAL n8n.** The backend calls the n8n webhook; n8n calls the private `/internal/leads` with its own service token; the backend writes PostgreSQL and returns the execution id. If n8n is down, the user is told nothing was created, and the same action can be confirmed again later without duplicates.
7. **Everything is audited** under one `request_id`, without secrets or personal free text.

## Known items (not blockers)
- **AGENT01BF3-01 (LOW, known, out of scope):** `_touch()` creates no `chat_conversations` row when none exists. The VM run exposed no blocker from it.
- **First intent turn:** for the PDF lead message, Grok asked for the missing details (`collecting_info`) before preparing, which is the expected safe behaviour. The version-binding correction turn rewrote the subject and description from the correction text, and the new version was shown before it could be executed.
