# Project State — Nexo AI Service Agent

> Factual state only. No secrets. Last updated: 2026-10-07 (FINAL-02).

## Repository

| Item | Value |
|------|-------|
| Local path | `C:\Users\User\Desktop\nexo-ai-service-agent` |
| Branch | `main` |
| HEAD | FINAL-02 commit (`FINAL-02: record permanent VM deployment, final evidence and final report`); deployed commit on the VM: `16c587f` (application code = `85781cf`). See `git log` for the SHA |
| Remote | none configured; nothing pushed |

## Phase history

| Phase | Status | Evidence |
|-------|--------|----------|
| PRE-01 — Repository bootstrap + read-only VM preflight | **PASS** (`2ac0865`) | `evidence/00-preflight/` |
| PRE-02 — VM Docker runtime provisioning | **PASS** (`2b396a6`) | `evidence/01-docker/` |
| FOUNDATION-01 — FastAPI + PostgreSQL Compose stack | **PASS** (`5926469`): local static + app level | `evidence/02-foundation/` |
| FOUNDATION-02 — VM container runtime + persistence validation | **PASS** (`cda8022`): 22/22 runtime checks on the VM; temporary, fully cleaned up | `evidence/03-foundation-runtime/` |
| APP-01 — Schema/migrations, synthetic customers, authenticated identity, ticket authorization | **PASS (local, real PostgreSQL 17.11)** (`2a0d2e5`): 60/60 tests; container runtime of the new image **not yet re-validated on VM** | `evidence/04-business-api/` |
| DOCS-01 — Official assessment PDF + canonical requirements text | **DONE** (`fe394bc`); B-06 resolved | `docs/` |
| APP-02 — Confirmed, idempotent ticket creation (**HIGH RISK**) | Local PASS (`9ef9823`); independent Codex audit: BLOCKER 0, **HIGH 1 (APP02-01)**, MEDIUM 0, LOW 1, INFO 3 | `evidence/05-ticket-create/` |
| APP-02F1 — Targeted fix for APP02-01 | PASS (`1284f98`): 115 passed, 1 opt-in skipped (×3); concurrent-prepare tests 10/10 runs. **Codex focused re-audit: PASS / SAFE FOR VM VALIDATION; APP02-01 CLOSED** (final: BLOCKER 0, HIGH 0, MEDIUM 0, LOW 1, INFO 3) | `evidence/05-ticket-create/app02f1/` |
| APP-02V1 — Temporary VM runtime validation of `1284f98` | **APP-02 = VM_VALIDATED**: run 2 **80/80 checks PASS** (run 1 PARTIAL due to a validation-script log-capture defect, kept as evidence); fully cleaned up; not a permanent deployment | `evidence/06-app02-runtime/` |
| APP-03A — Idempotent human handoffs (**HIGH RISK**: authenticated idempotent write) | **PASS (local, real PostgreSQL 17.11)**: 147 passed, 2 opt-in skipped (×2); handoff tests 32/32 (×3); mutations H1–H5 caught. **Independent audit recommended before VM promotion** | `evidence/07-handoff/` |
| APP-03AF1 — Targeted fix for APP03A-01 (LOW) | **APP03A-01 = CLOSED** (focused Codex re-audit PASS); was FIXED_PENDING_REAUDIT: supplied-but-invalid `X-Conversation-ID` → 400 on `POST /handoffs`; 159 passed, 2 opt-in skipped (×2); new tests fail on the unfixed code (6/12) and pass with the fix. No VM validation of APP-03A yet | `evidence/07-handoff/app03af1/` |
| N8N-01 — Self-hosted n8n foundation (infrastructure only) | **Static validation PASS** (170 passed, 2 opt-in skipped; 23 compose checks). **Runtime validation PENDING**: `evidence/08-n8n-foundation/vm-validate.sh` prepared, not executed (needs explicit VM authorization) | `evidence/08-n8n-foundation/` |
| N8N-01V1 — Temporary VM validation of `e23679d` | **N8N-01 = VM_VALIDATED**: run 2 **32/32 checks PASS** (2026-10-07); run 1 didn't execute (CRLF in my script edit, VM unchanged). Fully cleaned up; not a permanent deployment | `evidence/08-n8n-foundation/vm-validation.md` |
| APP-03A runtime smoke (during N8N-01V1) | **PASS (smoke only)**: authenticated `POST /handoffs` → 201 `created`, `pending`; same key → `replay`, same ID; no false attendance wording; 1 DB row `pending`. Full APP-03A suite remains local-only | `evidence/08-n8n-foundation/vm-validation.md` |
| APP-03B — Confirmed lead creation through n8n (**HIGH RISK**) | **PASS (local, real PostgreSQL 17.11)**: 220 passed, 3 opt-in skipped (×2); lead tests 41/41 (×3) + 6 workflow static; mutations L1–L7 caught (L6 via DB backstop, L6b double mutation caught). n8n hop tested with a labelled FakeN8n only, **not proof n8n ran**. Independent Codex audit: **PASS WITH LOWS** (BLOCKER 0, HIGH 0, MEDIUM 0, LOW 3, INFO 3) | `evidence/09-leads-n8n/` |
| APP-03BV1 — Temporary VM validation with REAL n8n 2.42.3 | **APP-03B = VM_VALIDATED**: run 2 **106/106 PASS** (2026-10-07); run 1 105/106 (probe hit n8n webhook-registration lag; harness probe fixed, no app/workflow edits). Real execution IDs verified in n8n's DB; full cleanup | `evidence/09-leads-n8n/vm-validation-real-n8n.md` |
| RAG-01 — Referenced pgvector retrieval (retrieval only; **HIGH-ish**: external provider + migration + attribution) | **PASS (local)**: real PostgreSQL 17.11 + pgvector 0.8.7; 248 passed (+ opt-in); RAG mutations R1–R7 caught; **live OpenRouter embeddings smoke PASS**; threshold calibrated with the real model. Codex audit: **FAIL** (2 MEDIUM, 4 LOW, 2 INFO), fixed in RAG-01F1; not deployed | `evidence/10-rag/` |
| RAG-01F1 — Fix audit findings RAG01-01 (atomic + serialized ingestion) and RAG01-02 (source-bound references) | **PASS (local)**: 8 new real-PostgreSQL tests (6 fail on 43ead8d), mutations F1–F5 caught, 256 passed ×2; no live OpenRouter call. Codex re-audit: **PASS WITH LOWS**, RAG01-01 and RAG01-02 **CLOSED** | `evidence/10-rag/rag01f1/` |
| RAG-01V1 — Temporary VM validation of `fce4580` with REAL OpenRouter embeddings + REAL pgvector 0.8.7 | **PASS, 138/138**: migrations 0001–0007 + checksums, read-only canonical mount (4 files == commit), real ingestion 4 docs/10 chunks/1536 dims, re-ingest 0 embedded (byte-identical), 10 supported queries found, 6 no-evidence queries insufficient (Barcelona 0.369), reference chain API→rows→mounted file→commit blob, 120 €→150 € on a temporary copy (1 chunk re-embedded, then restored), model consistency, TEST-provider atomic smoke in a scratch DB, auth/input, traceability, 0 secrets in logs, loopback only, full cleanup. **RAG-01 = VM_VALIDATED**. Not permanently deployed | `evidence/10-rag/vm-validation.md` |
| AGENT-01A — Minimal READ-ONLY conversational agent `POST /chat` (**HIGH-ish**: first LLM in the request path, trust boundary) | **PASS (local)**: 318 passed (61 agent tests on real PostgreSQL + pgvector, TEST-ONLY scripted chat client), 11/11 safety mutations caught; **live OpenRouter smoke 14/14** (real `x-ai/grok-4.7` + real embeddings, $0.038; first run 12/13 documented). Codex audit: **PASS WITH LOWS** (5 LOW, 2 INFO); not permanently deployed | `evidence/11-agent/` |
| AGENT-01AV1 — Temporary VM validation of `aa1713b` (REAL Grok 4.7 + REAL embeddings + REAL PostgreSQL/pgvector) | **PASS, run 2: 129/129** (run 1 rejected: harness `sys.path` defect, harness-only fix, faithful dry run). 16 real turns ($0.0426): grounded answer with metadata sources; Barcelona insufficient with NO answer call; ticket status from PostgreSQL (and follows a DB change); foreign == missing; chat customer_id ignored; 3 action intents not executed (tables unchanged); PDF injection in message and in a retrieved temporary doc → no action/leak. In-container TEST suite 47/47: request params (no fallback, strict schema, low reasoning), data sent, failure matrix (timeout/429/5xx/malformed/truncated/wrong model), compromised model, READ ONLY enforced by PostgreSQL. Logs clean; loopback only; full cleanup. **AGENT-01A = VM_VALIDATED** | `evidence/11-agent/vm-validation.md` |
| AGENT-01B — Stateful confirmed actions from chat (**HIGH RISK**: chat now drives business mutations) | **PASS (local)**: migration 0008 (conversation state, `cancelled`, immutable customer-scoped `T-` references); command/query split (`chat_actions` = only writer, via existing services); deterministic CONFIRMAR/CANCELAR gate (no model call); 61 new + 60 updated agent tests, 378 full (8 opt-in skipped); mutations B1-B18 all caught (B17 after an added serialization test; run 1 killed by the memory reaper, leftover B12 mutation detected and restored); live Grok smokes 10/10 + 14/14 ($0.0998). FakeN8n only locally: **no real-n8n agent E2E claimed**. Codex audit: **FAIL** (2 HIGH: AGENT01B-01/02, 5 LOW, 3 INFO), fixed in AGENT-01BF1; not deployed | `evidence/12-agent-actions/` |
| AGENT-01BF1 — Fix AGENT01B-01 (confirmation bound to the exact approved version) and AGENT01B-02 (authoritative cancellation) | **PASS (local)**: `confirmation_token` echoed by the client and re-checked under the conversation lock; `chat_conversations.revision` (migration 0009) blocks stale model proposals; cancellation answered from the authoritative action state; pointer dereferenced with customer + conversation + action. 15 new deterministic race tests (14 fail on 8507448; both HIGHs reproduced semantically on the old code); mutations F1–F7 caught; 393 passed. No live call. Codex re-audit: AGENT01B-01/02 **CLOSED**; new AGENT01BF1-01 (HIGH) and AGENT01BF1-02 (LOW) fixed in AGENT-01BF2 | `evidence/12-agent-actions/agent01bf1/` |
| AGENT-01BF2 — Fix AGENT01BF1-01 (stale proposals vs authoritative action state) and AGENT01BF1-02 (cancel membership before mutation) | **PASS (local)**: `reconcile()` re-reads the pointed action (customer+conversation+action) before any proposal is published (consumed -> completed sync; confirmed lead -> pointer kept for retry; never replaced); confirm/cancel advance the revision before business mutation; CANCELAR proves membership before any cancel. 8 new deterministic tests (all fail on 0b4f6c8 for the semantic reason); mutations G1-G5 caught; 401 passed. No live call, no migration. Codex: FAIL with AGENT01BF2-01 (HIGH, TOCTOU) and AGENT01BF2-02 (LOW), fixed in AGENT-01BF3 | `evidence/12-agent-actions/agent01bf2/` |
| AGENT-01BF3 — Fix AGENT01BF2-01 (atomic authoritative check + re-prepare) and AGENT01BF2-02 (cancel validates pointer before any mutation) | **PASS (local)**: propose() = ONE transaction: prepare-group advisory lock -> pointed action SELECT ... FOR UPDATE -> recheck -> service prepare as savepoint -> publish -> COMMIT; model call outside any transaction; same lock order as the API prepare path (no deadlock, tested). CANCELAR: pointer validated -> revision advanced -> then any cancel. 7 new deterministic tests with observed lock waits (TOCTOU and X/Z reproduced on c693a5a); mutations H1-H5 caught; 408 passed. No live call, no migration. Codex re-audit: PASS WITH LOWS (AGENT01BF2-01/02 CLOSED; one LOW AGENT01BF3-01) | `evidence/12-agent-actions/agent01bf3/` |
| AGENT-01BV1 — Temporary VM validation of `61774c6` (REAL Grok 4.7 + REAL embeddings + REAL PostgreSQL/pgvector + REAL n8n 2.42.3) | **PASS, run 2: 139/139** (run 1 rejected: harness `http` module shadowed by a helper, lost-response phase not run; harness-only fix). 36 real turns ($0.0717): critical ticket (no ticket before CONFIRMAR; CONFIRMAR+token with NO model call; T-reference; critical_incident handoff; replay); normal ticket; lost response -> committed ticket replayed; T-1001 from PostgreSQL incl. controlled change; isolation (foreign == missing, customer_id spoof ignored, B sees own); lead through REAL n8n (execution id + private writer audit + row, replay no new execution); n8n stopped -> 503 lead_not_confirmed, cannot_cancel, recovery with same token, one lead; human + deletion handoffs; injection; version binding (A's token -> review with B); cancel vs completed; restart persistence; correlated logs, 0 secrets. In-container TEST suite 29/29. Full teardown. **AGENT-01B = VM_VALIDATED** | `evidence/13-agent-actions-vm/vm-validation.md` |
| UI-01 — Evaluation client rebuilt from the approved Stitch design NEXO_UI_FREEZE_01 (REQ-ARCH-06) | **PASS (local)**: Stitch project inspected read-only through the owner's authenticated Chrome (no credentials/cookies handled; screenshots only in the scratchpad); the freeze = the newest Customer View + Evaluator View pair, tokens read from the 'Sovereign Support' DESIGN.md. New `src/frontend` (React 19 + TypeScript + Vite; owner-authorized local npm packages, lockfile committed). Uses only `POST /chat`; confirmation_token kept in memory, never rendered, echoed unchanged with CONFIRMAR; Cancel = CANCELAR; success card only for HTTP 200 + persisted result; drawer closed by default and shows only real response fields (placeholders such as INC id, SLA, pipeline latency, fake names, ticket history and attachments removed). Demo identity via a dev/preview proxy that attaches the synthetic Bearer server-side (browser and bundle hold no credential). typecheck + lint + 11/11 tests + build PASS; visual check against Stitch (desktop, 820px, 390px) with a TEST fixture backend. No backend change, no model call. **Visual fidelity: PASS with documented contract deviations; backend integration: contract-tested with fixtures, real-backend browser E2E pending** | `evidence/14-evaluation-client/ui01/ui01-report.md` |
| UI-02 — Evaluator web runtime + REAL browser E2E of `ca86d7c` (owner's Chrome via the extension; VM: REAL PostgreSQL/pgvector, backend, REAL n8n 2.42.3, REAL OpenRouter x-ai/grok-4.7 + embeddings) | **UI-02 = BROWSER_E2E_VALIDATED; evaluation client = VALIDATED.** New `web` Compose service (npm ci + build; zero-dependency Node boundary `server/server.mjs`): proxies only POST /chat and GET /health/ready, attaches the synthetic demo Bearer server-side from its runtime env, drops browser credentials, CSP, read-only/non-root/no caps, 127.0.0.1:8080, own `web` network (cannot reach db/n8n). Browser E2E 23 scenarios PASS: RAG + absent, critical ticket (no ticket before confirm; CONFIRMAR+hidden token with 0 LLM calls; T-1003 + critical handoff), replay, version binding/review, cancel, normal ticket, lead through REAL n8n (exec id + private writer + 1 row), n8n down -> red Not completed -> same-action recovery, handoffs, T-1001, A/B isolation via the account card, injection, error state, drawer real-only, restart persistence, browser + image + log secret scan 0. Responsive 390/820 checked on identical code locally (TEST fixture; the automated window cannot be resized). Harness: run 1 lost to an SSH reset (cleaned with a verified v2 cleanup); run 2 28/28. 17/17 frontend tests; full teardown | `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md` |
| FINAL-01 — Delivery freeze: documentation, evaluator handoff, final gate | **Docs ready; delivery NOT yet complete.** New: evaluator-ready README, `docs/EVALUATOR_RUNBOOK.md`, `ARCHITECTURE.md`, `REQUIREMENTS_MATRIX.md` (all 116 IDs), `AUDIT_FINDINGS.md`, `TEST_EVIDENCE_SUMMARY.md`, `KNOWN_LIMITATIONS.md`, `AI_DISCLOSURE.md`, `TECHNICAL_REPORT_SOURCE.md`. Finding: 2 stale `tests/test_compose.py` expectations (pre-UI-02 service/network sets) failed at `85781cf`; updated to the validated topology + 2 new `web` static guards; backend suite **410 passed / 8 skipped**. VM address redacted from current files (present in 3 earlier commits, no credentials). Final secret scan: 0. No product code changed, no paid call. Remaining: persistent VM deployment (owner), PDF rendering, extra screenshots (n8n executions UI, records, restart, 120->150), backup/restore exercise, delivery email | `docs/` |
| FINAL-02 — Permanent evaluation deployment + final real evidence + final PDF | **PASS, 35/35; stack LEFT RUNNING on the VM** (`~/nexo-eval/repo`, `.env` 600, `restart: unless-stopped`, loopback-only; backups in `~/nexo-eval-backups`; n8n owner account created by the owner). Real: journeys (T-1003 + handoff, lead via n8n exec 1, human handoff); 120->150 at retrieval AND chat level + canonical restore; backend outage (502 Not completed) and PostgreSQL outage (503, badge Unavailable, data intact, self-recovery); pg_dump + n8n state backup, then pg_restore removing a post-backup record; full restart persistence; n8n UI executions; secret scan 0. New UI LOW UI02-04 (readiness badge checked at page load only). Final PDF `docs/report/Nexo_Technical_Report.pdf` (47 pages) | `evidence/15-final-deployment/final-deployment-report.md` |

## RAG retrieval (RAG-01)

| Item | Value |
|------|-------|
| Corpus | `knowledge/` = exactly the four PDF §5 documents (REQ-RAG-07, REQ-KB-01..04), text verbatim (tested), plus a metadata header (source_id, title, reference) and `##` section headings. The brief's suggested ticket-guidance doc was **not** created: not in the PDF (would invent facts) |
| Embeddings | OpenRouter `POST /api/v1/embeddings`, model `openai/text-embedding-3-small` (`RAG_EMBEDDING_MODEL`); **dimension verified live = 1536** before freezing the schema |
| Schema | migration `0007_knowledge` (current version): `CREATE EXTENSION vector`; `knowledge_documents` (source_id UNIQUE, title, reference, path, content_sha256, embedding_model); `knowledge_chunks` (chunk_key UNIQUE, ordinal, section, content, content_sha256, embedding_model, `embedding vector(1536)`), cascade delete. Exact cosine, no ANN index |
| Chunking | deterministic, one chunk per `##` section (paragraph grouping ≤1200 chars only for long sections, no overlap); chunk text `<title> — <section>` + body; key `<source_id>#<slug(section)>`; CRLF-insensitive |
| Ingestion | `python -m app.rag_ingest [--dir]` (container: `docker compose exec backend python -m app.rag_ingest`; corpus mounted read-only at `/srv/knowledge`). **All-or-nothing (RAG-01F1):** parse/validate all files → embed every new/changed chunk with NO transaction open → ONE transaction: `pg_advisory_xact_lock` (dedicated key from `sha256("nexo:rag_ingest:v1")`), re-read index under the lock, upsert docs/chunks, delete stale chunks and removed documents, final consistency check (exact chunk set, one model), single COMMIT. Provider or DB failure → previous index unchanged. Concurrent runs wait on the lock; each publication is one complete generation (last wins); if a concurrent run changed a needed chunk → rollback + re-plan (≤3). Prints counts only; idempotent |
| Retrieval | `POST /rag/search` (Bearer; query 1..500, top_k 1..5): embed query with the same model → `ORDER BY embedding <=> q` → score `1 - distance`; accepted iff ≥ `RAG_MIN_SCORE`; returns `evidence: found|insufficient`, matches with references, `best_score`, `model`. **No answer generated** |
| Threshold methodology | Real-model calibration (`evidence/10-rag/calibrate.py` → `calibration.json`, 10 chunks × 24 queries: 15 supported incl. paraphrases + English, 6 unrelated, 3 in-domain-absent). **0.39** = midpoint of highest non-supported score (0.369, "¿Tenéis oficina en Barcelona?") and lowest supported expected score (0.4195): supported 15/15 accepted, non-supported 0/9. Unrelated-only midpoint (0.33) rejected because it would accept an absent fact. Margin ~±0.03 (thin) |
| Reference format | `<file> § <section>` + `chunk_id` + `document_version` (doc sha256 prefix) + `chunk_sha256`; every reference resolves to an indexed chunk and a file whose sha256 = indexed version (tested). **Filename bound to the real file (RAG-01F1):** stored reference = `path.name`; front matter `reference:` must equal it or ingestion fails closed before any provider/DB work |
| Model consistency | each chunk stores `embedding_model`; search → 503 `index_model_mismatch` if the index mixes models or ≠ the configured model; column type rejects other dimensions; empty index → 503 `index_not_ready` |
| Failures | no key → 503 `rag_unavailable` (no silent fake); provider down → 503 `embedding_unavailable`; DB down → 503; ingestion provider failure leaves the old index intact |
| Traceability | `rag_search` audit: request_id, conversation_id, customer_id, query_length, query_fp (not the raw query), model, result, accepted, best_score, chunk_ids, source_ids, duration |
| Live smoke | **PASS** (2026-10-07): model exists, 1536 dims, batch order preserved, real ingest 10 chunks into pgvector, re-ingest 0 embedded, known query → `02_support_policy.md § Horario de atención` 0.6988, unrelated → insufficient (0.1674). Total live usage for dimension probe + 2 calibrations + smoke: a few thousand tokens (≪ $0.01) |
| VM validation | **VM_VALIDATED** (RAG-01V1, 2026-10-07): see `evidence/10-rag/vm-validation.md`. Key transfer: SSH stdin only → 600-mode file → deleted |
| Local tooling | MSVC Build Tools 2022 (owner-authorized) + pgvector 0.8.7 built from the official source (tarball SHA-256 `cac0b10c…ea85`) into git-ignored `.tools/pg17.11`; production uses the official `pgvector/pgvector:0.8.7-pg17-bookworm` image |
| Requirements covered | REQ-RAG-01 (retrieval part), -02, -03 (evidence state), -05, -06, -07, -08 (mechanism proven locally: 120→150 re-index); REQ-KB-01..04; REQ-LLM-02 (embeddings via OpenRouter), -03; REQ-TRACE-02 (sources/model for search); REQ-SEC-01/02/03. **Pending (agent phase):** answer generation, citing, "no information" wording, REQ-INJ-01, REQ-TEST-01/07/09 end-to-end |

**APP-03B audit findings after VM validation:** APP03B-01 LOW webhook auth (**open**; confirmed inside loopback/private boundary, direct webhook can't create unconfirmed leads); APP03B-02 LOW n8n execution retention (**open**; execution data holds synthetic contact data + raw Idempotency-Key, no tokens); APP03B-03 LOW confirmed-action cleanup (**open**); APP03B-04 INFO real n8n import/activation/execution (**RESOLVED** by APP-03BV1); APP03B-05 INFO authenticated-session limitation (**open**); APP03B-06 INFO concurrent-confirm endpoint test (**covered** by APP-03BV1: same key → both 201 same lead; different keys → 201 + 409); new INFO: n8n `/healthz` healthy ~1.3 s before webhooks are registered after restart (observed; by code analysis a confirm in that window → 502 `workflow_rejected`, no lead, retryable).

## Leads through n8n (APP-03B)

| Item | Value |
|------|-------|
| Migration | `0006_leads` (current schema version): `service_credentials`, `pending_lead_actions`, `leads` |
| Lead schema | `leads`: id (uuid), company_name, contact_name, contact_email (format CHECK), need, requested_by_customer_id (session; not a lead field), source_action_id (UNIQUE → one lead per confirmed action), workflow_execution_id (n8n `$execution.id`), timestamps. Exactly the REQ-API-03 fields; contact channel = e-mail (REQ-LEAD-01) |
| Auth decision | PDF doesn't specify lead auth → minimum safe prototype: prepare/confirm require an existing test session (no anonymous write surface) (D-51) |
| Confirmation | `pending_lead_actions` pending → confirmed (exact fingerprint verified; SHA-256 of Idempotency-Key bound) → consumed (same txn as lead INSERT); superseded on re-prepare in the same conversation (advisory lock + one-pending-per-group index); 30-min TTL for pending. Fingerprint: SHA-256 of canonical JSON `{v: lead-v1, requested_by, company_name, contact_name, contact_email (lower-cased), need}` (NFC, trimmed) |
| n8n workflow | `nexo-lead-create` (`n8n/workflows/nexo-lead-create.json`, id `NexoLeadCreate01`): Webhook `POST /webhook/nexo-lead-create` → IF envelope complete → HTTP Request `POST http://backend:8000/internal/leads` (credential `nexo-lead-writer`, forwards `Idempotency-Key`, `X-Request-ID`, `$execution.id`) → Respond with backend status/body. No DB/code/SaaS nodes; exported without credentials (REQ-N8N-02) |
| Service-auth boundary | `/internal/leads` accepts only `service_credentials` scope `lead_write` (`n8n-lead-writer`). Backend env gets **only** `LEAD_WRITER_TOKEN_SHA256`; the raw token lives only in n8n's encrypted credential store. Customer tokens (different table) → 401. Provisioning refuses a missing hash or one equal to a customer token's hash |
| Idempotency | One key end-to-end: bound (as hash) to one action per session (`UNIQUE (requested_by, key hash)`), forwarded by n8n, re-checked by the private write; `leads.source_action_id` UNIQUE; consumed same-key retries answered from PostgreSQL without calling n8n; raw key never stored/logged (12-hex fingerprint) |
| Failure/retry | confirm never inserts; success only from the lead row read back from PostgreSQL. n8n down/5xx/timeout → check DB → no lead: 503 `lead_not_confirmed` (action stays `confirmed`, same-key retry resumes; other key → 409 `confirmation_in_progress`); lead committed but response lost → 201 replay (`recovered_after_dispatch`); workflow 2xx without row → 502 `workflow_inconsistent`; workflow/backend rejection → 502 `workflow_rejected`; DB error in private write → rollback, retryable |
| Traceability | `lead_prepare` / `lead_confirm` / `lead_write` audit lines; n8n forwards `X-Request-ID`, so confirm and private write share one request_id; `workflow_execution_id` on the lead row and both audit lines; no tokens, service token, raw key or contact text in logs (tested) |
| Requirements covered | REQ-LEAD-01, -02 (backend + workflow definition), -03 (API wording); REQ-CONF-03; REQ-RESP-03, -04; REQ-N8N-01 (definition; execution pending VM), -02; REQ-API-01 (adapted `POST /leads`), -02, -03 (lead fields); REQ-ARCH-05 (leads persisted); REQ-IDEMP-01, -02; REQ-AUTH-01, -04; REQ-FAIL-01, -02, -03; REQ-TRACE-02 (API part), -03; REQ-PERS-01, -02 (lead + n8n state survive recreation); **REQ-TEST-10 ("workflow executed and lead persisted") proven with REAL n8n in APP-03BV1** |

## n8n foundation (N8N-01)

| Item | Value |
|------|-------|
| Image | `n8nio/n8n:2.42.3` (official; tag `stable` = `latest` = 2.42.3 on 2026-10-06, digest prefix `sha256:240eaa2a3d49`; 2.43.0 was `next`/`beta`) |
| Service | `n8n` in `compose.yaml`, `restart: unless-stopped`, healthcheck `GET /healthz` via the image's Node.js |
| Host binding | `127.0.0.1:${N8N_HOST_PORT:-5678}` → 5678 (admin UI loopback only; access via SSH tunnel) |
| Persistence | named volume `n8n_data` → `/home/node/.n8n` (n8n's embedded SQLite: owner, workflows, encrypted credentials, executions) |
| Networks | new `automation` network (backend + n8n); `internal` unchanged (db + backend). n8n can reach `http://backend:8000`, **not** the database |
| Secrets | `N8N_ENCRYPTION_KEY` (required, from `.env`, must stay stable for the volume); n8n gets no DB password or customer tokens; telemetry and version checks disabled |
| Admin/auth | Self-hosted Community Edition, no n8n Cloud/subscription. Built-in user management: on first UI visit n8n asks to create the **owner account** interactively (no basic-auth env vars; nothing pre-seeded or bypassed). Owner password chosen by the operator, never stored in the repo |
| Exposure window | Until the owner exists, anyone reaching the UI could claim it; mitigated by loopback-only binding (SSH access required). Create the owner right after first start |
| Requirements | Foundation for REQ-ARCH-02, REQ-N8N-01/02, REQ-RESP-03, REQ-LEAD-02 (workflow in APP-03B); REQ-DOCKER-01..05, REQ-PERS-01/02, REQ-SEC-01/02/03 (statically) |
| Runtime proof | **VM_VALIDATED (N8N-01V1, 2026-10-07)**: `compose config` OK; db/backend/n8n healthy; backend `127.0.0.1:8000` and n8n `127.0.0.1:5678` only, no `:5432`; n8n only on `nexo_automation`, backend on both; n8n → `backend:8000/health` 200, `db` unresolvable; no `POSTGRES_*`/`AUTH_TOKEN_*` in n8n env; inactive marker workflow survived container recreation with the same encryption-key fingerprint; 0 secret occurrences in logs; n8n image ID on VM = recorded digest `sha256:240eaa2a3d49…`; owner setup left pending (`showSetupOnFirstLoad=True`), marker via supported CLI |

## Human handoffs (APP-03A)

| Item | Value |
|------|-------|
| Migration | `0005_handoffs` (current schema version) |
| Schema | `handoffs`: id (uuid), customer_id (FK, NOT NULL, from auth only), conversation_id, reason, summary (1–2000), status, idempotency_key, request_hash, created_at, updated_at; `UNIQUE (customer_id, idempotency_key)`; index (status, created_at) for the inbox |
| Reasons | `critical_incident` / `human_requested` / `unsafe_to_resolve`, exactly the three triggers of REQ-HANDOFF-01. The API validates; *choosing* the reason is the agent's job (later phase) |
| Status contract | Only `pending` exists (DB CHECK). Response `status_message`: "Registered and pending human attention. It has not yet been picked up by a person; no response time is guaranteed." No assignee/ETA fields. New states need a migration and an evidenced transition (REQ-HANDOFF-03) |
| API | `POST /handoffs` (Bearer + `Idempotency-Key`), body `{conversation_id, reason, summary}`, unknown fields → 422; `X-Conversation-ID` must match the body if sent (else 400). 201 + `Idempotency-Outcome: created|replay`; 409 `idempotency_key_conflict`; 400 missing/invalid key; 401 unauthenticated; 503 "retry with the same Idempotency-Key" on DB failure (never success) |
| Idempotency | The handoff row is its own idempotency record: one `INSERT … ON CONFLICT ON CONSTRAINT handoffs_customer_idempotency_key DO NOTHING`; on conflict the committed row is read (a concurrent holder is waited for) and replayed if `request_hash` matches (SHA-256 of op, conversation_id, reason, NFC-trimmed summary), else 409 without revealing the original. No process memory |
| Confirmation | **None by design**: the PDF requires user confirmation for tickets (§4B) and leads (§4C) only, not for escalation (§4E, REQ-TEST-06) |
| Side effects | No email/message sent (REQ-HANDOFF-04); persisted in a local table (REQ-HANDOFF-02) |
| Audit | action `handoff_create`, request_id, conversation_id, handoff_conversation_id, reason, handoff_id, idempotency, result, status, duration_ms. Summary text, tokens and passwords never logged |
| Tests | `tests/test_handoffs.py` 32 tests (all 12 required cases + validation, header mismatch, per-customer key scope, 6-way concurrency, in-transaction failure rollback, forbidden-claims detector) |
| Requirements covered | REQ-HANDOFF-02, -03, -04; REQ-API-01 (`POST /handoffs`), -02, -03 (escalation fields); REQ-ARCH-05 (escalations persisted); REQ-IDEMP-01, -02; REQ-AUTH-01, -04; REQ-FAIL-01 (API level), -02, -03; REQ-TRACE-02 (API part), -03; REQ-PERS-01 (DB state); REQ-TEST-06 (API half: persisted + pending). **Not covered here:** REQ-HANDOFF-01 trigger decisions (agent phase) |

**APP-03A independent Codex audit (of `2fd4e2a`): PASS WITH LOWS / SAFE FOR VM VALIDATION.**

| ID | Severity | Summary | Status |
|----|----------|---------|--------|
| APP03A-01 | LOW | Empty, whitespace-only or invalid supplied `X-Conversation-ID` was normalized to "absent", bypassing the header/body mismatch rule (handoff created with 201, audit conversation_id null) | **CLOSED**: focused Codex re-audit PASS. Fixed in APP-03AF1: `tracing.py` records whether the header was supplied; `POST /handoffs` rejects supplied-but-invalid with 400 (`InvalidConversationHeader`) before the mismatch and idempotency checks, so nothing is persisted and the key isn't consumed |

Observation for re-audit (not changed): `POST /tickets/prepare` still treats a supplied-but-invalid header as "no conversation" for supersede grouping (within the documented APP02-02 LOW behavior; ownership/confirmation/idempotency unaffected).

## VM runtime validation (APP-02V1, 2026-10-06, run 2 ~16:07–16:09 UTC)

| Item | Result |
|------|--------|
| Candidate | `1284f98` via git bundle, detached checkout on VM, SHA verified; image built on the VM |
| Startup | compose config valid; `db` + `backend` healthy; migrations 0001–0004 applied, `schema_migrations` checksums identical to the files; synthetic credentials provisioned; `/health` 200, `/health/ready` 200 at `0004` |
| Ports | db unpublished, no `:5432` host listener; backend only `127.0.0.1:8000`; public only `:9922`; backend → `db` via Docker DNS |
| Authorization | /me A→A, B→B; own tickets 200; foreign tickets 404 (generic, no leak); invalid/missing token 401 |
| Prepare/confirm | prepare 201, ticket count unchanged; confirm 201 `created`, real ticket persisted with owner CUSTOMER_A and `source_action_id`, readable by owner only |
| Idempotency | same key + same request → 201 `replay`, same ticket; same key + different action/hash → 409 `conflict`; consumed + new key → 409 `confirmation_already_used` + existing `ticket_id`; missing/invalid key → 400; no extra tickets |
| Invalidation | `normal` → re-prepared `critical` in the same conversation: old action superseded, confirm → 409 `confirmation_invalid`; new → 201 `critical`; +1 ticket |
| Concurrent prepare | 3 rounds × 8 concurrent prepares → each `pending=1, superseded=7`; only the pending action confirms (201), the 7 others 409; +1 ticket per round |
| Cross-customer | A confirming B's action → 404 identical to nonexistent, no leak, no ticket; B confirms its own → 201 |
| Priority | `normal`, `critical` accepted; `low`, `medium`, `high`, `urgent` → 422 and DB `tickets_priority_check` |
| Traceability | prepare/confirm audit lines with X-Request-ID, X-Conversation-ID, pending_action_id, ticket_id (after commit), created/replay/conflict, status, duration_ms; no tokens, password, `Bearer` or ticket content in logs |
| Persistence | after `down` (volume kept) + `up`: same db volume, migrations "up to date", same ticket readable by its owner, `/health/ready` 200, **idempotent replay still returns the same ticket** |
| Secrets | VM-generated, never printed; 0 occurrences of each in the run log |
| Cleanup | `down -v`, both images and build cache (249 MB) removed, temp dir incl. `.env` deleted; VM Docker state = pre-run; listeners `:9922` + loopback DNS only |

## APP-02 independent audit findings

| ID | Severity | Summary | Status |
|----|----------|---------|--------|
| APP02-01 | HIGH | `prepare()` not serialized per customer/conversation group: concurrent prepares could leave two pending actions, so two tickets via different keys | **CLOSED**: fixed in APP-02F1 (`1284f98`), Codex focused re-audit PASS, VM runtime behavior confirmed in APP-02V1 |
| APP02-02 | LOW | Missing or deliberately reused `X-Conversation-ID` makes same-customer flows supersede one another | Retained, documented (D-41, R-10) |
| APP02-03 | INFO | No retention cleanup of actions or idempotency records | Retained (R-11) |
| APP02-04 | INFO | No real connection failure injected exactly around COMMIT | Retained (R-15) |
| APP02-05 | INFO | Historical R-13 intermittent failure unexplained | Retained (R-13); not observed during APP-02F1 |

**APP02-01 fix:** `prepare()` takes `pg_advisory_xact_lock(prepare_lock_key(customer_id, conversation_id))` as
the first statement of its transaction (key = first 8 bytes of SHA-256 of `["nexo:ticket_prepare:v1", customer_id,
conversation_id]`, signed 64-bit). Migration `0004_one_pending_action_per_group` adds a partial unique index
(one `pending` action per `(customer_id, coalesce(conversation_id,''))`) after superseding older duplicates.
**Safe under READ COMMITTED:** a second prepare in the same group blocks on the lock before its supersede UPDATE;
when it proceeds, that UPDATE is a new statement with a fresh snapshot that sees and supersedes the first
transaction's committed row. The index rejects a second pending row on any code path. Original code reproduced the
bug (both pending; 3 of 6 in a free race); the fix passes all orderings tested.

## Ticket creation (APP-02)

| Item | Value |
|------|-------|
| Risk class | **HIGH** (confirmation, integrity, authorization, idempotency) |
| Migration | `0003_priority_and_ticket_confirmation`; APP-02F1 added `0004_one_pending_action_per_group` (current schema version) |
| Canonical priorities | `normal` / `critical` only (REQ-KB-02 semantics). Legacy mapping: `low`, `medium` → `normal` (neither can mean a company-wide total outage); `high`, `urgent` → **migration aborts** if any exist (no guessing; none existed). Seed tickets A (`medium`) and B (`low`) are now `normal`. Earlier migrations unchanged |
| Pending actions | `pending_ticket_actions`: id, customer_id (FK, from auth only), conversation_id, contact_name, subject, description, priority, `payload_hash`, status `pending/consumed/superseded/expired`, expires_at (TTL 30 min), consumed_at, timestamps |
| Fingerprint | SHA-256 of canonical JSON `{"v":"ticket-v1","customer_id",contact_name,subject,description,priority}`: sorted keys, `,`/`:` separators, UTF-8, `ensure_ascii=False`; text fields NFC-normalized and trimmed before hashing and storage |
| Prepare | `POST /tickets/prepare` → 201 with action id, summary (incl. authenticated customer_id), `summary_text`, `payload_hash`, `expires_at`. Creates **no** ticket. Serialized per group by a transaction-scoped advisory lock (APP-02F1), then supersedes the caller's still-pending actions in the same `X-Conversation-ID` (or among actions with no conversation). At most one pending action per group (DB unique index) |
| Confirm | `POST /tickets/confirm` body `{pending_action_id, payload_hash}` + `Idempotency-Key` header. One transaction: idempotency lookup → `SELECT … FOR UPDATE` own action → re-check idempotency → status/expiry → fingerprint (presented == stored == recomputed) → INSERT ticket from **stored** data with auth owner and `source_action_id` → INSERT idempotency record → mark action `consumed` → COMMIT → 201 |
| Idempotency | `idempotency_keys` PK `(customer_id, operation, idempotency_key)`; `request_hash` = SHA-256 of `{op, pending_action_id, payload_hash}`; stored `response_status` + `response_body` (jsonb). Same key + same request → replay (201, `Idempotency-Outcome: replay`); same key + other request → 409 `idempotency_key_conflict`; missing/invalid key → 400 |
| DB backstops | `tickets.source_action_id` UNIQUE (one ticket per action); idempotency PK. Concurrent losers roll back entirely and are answered from committed state |
| Error contract | Foreign/unknown action → identical 404; superseded/expired → 409 `confirmation_invalid`; fingerprint mismatch → 409 `confirmation_mismatch`; consumed + new key → 409 `confirmation_already_used` + existing `ticket_id`; unknown body fields (incl. `customer_id`, `confirmed`) → 422; DB failure → 503 "retry with the same Idempotency-Key", never success |
| Audit fields | action `ticket_prepare` / `ticket_confirm`, request_id, conversation_id, pending_action_id, confirmation_result, idempotency (`created`/`replay`/`conflict`), ticket_id (only after commit), result, error class, duration_ms. No tokens, passwords or ticket content |
| Tests | 48 APP-02 tests (37 ticket-create + 11 priority-migration) plus the existing 60, so **108 passed**; `test_evidence_dump` opt-in. Unmutated APP-02 file: 18/18 consecutive clean runs |
| Requirements covered | REQ-TICKET-02, -03, -04; REQ-CONF-01, -02, -04; REQ-IDEMP-01, -02; REQ-AUTH-01, -02, -04; REQ-ISO-01, -02; REQ-FAIL-01 (DB error/outage at API level), -02, -03; REQ-TRACE-02 (API part), -03; REQ-KB-02 (priority semantics); REQ-API-01 (adapted `POST /tickets`), -02, -03 (ticket fields); REQ-PERS-01 (DB-persisted state, not process memory) |

## Requirements source (DOCS-01)

| Item | Value |
|------|-------|
| Official assessment source (authoritative) | `docs/Prueba_Tecnica_Agente_IA_48h_2026-10-06.pdf` (7 pages, Spanish; SHA-256 `4088cd6ac9f5812cbff5459e21674f39242c6c3c5a8b6366fce4f7f42f9394ea`) |
| Canonical requirements text | `docs/ASSESSMENT_REQUIREMENTS.md`: English working representation with 116 traceability IDs (`REQ-<CATEGORY>-NN`, 26 categories), each citing its PDF section. **If they conflict, the PDF wins** |
| Note | FOUNDATION-01/02 and APP-01 were built from the owner's task briefs before the PDF was in the repo |

**Alignment observations** (non-normative; to be handled in later phases, nothing changed in DOCS-01):
- ~~REQ-KB-02 priority vocabulary~~: resolved in APP-02 by migration 0003 (`normal`/`critical`).
- REQ-TICKET journey D uses a ticket reference like `T-1001`; ticket IDs are still UUIDs. **Not addressed in APP-02**; open for a later phase (routes and IDs may be adapted if documented, REQ-API-01).
- REQ-API-04 requires documenting the initial data and how to restore it **without accidentally deleting evidence**.
- REQ-LEAD-02 / REQ-RESP-03: lead creation **must** go through an n8n workflow.
- REQ-DELIV-03/04, REQ-EVID-01: the final technical documentation and the test evidence are a **PDF** deliverable (plus README instructions); REQ-AI-01/02 require an AI-tool disclosure.
- REQ-TRACE-02 additionally requires logging retrieved sources and the model used (agent phase).

## Business API (APP-01)

| Item | Value |
|------|-------|
| Requirements source | Owner's APP-01 task brief (built before the official PDF was in the repo; trace to `docs/ASSESSMENT_REQUIREMENTS.md`: REQ-AUTH-01..04, REQ-ISO-01..02, REQ-API-01..04, REQ-TICKET-05, REQ-PERS) |
| Migrations | Own minimal runner `app/migrate.py`: ordered `app/migrations/*.sql`, recorded in `schema_migrations` (version + SHA-256 checksum), all pending migrations in one transaction under advisory lock; edited applied migration → refused. Container runs `python -m app.migrate` before serving |
| Schema version | `0002_synthetic_seed` (`0001_initial_schema`, `0002_synthetic_seed`) |
| Tables | `customers(id text PK, display_name, created_at)`; `api_credentials(customer_id FK, label, token_sha256 UNIQUE, …)`; `tickets(id uuid PK, customer_id NOT NULL FK → customers RESTRICT, contact_name, subject, description, priority CHECK, status CHECK, created_at, updated_at + trigger)` |
| Synthetic customers | `CUSTOMER_A` "Synthetic Customer A", `CUSTOMER_B` "Synthetic Customer B" |
| Seed tickets | A: `a0000000-0000-4000-8000-000000000001` (open, medium); B: `b0000000-0000-4000-8000-000000000001` (in_progress, low). Fixed timestamps, no real data |
| Authentication | **Synthetic assessment auth, not production identity.** Bearer token per customer from env `AUTH_TOKEN_CUSTOMER_A/B` (≥ 32 chars, distinct); `python -m app.provision_auth` stores **SHA-256 only**; requests are authenticated by hash lookup. Identity = DB lookup result only |
| API | `GET /health` (liveness), `GET /health/ready` (readiness), `GET /me`, `GET /tickets/{ticket_id}` |
| Authorization | Ownership in SQL (`WHERE id = $1 AND customer_id = $authenticated`). Foreign and unknown tickets return the identical `404 {"detail":"Ticket not found"}`; audit log distinguishes `denied_not_owner` / `not_found`. Missing/invalid credential → `401` + `WWW-Authenticate: Bearer`. DB failure → `503` generic |
| Readiness | `200 {"status":"ready","database":"ok","schema_version":…}` only if PostgreSQL answers **and** schema = latest migration; else `503 {"status":"not_ready","database":"unavailable"|"schema_outdated"}` with no connection details. Backend container HEALTHCHECK now uses `/health/ready` |
| Traceability | `X-Request-ID` generated or accepted (safe charset, ≤ 64 chars) and returned; `X-Conversation-ID` accepted the same way; one JSON audit line per request: ts, request_id, conversation_id, method, route, status, duration_ms, customer_id, action, ticket_id, result, error class. Never headers, tokens, passwords, bodies or reasoning |
| Tests | **60 passed / 0 failed / 0 skipped**, including 29 integration tests on a throwaway real PostgreSQL 17.11 (scram-sha-256, random port/password/tokens per run). Mutation check: removing the ownership filter makes 4 isolation tests fail |
| Local tooling | PostgreSQL 17.11 official Windows binaries (EDB zip, owner-authorized), SHA-256 `6eabdf00d2893713b75db4336a23c3fdf505f056e217ec6e2e95d901750cfea3`, in git-ignored `.tools/pg17.11/`; executables are not Authenticode-signed (integrity = HTTPS from EDB + recorded hash). `psycopg[binary]==3.3.6` |

## Runtime validation (FOUNDATION-02, 2026-10-06 12:54–12:56 UTC)

| Item | Result |
|------|--------|
| Commit tested | `59264698b854ddcd7e58ffb8168d68f60766bd28` (git bundle → detached checkout on VM, SHA verified) |
| VM-local secrets | `.env` generated on the VM (random 32-byte DB password, mode 600), never printed; 0 occurrences of the password in the run log; deleted at cleanup |
| `docker compose config` | VALID |
| Build | `nexo-backend:0.1.0` built on VM (221 MB); transitive deps resolved to the same versions as `evidence/02-foundation/pip-freeze.txt` |
| Health | `db` healthy (`pg_isready`), `backend` healthy (Dockerfile HEALTHCHECK); `GET 127.0.0.1:8000/health` → `200 {"status":"ok"}` |
| Ports | db: no published port; backend `127.0.0.1:8000` only; no `:5432` host listener; public listeners still only `:9922` |
| Service-to-service | backend → `db:5432` over Docker DNS; authenticated `psql` login over the network (PostgreSQL 17.11) |
| Persistence | marker row written, then `compose down` (volume kept) and `up`: new db container ID, same `nexo_db_data` volume instance, marker read back identical, so **PASS from real data** |
| Network / egress | `nexo_internal` is a normal `bridge` with `internal=false`. From the backend container: DNS `openrouter.ai` OK, HTTPS GET public `/api/v1/models` → 200 (no key, no LLM call). **No compose change needed** |
| Cleanup | marker table dropped; `compose down -v` (containers, network, volume); images `nexo-backend:0.1.0` + `pgvector/pgvector:0.8.7-pg17-bookworm` removed; build cache pruned (220.7 MB, this run only); `~/nexo-f02` (incl. `.env`) deleted. **VM Docker state = pre-run** (0 containers/images/volumes/cache) |

## Application foundation (FOUNDATION-01)

| Item | Value |
|------|-------|
| Architecture | `compose.yaml` (project `nexo`) with 2 services, `backend` + `db`, on private network `internal` |
| Backend | FastAPI `0.142.2` + uvicorn `0.54.0`, Python `3.12` (image `python:3.12.15-slim-bookworm`), non-root user (uid 10001) |
| Endpoint | `GET /health` → `200 {"status":"ok"}` (liveness; DB not checked) |
| Config | `src/backend/app/config.py`: env vars only; `POSTGRES_HOST/DB/USER/PASSWORD` required, `POSTGRES_PORT` default 5432; app fails fast at startup if missing; password excluded from repr; errors name variables, never values |
| Database | `pgvector/pgvector:0.8.7-pg17-bookworm` (PostgreSQL 17; pgvector **available, not enabled**) |
| DB exposure | no `ports:`; reachable only on the `internal` network as `db:5432` |
| Backend exposure | `127.0.0.1:${BACKEND_PORT:-8000}` → 8000 (loopback only, per D-11) |
| Healthchecks | db: `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` (10s/5s/5 retries/20s start); backend: Dockerfile `HEALTHCHECK` via Python stdlib GET `/health` (15s/3s/3 retries/10s start) |
| Startup order | `backend.depends_on.db.condition: service_healthy` |
| Restart policy | `unless-stopped` on both services |
| Persistence | named volume `db_data` → `/var/lib/postgresql/data` |
| Credentials | `${POSTGRES_*:?...}` substitution from the git-ignored `.env`; compose fails if unset |
| Tests | 23 passed / 0 failed (`pytest 9.1.1`, local Python 3.12.10); see `evidence/02-foundation/` |
| Local tooling | Python 3.12.10 installed per-user via winget (owner-authorized); project `.venv` (git-ignored). No local Docker |

## VM environment

| Area | Fact |
|------|------|
| Access | SSH `user@<VM_HOST>:9922`, password auth (entered interactively by owner, never stored) |
| User | `user` (uid 1000); groups: `user`, `adm`, `cdrom`, `sudo`, `dip`, `plugdev`, `lxd`, **`docker`** (added in PRE-02) |
| Hostname | `server` |
| OS | Ubuntu 24.04.4 LTS (noble); locale es (apt output in Spanish) |
| Kernel / arch | 6.8.0-100-generic / x86_64 (KVM guest) |
| CPU | 2 vCPU (QEMU Virtual CPU, AMD) |
| RAM | 3.8 GiB total, ~3.4 GiB available (pre-Docker); swap 3.8 GiB |
| Disk `/` | 47 GB ext4: 6.4 GB used before Docker, **6.9 GB used / 38 GB free after** (16%) |
| Firewall | `ufw` active (not modified); iptables backend `iptables-nft` |
| Listening TCP | 9922 (SSH, all interfaces); 53 loopback only (systemd-resolved). **No new ports after Docker install** |
| Outbound HTTPS | OK: openrouter.ai, pypi.org, download.docker.com, registry-1.docker.io |
| Git / curl | 2.43.0 / 8.5.0 |
| Python | 3.12.3; venv/pip **not installed** (not authorized; not needed if app runs in containers) |
| Pending OS updates | 228 packages upgradable (not in scope; not touched) |

## Docker status (PRE-02, verified 2026-10-06)

| Item | Value |
|------|-------|
| Installation source | Docker official apt repo `https://download.docker.com/linux/ubuntu` (`noble stable amd64`), deb822 file `/etc/apt/sources.list.d/docker.sources`, key `/etc/apt/keyrings/docker.asc` |
| GPG key fingerprint | `9DC858229FC7DD38854AE2D88D81803C0EBFCD88` (verified against Docker's published value before trust) |
| Docker Engine | **29.8.2** (`docker-ce 5:29.8.2-1~ubuntu.24.04~noble`, build 7fc2dff) |
| Docker CLI | 29.8.2 |
| containerd | `containerd.io 2.3.6-1~ubuntu.24.04~noble` |
| Docker Compose | **v5.6.0** (plugin `docker compose`; no legacy `docker-compose`) |
| Buildx | v0.37.1 |
| Also installed (deps) | `docker-ce-rootless-extras 5:29.8.2`, `pigz 2.8-1` (Ubuntu archive) |
| Service | `docker` and `containerd`: **active**, **enabled** (enabled by package postinst) |
| docker info | storage `overlayfs`, cgroup driver `systemd`, cgroup v2, root `/var/lib/docker` |
| docker group | GID 988, member `user`; Docker CLI works **without sudo** in a fresh session |
| Runtime test | `docker run --rm hello-world` OK; image removed afterwards; 0 containers / 0 images / 0 volumes remain |
| Networks | default `bridge`, `host`, `none` only |

## OpenRouter

| Item | Value |
|------|-------|
| OPENROUTER_BUDGET | **EUR 30** (confirmed by assessment contact; more could be considered if justified) |
| OPENROUTER_MODEL_SELECTION | **DEVELOPER_DISCRETION** |
| OPENROUTER_CONTACT_RECOMMENDATION | **Grok 4.7** (quality/cost) |
| OPENROUTER_MODEL_ID | **`x-ai/grok-4.7`** (VERIFIED 2026-10-07: public catalogue + live probe served exactly this id; $2/M in, $6/M out; reasoning mandatory, set to low/excluded). Config `OPENROUTER_CHAT_MODEL`; no fallback |
| Credential validation | **VALID**: `GET /api/v1/key` → HTTP 200 (PRE-01) |
| Provider-reported key metadata | `limit=30`, `limit_remaining=30`, `usage=0`, `limit_reset` empty, `is_free_tier=False` (unit of `limit` not stated by provider; not assumed) |
| Model tested | **none**; no LLM calls made (FOUNDATION-01 explicitly excludes them) |
| Key location | local git-ignored `.env` only; never copied to the VM |

## Decisions

- D-01: Remote inspection is read-only (INV-12); scripts are committed for reproducibility.
- D-02: SSH and sudo passwords are entered interactively by the owner at TTY prompts; the assistant never handles them.
- D-03: OpenRouter credential is validated from the local workstation, not the VM.
- D-04: Credential validation uses the non-billable `GET /api/v1/key`; any model call requires prior explicit approval.
- D-05: Raw evidence lives in git-ignored `evidence/**/raw/`; only sanitized copies are committed.
- D-06: No model is chosen; `openai/gpt-4o-mini` is **not** a project decision.
- D-07: Docker is installed from Docker's official apt repository, not Ubuntu's `docker.io` (which lacks the Compose v2 plugin) or the `get.docker.com` convenience script (not recommended for production).
- D-08: Docker's signing-key fingerprint is verified before the key is trusted.
- D-09: `ca-certificates`/`curl` are not reinstalled (already present) to avoid unrelated upgrades.
- D-10: Owner authorized Docker's **automatic** iptables chains and `docker0` bridge only. Not authorized: manual ufw changes, SSH changes, arbitrary firewall rules, publishing application ports.
- D-11: Docker-published ports bypass ufw (Docker's iptables rules are evaluated first), so any future container port must bind to `127.0.0.1` unless public exposure is explicitly authorized.
- D-12: `.gitattributes` forces LF for `*.sh` so scripts stay runnable on the VM despite `core.autocrlf=true` on the workstation.
- D-13: Two-service stack (FastAPI + PostgreSQL) with no extra frameworks (no LangChain/LangGraph/Redis/Celery), so each layer stays small and explainable.
- D-14: PostgreSQL via `pgvector/pgvector` (PG17) pinned tag: same PostgreSQL, with the vector extension ready for future RAG without a DB migration. PG17 rather than PG18 because PG18 images change the data directory layout.
- D-15: Python 3.12 pinned to patch level in the image (`3.12.15`); direct deps pinned with `==`. Transitive deps aren't locked yet (risk R-02).
- D-16: `/health` is liveness only and deterministic; DB readiness is enforced by the `db` healthcheck + `depends_on: service_healthy`. A DB-aware readiness endpoint comes with the first DB-using feature.
- D-17: Configuration fails fast at startup; secrets have no defaults and never appear in repr or error messages.
- D-18: Containers use `restart: unless-stopped`: they survive VM reboots and crashes but stay down if deliberately stopped.
- D-19: The backend container runs as non-root (uid 10001).
- D-20: The compose network name `internal` is only a label; it isn't `internal: true`, so container egress (future OpenRouter calls) works. Verified at runtime and kept unchanged.
- D-21: VM-side DB credentials are generated on the VM and never typed, printed or transferred; a VM-side leak check runs before `.env` is deleted.
- D-22: VM validation runs are temporary and self-cleaning (pre-checks abort on any existing state; final state is verified equal to pre-run).
- D-23: Plain SQL + `psycopg` 3 (no ORM) and an own ~80-line migration runner (no Alembic): every query and schema change is readable SQL, which is easier to explain and audit than generated code.
- D-24: Synthetic data and the schema live in versioned migrations; credentials do **not** (they are provisioned at runtime from the environment, hashed), so migrations stay deterministic and secret-free.
- D-25: Bearer tokens stored as unsalted SHA-256. Acceptable because tokens are random and at least 32 characters (no dictionary attack); passwords would need a slow hash instead.
- D-26: Foreign and unknown tickets return the identical `404` (not `403`), so existence and ownership never leak (INV-03). The audit log keeps the distinction for operators.
- D-27: Ownership is enforced in the SQL predicate itself, not by fetching then comparing, so another customer's row is never loaded for the request.
- D-28: Liveness (`/health`, process up, no dependencies) and readiness (`/health/ready`, DB reachable and schema current) are separate. The container HEALTHCHECK uses readiness, so "healthy" means "can serve requests". Supersedes the D-16 deferral.
- D-29: Integration tests use a real, throwaway PostgreSQL 17 (same major version as production) rather than mocks, because authorization correctness depends on real SQL and constraints.
- D-30: Test clusters live in a default-permission TEMP subfolder: on Windows, `mkdtemp`/pytest `tmp_path` create owner-only ACLs that `initdb`'s restricted token cannot read.
- D-31: Priority mapping `low`/`medium` → `normal`; `high`/`urgent` deliberately not auto-mapped (the migration aborts), because "critical" means a whole-company outage and that can't be inferred from a legacy label.
- D-32: Confirmation is server-bound: the client must echo the fingerprint of a stored, owned, pending, unexpired action. The ticket is built from the stored data, so a client can't confirm one summary and submit different data.
- D-33: Re-preparing supersedes the caller's pending actions in the same conversation, so a changed summary always requires a new confirmation (REQ-CONF-02).
- D-34: Idempotency record, ticket and action status change are committed in **one** transaction, with DB unique constraints as backstops. Process memory is never used for idempotency.
- D-35: A consumed action confirmed with a **new** key is rejected (409 `confirmation_already_used` + existing `ticket_id`), not replayed. Replay is reserved for the same key and the same request.
- D-36: Unknown request fields are rejected (`extra=forbid`), so `customer_id`/`confirmed` in a body are refused rather than silently ignored.
- D-37: Ticket creation is exposed as `POST /tickets/prepare` + `POST /tickets/confirm` (documented adaptation of the PDF's `POST /tickets`, REQ-API-01).
- D-38: (APP-02F1) `prepare()` serialization uses PostgreSQL `pg_advisory_xact_lock` per (customer, conversation) group, not app memory or external coordination. The lock is released automatically at COMMIT/ROLLBACK and is never logged.
- D-39: (APP-02F1) The lock key is derived with SHA-256 (namespaced, JSON-encoded group) → signed 64-bit, deterministic across processes; Python `hash()` is not used.
- D-40: (APP-02F1) Partial unique index "one pending action per group" as a database backstop. The lock alone gives the correct supersede semantics; the index alone would turn races into errors; together they guarantee the invariant for every ordering and code path.
- D-41: (APP02-02 disposition) A missing `X-Conversation-ID` stays supported and forms one group per customer. A server-generated ID wouldn't help, because the server can't correlate a later confirm to it without a session, which would be an auth/session redesign outside this fix. **The agent phase must always send a stable, unique `X-Conversation-ID` per conversation.**
- D-42: (APP-03A) Handoffs need no user-confirmation step: the PDF demands confirmation only for tickets and leads.
- D-43: (APP-03A) `reason` is restricted to the PDF's three escalation triggers; `status` is restricted to `pending`, because there's no evidence source for "a human is attending".
- D-44: (APP-03A) Handoff idempotency lives on the handoff row (`UNIQUE (customer_id, idempotency_key)` + request_hash), not in the ticket-specific `idempotency_keys` table (its FKs are ticket-bound; changing it would alter audited APP-02 schema). Replay renders the current row, identical to the original while status can only be `pending`.
- D-45: (APP-03A) The handoff `conversation_id` is business data in the body (REQ-API-03); if `X-Conversation-ID` is also sent it must match, so audit correlation can't diverge from the stored record.
- D-46: (APP-03AF1) A supplied `X-Conversation-ID` is validated with the existing `safe_id` rule after stripping outer whitespace; "absent" and "supplied but invalid" are distinct request states (`request.state.conversation_header_supplied`). The raw invalid value is never logged.
- D-47: (N8N-01) n8n pinned to the official `n8nio/n8n:2.42.3` (the `stable` release at selection time); upgrades are explicit changes.
- D-48: (N8N-01) Separate `automation` network: n8n reaches the backend API only, never PostgreSQL; the business DB stays on `internal`.
- D-49: (N8N-01) n8n keeps its own state in its default embedded SQLite in `n8n_data`, separate from the business database (simpler, isolated, no extra DB user).
- D-50: (N8N-01) n8n UI loopback-only plus interactive owner setup; no attempt to script or bypass n8n's supported first-run flow.
- D-51: (APP-03B) Lead auth isn't specified by the PDF; prepare/confirm require an existing test session, stored as `requested_by_customer_id` (isolation/audit only, not a lead field).
- D-52: (APP-03B) Contact channel (REQ-LEAD-01) = `contact_email`, the only channel field REQ-API-03 names; no phone or other personal data collected.
- D-53: (APP-03B) Only `leads.internal_create` inserts leads, behind `/internal/leads` + the `lead_write` service credential; confirm only dispatches and then reads PostgreSQL.
- D-54: (APP-03B) The backend holds only the SHA-256 of the n8n lead-writer token, so it cannot impersonate n8n; the token lives in n8n's credential store.
- D-55: (APP-03B) The n8n webhook is unauthenticated (private network, loopback host port); harmless because the private write requires a user-confirmed action with the bound key and identical payload.
- D-56: (APP-03B) Action state `confirmed` (key bound, not yet consumed) makes the distributed hop retryable; `consumed` only in the lead-INSERT transaction.
- D-57: (RAG-01) Corpus = exactly the four PDF documents verbatim; headings added only as structure for `document § section` references.
- D-58: (RAG-01) Embeddings via OpenRouter `openai/text-embedding-3-small`, 1536 dims (verified live); provider behind an interface; no key ⇒ 503, never a fake in production.
- D-59: (RAG-01) Exact cosine search, no ANN/HNSW: 10 chunks; an index would add complexity without measurable benefit.
- D-60: (RAG-01) Threshold calibrated with the real model, including in-domain-absent queries; 0.39 chosen over the unrelated-only 0.33 to avoid accepting absent facts.
- D-61: (RAG-01) Local test PostgreSQL gets pgvector 0.8.7 built from the official source with MSVC (no third-party binaries; version parity with production).
- D-62: (RAG-01F1) Ingestion = plan → embed all → one advisory-locked transaction (lock never held during provider calls); re-plan instead of publishing a chunk without its matching embedding.
- D-63: (RAG-01F1) Keep the `reference:` front-matter line for readability but require `reference == file name` (fail closed); citations use `path.name`.
- D-64: (AGENT-01A) Two-call design: (1) the LLM proposes an intent from a closed enum (nothing else accepted); (2) only for knowledge questions with sufficient evidence, the LLM paraphrases the accepted passages. Ticket status answers are deterministic from PostgreSQL (no LLM, no ticket data sent out).
- D-65: (AGENT-01A) Tool arguments never come from the model: the ticket id is the UUID typed by the authenticated customer; identity from the token.
- D-66: (AGENT-01A) Deterministic grounding guard: citations ⊆ retrieved+accepted chunks; every figure in the answer must be the same number in the cited chunks; otherwise `answer_blocked`.
- D-67: (AGENT-01A) The agent's DB session is READ ONLY (PostgreSQL-enforced). Action intents are recognised and answered with `executed: false`.
- D-68: (AGENT-01A) Stateless turns; `conversation_id` from body or header (same rule), generated if absent.
- D-69: (AGENT-01A) The PDF injection document is used only in TEST copies of the corpus (unit fixture + live smoke fresh DB); the deployed corpus stays the 4 PDF documents.
- D-70: (AGENT-01B) Command/query separation: the READ side (interpretation, RAG, ticket status, state reads) uses a READ ONLY session; only `app/chat_actions.py` writes, exclusively through the existing services (ticket_actions, leads, handoffs). The lead confirmation orchestration moved unchanged into `leads.confirm_via_workflow`, shared by the API and chat.
- D-71: (AGENT-01B) Confirmation is a deterministic gate: only the whole message CONFIRMAR/CONFIRM (trim + casefold) confirms; CANCELAR/CANCEL cancels; no model call on those turns; the model has no confirmation field.
- D-72: (AGENT-01B) Conversation state = `chat_conversations` (PK customer + conversation): a pointer to the prepared action plus the not-yet-prepared draft; no transcripts. Turns of a conversation are serialized by an advisory lock. Any other pending action in the conversation means nothing is executed.
- D-73: (AGENT-01B) Chat idempotency key = `chat:<conversation_id>:<action_id>` (customer-scoped by the services); handoff keys `chat-ticket-handoff:<ticket_id>` and `chat-handoff:<conversation>:<reason>`.
- D-74: (AGENT-01B) Critical tickets: priority suggested by the model from the KB policy, shown in the summary and confirmed by the user; after confirmation a `critical_incident` handoff is created (backend-decided). Handoffs need no confirmation (the PDF requires it only for tickets/leads).
- D-75: (AGENT-01B) Cancellation adds the terminal status `cancelled` (migration 0008); the existing confirm logic rejects it. A lead already handed to n8n cannot be cancelled.
- D-76: (AGENT-01B, R-14) Short ticket references `T-1001...` (sequence; seeds A=T-1001, B=T-1002), UNIQUE + immutable, resolved only within the authenticated customer's tickets; HTTP API responses unchanged.
- D-77: (AGENT-01BF1) A CONFIRMAR executes only the version named by the client-echoed `confirmation_token` = sha256(action_id + payload_hash)[:16], compared with the state re-read under the conversation lock; missing/different token => `confirmation_review_required` with the current summary (fail closed). Server-side admission capture alone cannot handle a lost re-prepare response, so the binding comes from what the client displayed.
- D-78: (AGENT-01BF1) `chat_conversations.revision` increments on every state change; a model proposal is published only if the revision it was interpreted against is unchanged (else `conversation_changed`). No transaction is held open during model calls.
- D-79: (AGENT-01BF1) Cancellation success only when this call moved the action pending -> cancelled; otherwise the answer comes from the authoritative status (consumed => `already_completed` with the object; confirmed => `cannot_cancel`; superseded/expired/cancelled => `not_pending`). Created objects are never deleted or reversed.
- D-80: (AGENT-01BF2) The business action status is AUTHORITATIVE; the conversation revision is only a concurrency signal. Before a model proposal is published, the pointed action is re-read (customer AND conversation AND action) and must be `pending`; otherwise chat state is synchronized from it and the proposal is rejected. A pointer whose action left `pending` is never replaced by a proposal.
- D-81: (AGENT-01BF2) confirm/cancel advance the revision before the service may change business state (durable even if the chat save is later lost). CANCELAR dereferences the pointer with customer AND conversation AND action BEFORE any cancel mutation.
- D-82: (AGENT-01BF3) Proposal publication is one transaction with the pointed action row locked (SELECT ... FOR UPDATE) between the authoritative check and the re-prepare; the service prepare joins it as a savepoint (no service refactor). Lock order: conversation advisory -> prepare-group advisory xact (service.prepare_lock_key) -> action row -> writes, matching the API prepare path; confirm paths take only the row lock. The model call stays outside any transaction.
- D-83: (AGENT-01BF3) CANCELAR order: validate pointer membership (zero cancel-service calls if invalid) -> advance revision -> cancel other pending actions -> cancel the pointed action.
- D-84: (UI-01) **NEXO_UI_FREEZE_01 = APPROVED / CANONICAL** visual design for the evaluation client: Stitch project "NEXO Enterprise Support Portal", Customer View (drawer closed) + Evaluator View (Technical details drawer open), design system "Sovereign Support". The UI is rebuilt from it, not exported; the real /chat contract overrides any placeholder data.
- D-85: (UI-01) The browser never holds a customer credential: the dev/preview proxy maps a demo session (A/B) to the synthetic Bearer token server-side and strips browser Authorization/Cookie headers. Identity stays a backend decision (INV-01/02).
- D-86: (UI-02) The evaluator runtime is the Compose `web` service: a zero-dependency Node boundary that serves the bundle and proxies ONLY POST /chat and GET /health/ready, attaching the selected synthetic demo credential from its runtime environment (never build args, bundle or browser). Anyone reaching the loopback web port acts as one of the two synthetic demo customers (accepted for evaluation).

## Side effects recorded

- `gpg --show-keys` (key fingerprint check) created an empty `~/.gnupg` keyring for `user`. Harmless; no system config changed.
- Docker created its standard iptables chains and the `docker0` bridge (authorized by D-10).
- FOUNDATION-02 left no residual Docker or filesystem state on the VM (see Runtime validation → Cleanup).
- UI-01: one accidental canvas edit in the Stitch project (a Preview -> Desktop click) was reverted immediately with a single undo; the design system was viewed but never saved. Local only: `src/frontend/node_modules` (git-ignored) from the owner-authorized npm install.
- UI-02: VM run 1 was lost to an SSH reset and left the stack + secrets until cleanup v2 (v1 killed itself); v2 verified baseline. Run 2 tore down fully (0 containers/images/volumes/build cache, no :8000/:5432/:5678/:8080/:8099 listener, temp dir removed). Local branch `ui02-candidate` (the validated candidate commit) kept for traceability; nothing pushed.
- FINAL-02: the VM now PERMANENTLY runs the evaluation stack (owner-authorized): `~/nexo-eval/repo` with `.env` mode 600 (OpenRouter key + synthetic credentials), Docker volumes `nexo_db_data`/`nexo_n8n_data`, images built/pulled for it, backups in `~/nexo-eval-backups`. Temporary material removed; control endpoint stopped.

## Open blockers

1. ~~B-01 OpenRouter credential invalid.~~ Resolved in PRE-01.
2. ~~B-02 Docker Engine + Compose absent on VM.~~ Resolved in PRE-02.
3. **B-03 Python venv/pip absent on VM.** Not needed if the app runs in containers; installing is not authorized.
4. ~~B-04 Authorized models and usage limits unknown.~~ **RESOLVED**: budget EUR 30, developer discretion; chat model `x-ai/grok-4.7` verified in AGENT-01A.
5. ~~B-05 Foundation container runtime not validated.~~ Resolved in FOUNDATION-02.
6. ~~B-06 Assessment requirements document not in repository.~~ **RESOLVED** in DOCS-01: official PDF added; canonical text with 116 `REQ-*` IDs created (see Requirements source).

## Current risks

- ~~R-01: Compose unproven at runtime.~~ Closed by FOUNDATION-02.
- R-02: Transitive Python dependencies aren't locked, so a future rebuild could resolve different versions. The VM build on 2026-10-06 matched `evidence/02-foundation/pip-freeze.txt`.
- R-05: No persistent deployment exists on the VM (validation was temporary by design). A deliberate deploy step is needed before any end-to-end demo.
- R-03: Starlette deprecation warning for `httpx` in `TestClient`. Not a failure; revisit when upgrading.
- R-04: VM has 3.8 GiB RAM shared by Postgres + backend (+ later n8n); monitor memory.
- ~~R-06: APP-01/02 image not container-validated on the VM.~~ Closed by APP-02V1 (image built and run on the VM; migrate → provision → serve and the readiness HEALTHCHECK confirmed).
- R-16: VM validation runs are temporary by design; no persistent deployment exists yet (R-05 still applies). A deliberate, authorized deployment step is needed before the evaluators can use the system.
- R-17: (APP-03A) Handoffs require an authenticated customer. A prospect without credentials (e.g. in the lead flow) can't be escalated through this endpoint yet; revisit if the lead/agent phase needs it.
- R-18: (APP-03A) There's no staff-side inbox endpoint or status transition yet; evaluators/operators inspect the `handoffs` table. Any future "picked up" state must be set by an evidenced human action, never by the agent.
- R-19: (APP-03A) If statuses are added later, an idempotent replay will show the handoff's *current* state (not a frozen original response); acceptable and documented (D-44).
- ~~R-20: n8n runtime unverified.~~ Closed by N8N-01V1.
- R-23: Process lesson (N8N-01V1 run 1): editing shell scripts with Python `write_text()` on Windows writes CRLF; Git Bash `bash -n` and `grep -c $'
- ~~R-24: n8n-side behavior unverified.~~ Closed by APP-03BV1: `import:credentials`, `import:workflow`, `publish:workflow` + restart, IF/HTTP Request/Respond formats and `$execution.id` all work in 2.42.3.
- R-29: (APP-03BV1) After an n8n (re)start, `/healthz` is healthy ~1.3 s before published webhooks are registered; confirms in that window fail safely (502, retryable). A readiness check on the webhook would remove the window.
- R-30: (RAG-01) Thin threshold margin (~±0.03) on a 24-query evaluation set; embeddings vary slightly between calls. The threshold proves relevance, not that a chunk answers; the agent must still check.
- R-31: (RAG-01) User queries are sent to OpenRouter for embedding (REQ-SEC-03); the agent should avoid sending unnecessary personal data in queries.
- R-32: (RAG-01) Re-ingestion is manual (command); stale index if someone edits `knowledge/` and forgets to run it (the PDF doesn't require automatic detection).
- ~~R-33: (RAG-01) RAG not yet validated on the VM.~~ **CLOSED** by RAG-01V1 (pgvector image, read-only mount, ingestion in container, /rag/search, 120→150 demo).
- R-34: (RAG-01 audit, LOW) Provider-response hardening: malformed/non-numeric/NaN embedding payloads should be rejected explicitly (currently dimension/count checks only). Open.
- R-35: (AGENT-01A) The grounding guard checks citations and figures, not full semantic entailment: a wrong but figure-free paraphrase citing a real chunk isn't caught mechanically. Mitigated by the prompt, temperature 0 and evidence-only passages.
- R-36: (AGENT-01A) The intent classification is model-dependent: a misclassification gives a safe but unhelpful answer (e.g. a clarification instead of an answer). The live smoke shows the real model refused a question ABOUT the injection document, and declined (conservatively) a policy question that retrieved it.
- R-37: (AGENT-01A) No rate limiting or per-customer LLM budget on `/chat` (each turn ≤ ~$0.007); acceptable for the assessment, needed before production.
- R-38: (AGENT-01A) User messages are sent to OpenRouter (xAI) for classification and answering (REQ-SEC-03); ticket data, customer ids and tokens are not.
- ~~R-39: No conversation memory.~~ **RESOLVED (AGENT-01B)**: minimal conversation state (pointer + draft), no transcripts.
- R-40: (AGENT-01AV1, INFO) One real intent call took 23.7 s (OpenRouter latency), close to the 30 s timeout; slower calls answer 503 `llm_unavailable` (safe, no false success).
- R-41: (AGENT-01B, LOW) A compromised or wrong model can trigger an unwanted handoff (no confirmation by design) or a harmless prepared draft. Bounded: same customer, enum reason, summary = the customer's own words; no ticket/lead without the user's CONFIRMAR.
- R-42: (AGENT-01B, LOW) Draft text (subject/description/need) is model-extracted and may be paraphrased; the user sees the exact stored summary before confirming (REQ-CONF-02).
- R-43: (AGENT-01B, INFO) Conversation state and service writes are not one transaction (the lead hop cannot be); the state is only a pointer and every service re-validates, so a stale pointer fails safe (invalid / nothing pending), never a wrong creation.
- R-44: (AGENT-01B, INFO) Interpretation cost about doubled (avg $0.0038/call; a turn is at most ~$0.01) with the larger schema; still within budget (R-37 rate limiting remains open).
- R-45: (AGENT-01B, INFO) Local machine memory is tight (80-92% load of 5.8 GiB during mutation runs); a background mutation run was killed by Claude Code's memory reaper and left one mutation applied (detected and restored). Mutation runs are now foreground-only with byte-exact backups and per-mutation restoration checks.

### AGENT-01A audit findings (Codex: PASS WITH LOWS; VM_VALIDATED in AGENT-01AV1)
| ID | Severity | Status |
|----|----------|--------|
| AGENT01A-01 malformed ancillary model metadata (e.g. `usage`) not hardened | LOW | **CLOSED** (fixed in AGENT-01B; closed by the AGENT-01B Codex audit) |
| R-35 grounding guard checks citations + figures, not full entailment | LOW | OPEN |
| R-37 no rate limit / per-customer LLM budget | LOW | OPEN |
| R-38 user messages sent to OpenRouter/xAI | LOW | OPEN (runtime boundary documented in vm-validation.md) |
| R-14 `T-1001` references unsupported (UUID only) | LOW | **FIXED_PENDING_REAUDIT** (AGENT-01B: customer-scoped immutable references) |
| R-36 intent classification model-dependent (safe but sometimes unhelpful) | INFO | OPEN |
| R-39 no conversation memory | INFO | **RESOLVED_PENDING_REAUDIT** (AGENT-01B) |

### AGENT-01B audit findings (Codex: FAIL -> BF1 -> BF2 -> BF3 -> PASS WITH LOWS; VM_VALIDATED in AGENT-01BV1)
| ID | Severity | Status |
|----|----------|--------|
| AGENT01B-01 confirmation bound to whatever pointer exists at lock time (re-prepare / lost response could execute an unapproved version) | HIGH | **CLOSED** (AGENT-01BF1; closed by the Codex re-audit) |
| AGENT01B-02 cancellation success from stale chat state after a concurrent confirmation | HIGH | **CLOSED** (AGENT-01BF1; closed by the Codex re-audit) |
| AGENT01BF1-01 conversation revision unchanged when the authoritative action changes outside a chat save (stale proposal could prepare B and replace A's recovery pointer) | HIGH | **CLOSED** (AGENT-01BF2; closed by the Codex re-audits) |
| AGENT01BF1-02 CANCELAR mutated the owner-scoped action before proving conversation membership | LOW | **CLOSED** (AGENT-01BF2; closed by the Codex re-audits) |
| AGENT01BF2-01 TOCTOU between the authoritative read (reconcile) and prepare (separate transactions, no row lock) | HIGH | **CLOSED** (AGENT-01BF3; closed by the Codex re-audit; VM_VALIDATED in AGENT-01BV1) |
| AGENT01BF2-02 CANCELAR could cancel other pending actions before validating the pointed action's conversation | LOW | **CLOSED** (AGENT-01BF3; closed by the Codex re-audit) |
| AGENT01BF3-01 `_touch()` creates no `chat_conversations` row when none exists | LOW | OPEN (known; documented; no blocker observed in AGENT-01BV1) |
| UI02-01 an identical re-shown draft (after confirmation_review_required) badges the earlier copy "Replaced" (not actionable, wording overstates) | LOW (UI) | OPEN |
| UI02-02 sidebar time = creation of the empty conversation slot, not the first message | LOW (UI) | OPEN |
| UI02-03 ~820 px with sidebar: 4 draft tiles ~100 px wide, long values truncated (tooltip has the full value) | LOW (UI) | OPEN |
| UI02-04 "Connected" badge is a page-load readiness check, not live (updates on reload; requests always report failures) | LOW (UI) | OPEN |
| Remaining AGENT-01B audit LOW (5) / INFO (3) items, incl. the pointer-conversation predicate note (now addressed as defense in depth) | LOW/INFO | OPEN unless the re-audit closes them |

### RAG-01 audit findings
| ID | Severity | Status |
|----|----------|--------|
| RAG01-01 | MEDIUM | **CLOSED** (RAG-01F1; Codex re-audit PASS WITH LOWS; VM-validated in RAG-01V1) |
| RAG01-02 | MEDIUM | **CLOSED** (RAG-01F1; Codex re-audit PASS WITH LOWS; VM-validated in RAG-01V1) |
| LOW: R-30 threshold/evaluation margin, R-31 OpenRouter data boundary, R-32 manual ingestion, R-34 provider-response hardening | LOW | OPEN |
| INFO: historical `evidence/10-rag/architecture.md` described per-document ingestion | INFO | **RESOLVED (docs)**: superseded note added in RAG-01V1, history kept |
| INFO: remaining audit INFO item(s) | INFO | OPEN, carried as noted by the auditor |
- R-25: (APP-03B) The webhook can be triggered by anyone with VM shell access (loopback) or on the automation network; it can't create unconfirmed leads, but it could re-dispatch already-confirmed actions (idempotent replays) or add load. Webhook header auth is a possible hardening.
- R-26: (APP-03B) n8n stores execution data (incl. the lead payload and Idempotency-Key) in its own DB; retention/pruning isn't configured (data-minimization follow-up, REQ-SEC-03).
- R-27: (APP-03B) A `confirmed` action whose hop keeps failing stays `confirmed` indefinitely (no expiry), by design for retryability; no cleanup job yet.
- R-28: (APP-03B) Leads require a test session (D-51); real prospects without credentials couldn't use this flow as-is.'` didn't reveal it. Before any VM run, check CR bytes of the exact remote command string (byte-level).
- R-21: (N8N-01) First-run owner claim window (see n8n foundation); evaluators need SSH + tunnel to use the n8n UI.
- R-22: (N8N-01) Losing or changing `N8N_ENCRYPTION_KEY` makes stored n8n credentials unreadable; it must be backed up with the `n8n_data` volume (REQ-PERS-03 documentation pending).
- R-07: Synthetic auth has no expiry, rotation policy, rate limiting or lockout; acceptable only for the assessment.
- R-08: One new DB connection per operation (up to 3 per ticket request). Local test latency was about 100 ms per request on Windows; add a pool if load or latency requires it.
- R-09: No chat endpoint exists yet, so "customer_id in chat cannot override identity" is proven at the API boundary (query, headers, free text). The agent phase must keep passing identity from the auth context, never from model output.
- R-10 (= APP02-02 LOW): Supersede scope relies on the client sending a stable `X-Conversation-ID`. Without it, or with a reused ID, a customer's flows in that group supersede each other. This is safe (the older summary just needs re-preparing), but parallel flows interfere. Mitigation: the agent always sends a unique conversation ID (D-41).
- R-11 (= APP02-03 INFO): Idempotency records and expired/superseded actions are never purged (no retention job yet); fine at assessment scale.
- R-15 (= APP02-04 INFO): The tests simulate response loss after COMMIT and failures inside the transaction, but not a real connection drop exactly during COMMIT acknowledgement. By design the outcome is resolved by a same-key retry (R-12).
- R-12: A 503 from confirm is "outcome not confirmed". The caller must retry with the same key to learn the definitive result (documented; the agent phase must implement this).
- R-13 (= APP02-05 INFO): An intermittent failure of 2 unrelated tests was observed once during a mutation run (M5) and didn't reproduce (see `evidence/05-ticket-create/mutation-checks.md`). Root cause unconfirmed. Not observed during APP-02F1 (10 + 7 groups of runs). Procedure if it recurs: stop and preserve full pytest output, the PostgreSQL log, test order, mutation state and cleanup state.
- R-14: The ticket reference format `T-1001` (PDF journey D) isn't implemented; IDs are UUIDs. Since AGENT-01A, `/chat` asks for the full UUID and says `T-1001`-style references aren't supported yet (live-tested). **AGENT-01B:** short references implemented (customer-scoped, immutable; seeds T-1001/T-1002).

## Next recommended phase

1. ~~Resolve B-06.~~ Done in DOCS-01.
2. ~~APP-02~~ Audited → fixed (APP-02F1) → re-audit PASS → **VM_VALIDATED (APP-02V1)**.
3. **APP-03A handoffs:** audited (PASS WITH LOWS) → APP03A-01 fixed in APP-03AF1 → focused re-audit PASS (**CLOSED**); VM validation still pending (with N8N-01).
4. ~~N8N-01 VM validation~~ **VM_VALIDATED (N8N-01V1)**; APP-03A handoff runtime smoke PASS in the same run.
5. ~~APP-03B~~ Implemented → audit PASS WITH LOWS → **VM_VALIDATED with real n8n (APP-03BV1)**.
6. ~~RAG retrieval~~ **DONE**: RAG-01 → RAG-01F1 (audit fixes) → RAG-01V1 **VM_VALIDATED**.
7. ~~AGENT-01A~~ **DONE**: AGENT-01A (local) -> Codex PASS WITH LOWS -> AGENT-01AV1 **VM_VALIDATED**.
8. ~~AGENT-01B~~ **DONE**: AGENT-01B -> BF1 -> BF2 -> BF3 -> Codex PASS WITH LOWS -> AGENT-01BV1 **VM_VALIDATED** (REAL n8n agent E2E: chat -> CONFIRMAR(token) -> n8n -> /internal/leads -> PostgreSQL).
9. ~~UI-01 / UI-02~~ **DONE**: evaluation client rebuilt from NEXO_UI_FREEZE_01 (UI-01) and validated end to end in the browser against the real stack (UI-02). Next: final deliverables (README walkthrough, technical documentation/PDF evidence, AI-tool disclosure: REQ-DELIV-03/04, REQ-EVID-01, REQ-AI-01/02); optional UI LOW polish (UI02-01..03).
10. ~~FINAL-01 / FINAL-02~~ **DONE**: docs, permanent VM deployment, final evidence and final PDF. **Remaining (owner):** configure a remote and push (decide on the VM address present in 3 old commits; keep `ui02-candidate` local), confirm the AI-tool list, send the delivery email with the PDF and access instructions (VM access + synthetic tokens + n8n login via a private channel).
