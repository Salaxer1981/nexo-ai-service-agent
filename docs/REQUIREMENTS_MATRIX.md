# Requirements matrix (all 116 IDs)

**What this maps.** Every requirement of the assessment PDF, using the IDs of
[`ASSESSMENT_REQUIREMENTS.md`](ASSESSMENT_REQUIREMENTS.md), maps to its implementation, its evidence and a status. The
PDF is authoritative. Statuses mean:
- **PASS:** implemented and evidenced.
- **PARTIAL:** something remains, stated in the row.
- **PENDING (owner):** an action only the owner can take.
- **N/A:** a process item with no artefact.

## Evidence keys
| Key | Location |
|---|---|
| UI02 | `evidence/14-evaluation-client/ui02-browser-e2e/ui02-report.md`: real browser against the real VM stack |
| BV1 | `evidence/13-agent-actions-vm/vm-validation.md`: AGENT-01BV1, real Grok + real n8n, 139/139 |
| AV1 | `evidence/11-agent/vm-validation.md`: AGENT-01AV1, read-only agent, real Grok, 129/129 |
| RAGV | `evidence/10-rag/vm-validation.md`: RAG-01V1, real embeddings + pgvector, 138/138 |
| A2V | `evidence/06-app02-runtime/summary.md`: APP-02V1 ticket API on the VM, 80/80 |
| N8V | `evidence/08-n8n-foundation/`: N8N-01V1, 32/32 |
| L3V | `evidence/09-leads-n8n/`: APP-03BV1, lead through real n8n, 106/106 |
| PRE | `evidence/00-preflight/`, `evidence/01-docker/`, PROJECT_STATE "VM environment" / "Docker status" |
| T | Automated tests in `tests/` (410 passed / 8 skipped at delivery) and `src/frontend/src/test/` (17/17) |
| AUD | [`AUDIT_FINDINGS.md`](AUDIT_FINDINGS.md) |
| F2 | `evidence/15-final-deployment/final-deployment-report.md`: FINAL-02, permanent deployment + final real evidence, 35/35 |

## Matrix

### Objective and scope
| ID | Implementation | Evidence | Status / limitation |
|---|---|---|---|
| REQ-GEN-01 | Whole solution: RAG, tickets, leads, ticket status, handoffs, on the Ubuntu VM with Docker | UI02, BV1, F2 | **PASS**. Deployed, validated, and left running on the VM (FINAL-02) |
| REQ-GEN-02 | Controls: auth, confirmation, idempotency, audit, tests | AUD, T, BV1 | **PASS** |
| REQ-GEN-03 | Delivery timing | — | N/A (owner/email) |
| REQ-GEN-04 | VM resources and initial state documented | PRE | **PASS** |
| REQ-GEN-05 | Blockers requested (OpenRouter key/budget/model, Docker install authorization) | PROJECT_STATE "Open blockers", "OpenRouter" | **PASS** |
| REQ-GEN-06 | Synthetic data only (seed customers, `example.test` addresses); no emails or messages sent | `0002_synthetic_seed.sql`, BV1 | **PASS** |
| REQ-GEN-07 | Incomplete items declared | this matrix, `KNOWN_LIMITATIONS.md` | **PASS** |

### Architecture and responsibilities
| ID | Implementation | Evidence | Status |
|---|---|---|---|
| REQ-ARCH-01 | `compose.yaml` (db, backend, n8n, web) | BV1, UI02 | **PASS** |
| REQ-ARCH-02 | n8n workflow `nexo-lead-create` integrated in the lead confirmation | L3V, BV1 §17, UI02 #12 | **PASS** |
| REQ-ARCH-03 | pgvector RAG with `<file> § <section>` references | RAGV, AV1, UI02 #2 | **PASS** |
| REQ-ARCH-04 | `/chat` agent (FastAPI + Grok via OpenRouter) | AV1, BV1 | **PASS** |
| REQ-ARCH-05 | PostgreSQL tables for tickets, leads, handoffs, plus the API | A2V, L3V, BV1 | **PASS** |
| REQ-ARCH-06 | Web chat (`web` service) | UI02 | **PASS** |
| REQ-ARCH-07 | JSON audit log per request, correlated by request ID / conversation | BV1 §24, UI02 | **PASS** |
| REQ-RESP-01 | The agent interprets, retrieves and proposes; it never executes | `docs/ARCHITECTURE.md`, AV1 | **PASS** |
| REQ-RESP-02 | RAG only for knowledge; live data from the API | AV1, UI02 #16 | **PASS** |
| REQ-RESP-03 | Leads only through the n8n workflow → `/internal/leads` | L3V, BV1 §17 | **PASS** |
| REQ-RESP-04 | The API validates permissions, data and idempotency, and stores | A2V, T | **PASS** |
| REQ-RESP-05 | The web client covers the complete journey | UI02 | **PASS** |

### Infrastructure and LLM
| ID | Implementation | Evidence | Status |
|---|---|---|---|
| REQ-INFRA-01 | Initial VM state documented | PRE | **PASS** |
| REQ-INFRA-02 | Docker + Compose installed (owner-authorized) and used on the VM | PRE, BV1 | **PASS** |
| REQ-INFRA-03 | SSH and `ufw` untouched; loopback-only ports | PRE, BV1 §6 | **PASS** |
| REQ-LLM-01 | Key obtained privately; EUR 30 budget and model selection confirmed with the contact | PROJECT_STATE "OpenRouter" | **PASS** |
| REQ-LLM-02 | OpenRouter for chat and embeddings | AV1, RAGV | **PASS** |
| REQ-LLM-03 | Embeddings strategy documented (text-embedding-3-small, 1536 d, threshold calibration) | `evidence/10-rag/architecture.md`, `calibration.json` | **PASS** |
| REQ-LLM-04 | Served model logged per call | BV1 §24 | **PASS** |
| REQ-LLM-05 | Reasoning excluded and not stored | BV1 §24, UI02 #23 | **PASS** |

### RAG and knowledge base
| ID | Implementation | Evidence | Status / limitation |
|---|---|---|---|
| REQ-RAG-01 | Questions on services, hours, prices and procedures answered from RAG | AV1 K1–K4, UI02 #2 | **PASS** |
| REQ-RAG-02 | References `<file> § <section>` | AV1, UI02 #2 | **PASS** |
| REQ-RAG-03 | Absent information acknowledged (no model answer below the threshold) | AV1, UI02 #3 | **PASS** |
| REQ-RAG-04 | No invented prices or deadlines (grounding guard on figures and citations) | AV1 (K3, blocked invented figures) | **PASS** |
| REQ-RAG-05 | Documents passed as data, never as system instructions | AV1 P3/S5 | **PASS** |
| REQ-RAG-06 | Ticket status never from RAG | UI02 #16 | **PASS** |
| REQ-RAG-07 | The four documents in `knowledge/`, indexed | RAGV (4 docs / 10 sections) | **PASS** |
| REQ-RAG-08 | 120 € → 150 € update: re-ingest, same reference, old price gone, canonical corpus restored; procedure in README / runbook §9 | RAGV, F2 #2–3 | **PASS**: retrieval and chat answer ("150 € más IVA", same reference), then restored to 120 € |
| REQ-KB-01 | `knowledge/01_services.md` | T (verbatim content tests), RAGV | **PASS** |
| REQ-KB-02 | `knowledge/02_support_policy.md` | T, RAGV, UI02 #2 | **PASS** |
| REQ-KB-03 | `knowledge/03_commercial_policy.md` | T, AV1 K3/K4 | **PASS** |
| REQ-KB-04 | `knowledge/04_security_policy.md`, and enforced in code (deletion → handoff; no foreign data) | T, UI02 #15, #17 | **PASS** |

### Business API
| ID | Implementation | Evidence | Status / limitation |
|---|---|---|---|
| REQ-API-01 | `POST /tickets/prepare` + `/confirm`; `GET /tickets/{id}`; `POST /leads/prepare` + `/confirm` (→ n8n); `POST /handoffs`; `GET /health` (adapted routes documented in the README) | A2V, L3V, T | **PASS** |
| REQ-API-02 | Pydantic validation (extra fields forbidden), bearer authentication | T, A2V | **PASS** |
| REQ-API-03 | The ticket, lead and handoff schemas have every minimum field, generated UUIDs and T-references | migrations 0001–0009, BV1 | **PASS** |
| REQ-API-04 | Two synthetic customers with one ticket each (T-1001 / T-1002); initial data, backup/restore and reset documented in the README | `0002_synthetic_seed.sql`, README, F2 #6–7 | **PASS**: backup and restore executed on the VM (a post-backup record removed by the restore, everything else identical) |

### Tickets, leads, n8n, handoffs
| ID | Implementation | Evidence | Status |
|---|---|---|---|
| REQ-TICKET-01 | Data collection, classification, critical/normal priority | BV1 §11, §13; UI02 #4, #11 | **PASS** |
| REQ-TICKET-02 | Summary card plus confirmation before creating | UI02 #4–7 | **PASS** |
| REQ-TICKET-03 | Real UUID and T-reference from the committed row | BV1 §11, UI02 #7 | **PASS** |
| REQ-TICKET-04 | API failure → no claim of creation | T (DB down), BV1, UI02 #13/#19 | **PASS** |
| REQ-TICKET-05 | Status from PostgreSQL via the API, follows DB changes | BV1 §15, UI02 #16 | **PASS** |
| REQ-LEAD-01 | Company, contact, need, email (the e-mail must appear in the message) | BV1 §17, UI02 #12 | **PASS** |
| REQ-LEAD-02 | Confirmation, then n8n workflow → private writer | L3V, BV1 §17, UI02 #12 | **PASS** |
| REQ-LEAD-03 | No prices, discounts, contracts or dates promised (stated in the summary) | UI02 #12 | **PASS** |
| REQ-N8N-01 | Functional workflow in the agent operation | L3V, BV1, UI02 | **PASS** |
| REQ-N8N-02 | `n8n/workflows/nexo-lead-create.json` without credentials | T (`test_lead_workflow_static.py`) | **PASS** |
| REQ-HANDOFF-01 | Critical incident, explicit request, unsafe case (deletion) | BV1 §11/§19, UI02 #7/#14/#15 | **PASS** |
| REQ-HANDOFF-02 | `handoffs` table | BV1, UI02 | **PASS** |
| REQ-HANDOFF-03 | "Pending, nobody has picked it up, no guaranteed time" | UI02 #7/#14 | **PASS** |
| REQ-HANDOFF-04 | No emails or messages sent | code, BV1 | **PASS** |

### Authentication, isolation, confirmation, idempotency
| ID | Implementation | Evidence | Status |
|---|---|---|---|
| REQ-AUTH-01 | Identity = SHA-256(bearer) lookup only | T, BV1 §16 | **PASS** |
| REQ-AUTH-02 | Chat `customer_id` has no authority | BV1 §16, UI02 #17 | **PASS** |
| REQ-AUTH-03 | Two synthetic customers with tokens | seed + `.env` | **PASS** |
| REQ-AUTH-04 | API validates authentication and permissions on every request | T, A2V | **PASS** |
| REQ-AUTH-05 | Tokens generated at deployment and shared privately; never in docs or the PDF | README, secret scans | **PASS** |
| REQ-ISO-01 | Owner-scoped queries in the backend | T, BV1 §16 | **PASS** |
| REQ-ISO-02 | Foreign ticket = nonexistent, no content leaked | A2V, BV1 §16, UI02 #17 | **PASS** |
| REQ-ISO-03 | No foreign tickets or contacts shown (also under injection) | UI02 #17/#18 | **PASS** |
| REQ-CONF-01 | Ticket confirmation gate | UI02 #4–7 | **PASS** |
| REQ-CONF-02 | Version token; changed data needs a new confirmation | AUD (AGENT01B-01), BV1 §21, UI02 #9 | **PASS** |
| REQ-CONF-03 | Lead confirmation gate | UI02 #12 | **PASS** |
| REQ-CONF-04 | No record before; real ID after | BV1 §11, UI02 #4–7 | **PASS** |
| REQ-IDEMP-01 | Idempotency keys (API `Idempotency-Key`; chat `chat:<conversation>:<action>`) | A2V, BV1 §12/§14, UI02 #8 | **PASS** |
| REQ-IDEMP-02 | Enforced by the API / services | T | **PASS** |

### Failures, injection, persistence
| ID | Implementation | Evidence | Status / limitation |
|---|---|---|---|
| REQ-FAIL-01 | Timeouts, errors and outages give 503/502 + code (LLM, DB, backend, n8n) | T (stub matrix), BV1 §18, UI02 #13, F2 #4–5 | **PASS**: real n8n, backend and PostgreSQL outages on the VM; LLM timeout/429/5xx via TEST stubs |
| REQ-FAIL-02 | Lost response: replay returns the same object; documented | BV1 §14, `ARCHITECTURE.md` §3 | **PASS** |
| REQ-FAIL-03 | No false success | BV1 §18, UI02 #13/#19 | **PASS** |
| REQ-INJ-01 | Test document `05_injection_test.md` (temporary) retrieved top-1 and authorized nothing | AV1 P3 | **PASS** |
| REQ-INJ-02 | Documents are data | AV1 S5, UI02 #18 | **PASS** |
| REQ-PERS-01 | Named volumes | BV1 §22 | **PASS** |
| REQ-PERS-02 | Restart → data preserved, service recovered | BV1 §22, UI02 #22 | **PASS** |
| REQ-PERS-03 | Backup, restore and stop/start documented (README) and executed | README, F2 #6–8 | **PASS** |

### Docker, traceability, security
| ID | Implementation | Evidence | Status |
|---|---|---|---|
| REQ-DOCKER-01 | `compose.yaml`, Dockerfiles, `.env.example` (placeholders only) | T (`test_compose.py`) | **PASS** |
| REQ-DOCKER-02 | Pinned images (no `latest`) | T | **PASS** |
| REQ-DOCKER-03 | Volumes, `restart: unless-stopped`, healthchecks | T, BV1 | **PASS** |
| REQ-DOCKER-04 | Only loopback ports; DB unpublished; n8n UI via a tunnel | T, BV1 §6, UI02 | **PASS** |
| REQ-DOCKER-05 | No privileged containers or Docker socket; users and permissions documented | T, `ARCHITECTURE.md` §9 | **PASS** |
| REQ-TRACE-01 | Message → retrieval → decision → confirmation → workflow → API → result, one request ID | BV1 §24, UI02 #12 | **PASS** |
| REQ-TRACE-02 | Request ID, sources, action, result, error, duration, model | BV1 §24 | **PASS** |
| REQ-TRACE-03 | Correlated by request and conversation | BV1 §24 | **PASS** |
| REQ-SEC-01 | No credentials in code, screenshots, logs or docs (scans every run, plus a final repo scan) | BV1 §24, UI02 #23, FINAL-01 scan | **PASS** |
| REQ-SEC-02 | Secrets never logged | same | **PASS** |
| REQ-SEC-03 | Minimal data to OpenRouter (no IDs, tokens or rows); documented | AV1, `ARCHITECTURE.md` §9 | **PASS** |
| REQ-SEC-04 | No OpenRouter key or VM access in docs or attachments | FINAL-01 scan | **PASS** for current files (the VM address appears in 3 old commits, no credentials: see limitations) |

### Tests, evidence, delivery, AI
| ID | Implementation | Evidence | Status / limitation |
|---|---|---|---|
| REQ-TEST-01..10 | Minimum test matrix | [`TEST_EVIDENCE_SUMMARY.md`](TEST_EVIDENCE_SUMMARY.md) §4 | **PASS** |
| REQ-TEST-11 | Automated tests plus reproducible harnesses | T, `evidence/*/vm-*.sh` | **PASS** |
| REQ-TEST-12 | Per case: steps, expected, obtained, status, evidence | Runbook; UI02 and F2 scenario tables; final PDF | **PASS** |
| REQ-TEST-13 | Failures declared; rejected runs kept | AUD §B | **PASS** |
| REQ-EVID-01 | Readable screenshots: journeys, RAG sources, n8n executions, persisted records, access controls, errors, restart, knowledge update | UI02 `screenshots/`, F2 `screenshots/`, final PDF | **PASS** |
| REQ-EVID-02 | Screenshots explained (captions and scenario tables) | UI02, F2, final PDF | **PASS** |
| REQ-EVID-03 | No secrets in evidence or screenshots | scans | **PASS** |
| REQ-DELIV-01 | Operational solution on the VM, accessible by the documented procedure (SSH tunnel to `127.0.0.1:8080`) | F2 (35/35; left running, `restart: unless-stopped`) | **PASS** |
| REQ-DELIV-02 | Repository: Compose, dependencies, `.env.example`, RAG documents, n8n export | repo | **PASS** |
| REQ-DELIV-03 | Technical documentation **in PDF** | `docs/report/Nexo_Technical_Report.pdf` (generated from the repo docs and evidence) | **PASS** |
| REQ-DELIV-04 | Autonomous-evaluation instructions in the README **and** the PDF | README, [`EVALUATOR_RUNBOOK.md`](EVALUATOR_RUNBOOK.md), PDF chapter 4 | **PASS** |
| REQ-DELIV-05 | The 9 items: access, start/stop/status, private credentials, synthetic identities, steps with expected results, errors/duplicates/foreign access, RAG update, logs/n8n/records, recovery/restore | README + runbook | **PASS** |
| REQ-DELIV-06 | Completed and pending list, plus limitations | this matrix, `KNOWN_LIMITATIONS.md` | **PASS** |
| REQ-DELIV-07 | Reply to the invitation email with the PDF and access | — | **PENDING (owner)** |
| REQ-AI-01 / REQ-AI-02 | AI tools, purpose and validation declared | [`AI_DISCLOSURE.md`](AI_DISCLOSURE.md) | **PASS** (owner to confirm the tool list) |

## Summary
- **Implementation:** every functional, security, reliability, Docker and delivery-artefact requirement is implemented
  and evidenced with the real stack. The solution is running on the VM (FINAL-02).
- **Remaining owner actions (no product code):**
  - publish the repository (DELIV-02 access);
  - reply to the invitation email with the PDF and access details (DELIV-07);
  - confirm the AI-tool list (AI-01/02).
