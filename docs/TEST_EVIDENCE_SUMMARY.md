# Test and evidence summary

Each count belongs to **one** run, of one kind, on one commit. They are **not** added together into a global number.

**Labels:**
- **REAL:** real PostgreSQL / pgvector / n8n / OpenRouter.
- **TEST:** fixtures or scripted stand-ins, used to force failure and race conditions deterministically. TEST results
  never count as real-model or real-n8n evidence.

## 1. Automated suites (local, no paid calls)

| Suite | Commit / phase | Result | Evidence |
|---|---|---|---|
| Backend full suite (real PostgreSQL 17.11 + pgvector 0.8.7 throwaway cluster; scripted LLM, hashing embedder, FakeN8n = TEST) | **HEAD at delivery (FINAL-01)** | **410 passed, 8 skipped** (opt-in live/evidence tests) | Run during FINAL-01; includes 2 new static guards for the `web` service |
| Backend full suite | AGENT-01BF3 `61774c6` (final backend candidate) | 408 passed, 8 skipped | `evidence/12-agent-actions/agent01bf3/pytest-full.txt` |
| Backend full suite | AGENT-01A `aa1713b` | 318 passed, 7 skipped | `evidence/11-agent/pytest-full.txt` |
| Backend full suite | RAG-01 | 248 passed, 4 skipped | `evidence/10-rag/pytest-full.txt` |
| Mutation checks (each fix undone, tests must fail) | BF1, BF2, BF3, AGENT-01B, RAG | All mutants caught | `evidence/12-agent-actions/**/mutation-checks.txt`, `evidence/10-rag/mutation-checks.txt` |
| Web client: typecheck, lint, Vitest (11 UI + 6 runtime-boundary tests), production build | UI-02 `85781cf` | **17/17**, build OK | `evidence/14-evaluation-client/ui02-browser-e2e/checks.txt` |

## 2. Real VM validations (temporary deployments, full teardown after each)

| Phase | Candidate | Accepted run | What it proved | Evidence |
|---|---|---|---|---|
| APP-02V1 | `1284f98` | run 2: **80/80** | Ticket API: prepare/confirm, idempotency replay/conflict, isolation, restart persistence | `evidence/06-app02-runtime/` |
| N8N-01V1 | `e23679d` | run 2: **32/32** | n8n foundation, network boundaries, handoff smoke | `evidence/08-n8n-foundation/` |
| APP-03BV1 | REAL n8n 2.42.3 | run 2: **106/106** | Lead through the real workflow and private writer | `evidence/09-leads-n8n/` |
| RAG-01V1 | `fce4580` | **138/138** | Real embeddings, pgvector, references, threshold, **120 € → 150 € update and restore** | `evidence/10-rag/vm-validation.md` |
| AGENT-01AV1 | `aa1713b` | run 2: **129/129** (incl. in-container TEST suite 47/47) | Read-only agent with real Grok 4.7: grounded answers, absent info, ticket status, isolation, injection (message and document) | `evidence/11-agent/vm-validation.md` |
| AGENT-01BV1 | `61774c6` | run 2: **139/139** (incl. in-container TEST suite 29/29) | Confirmed actions with real Grok + real n8n: critical/normal tickets, replay, **lost response**, version binding, cancel, lead + n8n failure/recovery, handoffs, restart, logs/secrets | `evidence/13-agent-actions-vm/vm-validation.md` |
| FINAL-02 | `16c587f` (code = `85781cf`) | **35/35** (stack left running) | Permanent deployment; 120 € → 150 € at chat level + restore; real backend and PostgreSQL outages; backup + restore; restart; n8n executions (UI); final secret scan 0 | `evidence/15-final-deployment/final-deployment-report.md` |
| UI-02 | `ca86d7c` (code = `85781cf`) | run 2: **28/28** harness checks + **23 browser scenarios** | The evaluator web client in a real browser against the real stack (below) | `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md` |

**Rejected runs** are kept and labelled in each evidence folder; see [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) §B.

## 3. Real browser E2E (UI-02)

The owner's Chrome, driven through the browser extension, ran against the VM stack: real model and real n8n, desktop
viewport. All 23 scenarios PASS:

| # | Scenario |
|---|---|
| 1 | Welcome state (NEXO layout, drawer closed, real readiness) |
| 2–3 | RAG with a reference; absent information |
| 4–8 | Critical incident: no ticket before Confirm; CONFIRMAR with the hidden token and no model call; T-1003 plus a pending handoff; replay |
| 9–10 | Version binding and review; Cancel; Confirm after Cancel does nothing |
| 11 | Normal ticket |
| 12–13 | Lead through real n8n (execution id + private writer + 1 row); n8n down gives Not completed, then same-action recovery |
| 14–15 | Human handoff; data-deletion handoff |
| 16–17 | T-1001 from PostgreSQL; A/B isolation through the account card; `customer_id` spoof |
| 18–19 | Prompt injection; controlled error state |
| 20 | Technical drawer shows real values only |
| 21 | Responsive (390/820 px on identical code locally, TEST fixture; see limitations) |
| 22 | Restart and persistence |
| 23 | Secret scan of browser, bundle, logs and web image filesystem (0 occurrences) |

Screenshots: `evidence/14-evaluation-client/ui02-browser-e2e/screenshots/` (01–10 real stack; 11–12 TEST responsive).

## 4. Assessment test matrix (§7 of the PDF)

| PDF test | Status | Evidence |
|---|---|---|
| Schedule / AI price / absent data | PASS | AV1 K1–K4 + absent; UI-02 #2–3 |
| Ticket without confirmation / confirmed | PASS | BV1 §11; UI-02 #4–7 |
| Resend with the same key | PASS | APP-02V1 (API `Idempotency-Key` replay); BV1 §12; UI-02 #8 |
| Another customer's ticket | PASS | AV1; BV1 §16; UI-02 #17 |
| API unavailable | PASS | REAL on the VM: n8n down (BV1 §18; UI-02 #13), backend down and PostgreSQL down (FINAL-02 #4–5). LLM timeout/429/5xx: TEST (in-container stub matrix AV1/BV1) |
| Human request / critical incident | PASS | BV1 §11, §19; UI-02 #7, #14–15 |
| Injection in documentation | PASS | AV1 P3 (temporary `05_injection_test.md` retrieved top-1, authorized nothing) and TEST S5 |
| Stack restart | PASS | BV1 §22; UI-02 #22; FINAL-02 #8 |
| 120 € → 150 € | PASS | RAG-01V1 (retrieval) and FINAL-02 #2–3 (chat answer "150 € más IVA", same reference; restored) |
| Lead confirmed through n8n | PASS | APP-03BV1; BV1 §17; UI-02 #12 |
