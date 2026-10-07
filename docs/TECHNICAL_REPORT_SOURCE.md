# Nexo AI Service Agent: technical report (source for the PDF deliverable)

> **How to produce the PDF.** Render this file with the figures referenced below. Every result here is backed by a file
> under `evidence/`. Nothing is claimed without evidence; open items are stated as such.
>
> **Placeholders:** `<VM_HOST>` and `<SSH_PORT>` stand for the VM access, which is provided privately and isn't
> included (REQ-SEC-04).

---

## 1. Executive summary

**What Nexo is.** A small, verifiable customer-service agent for the fictitious company Nexo Servicios, deployed with
Docker Compose on Ubuntu. It:
- answers from four company documents, with references (RAG on PostgreSQL/pgvector, OpenRouter embeddings);
- registers incidents and commercial requests **only after explicit confirmation of the exact summary shown**;
- reads ticket status from the business API;
- escalates to a human, always as "pending";
- creates leads only through an **n8n workflow** that writes through a private backend endpoint.

**Design rule: the LLM proposes; the backend authorizes and executes.** `x-ai/grok-4.7` (via OpenRouter) only turns a
message into a strict JSON interpretation. Identity, isolation, confirmation, idempotency and every write are
deterministic backend code.

**Validation.**
- **Automated suite:** 410 backend tests (real PostgreSQL) plus 17 web-client tests.
- **Independent audit:** four high-severity findings, all fixed and closed.
- **Real VM runs** (real PostgreSQL/pgvector, n8n, OpenRouter): accepted runs of 138/138 (RAG), 129/129 (read-only
  agent), 139/139 (confirmed actions), 28/28 (web runtime) and 35/35 (final permanent deployment).
- **Real browser E2E:** 23 scenarios against the real stack.

**Deployment.** The solution is running on the evaluation VM (FINAL-02: 35/35, including real backend and PostgreSQL
outages, backup and restore, the 120 € → 150 € change at chat level, restart persistence, and a zero-secret scan).

## 2. Requirements coverage

**Coverage table:** all 116 requirement IDs map to an implementation, evidence and a status
([`REQUIREMENTS_MATRIX.md`](REQUIREMENTS_MATRIX.md)). Include the matrix, or its summary, as an appendix.

**Status:**
- **Functional, security, reliability and Docker requirements:** all PASS.
- **PARTIAL or PENDING:** the persistent VM deployment, the PDF rendering, extra screenshots, the backup/restore
  exercise, and the owner's delivery email.

## 3. Architecture

**Content:** see [`ARCHITECTURE.md`](ARCHITECTURE.md) §1 and §9.
- **Figure 1:** the request-path diagram.
- **Table:** the services table from the README (image, ports, networks, user).

**Key decisions:**
- **Database:** PostgreSQL for everything, including pgvector. It's one engine, transactional ingestion, and the same
  backups as the rest of the data.
- **No orchestration framework:** the control flow is plain code, so it's auditable.
- **Least-privilege networks:** db only with the backend; n8n reaches only the backend; web reaches only the backend.
- **Loopback-only ports:** Docker-published ports bypass `ufw`.

## 4. RAG design

**Content:** `ARCHITECTURE.md` §2, `evidence/10-rag/architecture.md`, `calibration.json`.
- **Chunks:** one `##` section each, referenced as `<file> § <section>`. Ingestion is atomic, versioned by SHA-256, and
  re-embeds only changed sections.
- **Threshold:** `0.39`, calibrated with real embeddings. Below it, the system answers that it has no information and
  makes no model call.
- **Answering:** retrieved text is given to the model as data, never as instructions. A grounding guard blocks
  invented citations and figures.
- **Price update:** RAG-01V1 replaced 120 € with 150 €. The same reference and the same row were kept, and no 120 € text
  remained; then the original was restored. Steps are in runbook §9.

**Figures:**
- `screenshots/02-rag-drawer.jpg`: the answer with its source plus the drawer;
- RAGV table rows for absent information and for the price update.

## 5. Agent and control design

**Content:** `ARCHITECTURE.md` §1–5 and `evidence/12-agent-actions/architecture.md`.
- **Read side:** the model interprets, inside a PostgreSQL `READ ONLY` transaction.
- **Command side:** only `chat_actions` may prepare, confirm or cancel, and only through the existing services.
- **Model failures fail closed:** wrong served model, malformed output and extra fields all give 503 with no false
  success.

## 6. Confirmation and idempotency

**Content:** `ARCHITECTURE.md` §3, `AUDIT_FINDINGS.md` (AGENT01B-01/-02, BF1-01, BF2-01).
- **Version token:** each summary carries a `confirmation_token` bound to its action and payload hash. A stale or
  missing token gives a review, never an execution.
- **Deterministic gate:** CONFIRMAR and CANCELAR are matched without any model call.
- **Idempotency:** the key `chat:<conversation>:<action>` makes a replay or lost response return the same object.
- **Authoritative cancellation:** success only if the action really moved from pending to cancelled.

**Figures:** `03-critical-draft.jpg` (no ticket yet), `04-critical-created.jpg` (T-1003 + pending handoff),
`05-version-binding-B.jpg`.

## 7. n8n workflow

**Content:** `ARCHITECTURE.md` §4, `n8n/workflows/nexo-lead-create.json` (no credentials).
- **Credentials:** the backend holds only the SHA-256 of the service token, and `/internal/leads` rejects customer
  tokens.
- **n8n down:** honest 503, and the same action is recovered later.

**Figures:**
- `06-lead-draft.jpg`, `07-lead-created-n8n.jpg`, `08-n8n-down-not-completed.jpg`;
- `evidence/15-final-deployment/screenshots/11-n8n-ui-executions.jpg`: the n8n UI executions list.

## 8. Security and isolation

**Content:** `ARCHITECTURE.md` §6 and §9.
- **Identity:** SHA-256 token lookup only.
- **Isolation:** owner-scoped data access; a foreign ticket is indistinguishable from a nonexistent one.
- **Web boundary:** the server-side demo credential boundary.
- **Injection:** a message and a retrieved document both failed to change any control.
- **Secrets:** scans in every run found 0 occurrences.
- **Data minimization:** what is sent to OpenRouter is listed.

**Figures:** `10-customer-B-own-ticket.jpg`, plus UI02 table rows #17–18 and #23.

## 9. Reliability and failure handling

**Content:** `ARCHITECTURE.md` §7. A real n8n outage was exercised on the VM and in the browser. Database and LLM
outages were exercised with TEST stand-ins (local real PostgreSQL made unavailable; stub servers). The lost response was
exercised on the VM (BV1 §14). Restart persistence: BV1 §22 and UI02 #22.

## 10. Docker and Linux deployment

**Content:** README (Prerequisites, Start, Stop/backup/restore), `ARCHITECTURE.md` §9, PRE (VM initial state).
Images are pinned, with healthchecks and `restart: unless-stopped`, non-root users, no privileged containers or Docker
socket, and loopback-only ports.

## 11. Evaluation client

**Content:** `evidence/14-evaluation-client/ui01/ui01-report.md` and `ui02-browser-e2e/ui02-report.md`.
- **Origin:** a rebuild of the approved Google Stitch design (NEXO_UI_FREEZE_01). Mockup placeholders were replaced by
  the real API contract.
- **Security:** the confirmation token is hidden in memory, and the technical drawer shows real data only.

**Figures:** `01-welcome.jpg`, `09-human-handoff.jpg`.

## 12. Testing and evidence

**Content:** [`TEST_EVIDENCE_SUMMARY.md`](TEST_EVIDENCE_SUMMARY.md) (counts per run; never added together).
- **Per-case format (REQ-TEST-12):** use the UI02 scenario table and the runbook steps. Each gives input, expected,
  obtained, status and evidence.

## 13. Audit findings and remediation

**Content:** [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md). Section A covers the product findings; section B covers the
harness and infrastructure defects, with the rejected runs kept as evidence.

## 14. Known limitations and improvements before production

**Content:** [`KNOWN_LIMITATIONS.md`](KNOWN_LIMITATIONS.md).

## 15. Reproduction and autonomous evaluation instructions

**Content:** the README (Configuration, Start, Verify health, Open the web client, Logs, Stop/backup/restore) and
[`EVALUATOR_RUNBOOK.md`](EVALUATOR_RUNBOOK.md) (steps 0–15 with expected results). Test credentials are delivered
through a private channel (REQ-AUTH-05).

## 16. AI-tool disclosure

**Content:** [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md).
