# RAG-01V1 — VM validation of referenced pgvector retrieval

**Result: PASS. 138/138 checks, 0 failures.** REAL VM / REAL pgvector 0.8.7 (official image) / REAL OpenRouter embeddings.
Candidate `fce4580cdfdcfa569ec43ee4b40c56caca2415db` (RAG-01 + RAG-01F1, Codex re-audit PASS WITH LOWS). Run 2026-10-07,
one owner-run SSH session; temporary only; fully cleaned up. Full log: `vm-run-rag01v1.txt`. Harness: `vm-validate.sh`.
No application, compose or corpus change. No chat/completions call. n8n not started (not needed for RAG).

## How the OpenRouter key was handled
- **Read locally** from the git-ignored `.env` and sent as the first line of the SSH session's **stdin** (the encrypted
  stream), followed by the git bundle. It never appeared in any command's arguments, locally or on the VM. I verified
  that the remote command string doesn't contain it.
- **On the VM:** `read` (a bash builtin) → `$WORK/ork`, mode 600 inside a 700 directory → temporary `.env` (600) →
  deleted with the directory at cleanup.
- **Never printed.** The raw log contains it 0 times; on the VM, the run log and container logs contain it 0 times.
- **Pre-run framing bug, caught locally:** `.env` has no trailing newline, so the first command draft would have glued
  the key to the bundle header. Fixed (`tr -d '\r\n'; echo`) and verified byte-exact (bundle SHA-256 matched on the VM).

## Results
| Area | Evidence (section of the log) | Result |
|------|-------------------------------|--------|
| Exact candidate | §1–2: bundle sha256 = local; checkout = fce4580; clean tree | PASS |
| Startup / migrations | §4–5: db + backend healthy; migrations 0001–0007 applied; `schema_migrations` checksums == committed SQL (7 rows); PostgreSQL 17.11; **vector 0.8.7**; `knowledge_chunks.embedding vector(1536)`; `/health` 200, `/health/ready` 200 (`schema_version 0007_knowledge`) | PASS |
| Knowledge mount | §7: `./knowledge → /srv/knowledge rw=false`; write refused; `ls -A` = exactly the 4 canonical files; container sha256 == commit blob for all 4 | PASS |
| Real ingestion | §10: `{documents 4, new 4, chunks 10, embedded 10, model openai/text-embedding-3-small}`; DB: 4 docs, 10 chunks, 10 distinct keys, dims 1536, one model; output = one counts line (no key/vectors) | PASS |
| Re-ingest | §11: `embedded 0, unchanged 4`; documents + chunks byte-identical (ids, hashes, models, vector md5, `updated_at`) | PASS |
| Supported retrieval | §12: 10 queries, all `found` with the expected chunk accepted. A schedule → `02_support_policy.md § Horario de atención` 0.6988; B services → `01_services.md § Catálogo de servicios` 0.5169; C commercial → `03_commercial_policy.md § Tarifas` 0.5372 (all top-1). Password query: expected chunk at rank 2 (0.4371), as in calibration | PASS |
| No evidence | §13: **Barcelona → `insufficient`, `matches: []`, best 0.369 < 0.39**; phone 0.3067; mobile apps 0.3181; paella 0.1674; bitcoin 0.2499; Australia 0.0665. No `answer` field anywhere | PASS |
| Reference integrity | §14: for 7 accepted hits: API filename == document row `reference` == `path` == file re-parsed in the container; `document_version` == row sha == sha256(mounted file) == sha256(commit blob); `chunk_sha256` == row sha == sha256(DB content) == chunk sha re-parsed from the mounted file; API text == DB content | PASS |
| 120 € → 150 € | §15, **temporary copy only**: 1 occurrence; ingest copy → 0 embedded; retrieval shows 120 €; one-line diff; committed file untouched; re-ingest → `updated 1, embedded 1, unchanged 3`; 0 rows with 120 €; same row id 6 now 150 €; same 10 keys/ids; retrieval → `03_commercial_policy.md § Tarifas` with 150 €, version = sha256(edited file); **restore** from canonical → 120 € back, all versions == committed files; temporary copy deleted (host + container) | PASS |
| Model consistency | §16: configured == indexed == API model = `openai/text-embedding-3-small`; 1536 in code and in every vector; one model in chunks and documents | PASS |
| Atomic failure smoke (**TEST providers**) | §17, scratch DB on the real VM PostgreSQL/pgvector, deterministic TEST-ONLY providers (NOT OpenRouter): provider failure on call 2 → index identical; DB failure during publication → full rollback; configured ≠ indexed model and mixed-model index → `index_model_mismatch` with 0 provider calls; scratch DB dropped; real index md5 unchanged | PASS |
| Auth / input | §18: A and B identical shared results; missing/invalid token 401; `customer_id` 422; malformed `X-Conversation-ID` 400; top_k 0/6/"abc" 422; empty/whitespace/501-char/missing query 422; 500 chars accepted | PASS |
| Traceability | §19: 23 `rag_search` events with request_id, conversation_id, customer_id, query_length, query_fp (== sha256[:12]), top_k, model, result, accepted, best_score, chunk_ids, source_ids, status, duration_ms; rejected request recorded (400, `InvalidConversationHeader`, no conversation id echoed) | PASS |
| Secrets | §19: OpenRouter key, both customer tokens and the DB password appear 0× in the run log and container logs; no `Bearer`/Authorization values; no raw embeddings; no raw query text or chunk content in backend logs | PASS |
| Network | §6: only `127.0.0.1:8000` added; db has no host port; no :5432/:5678; public listeners only :9922. Backend reached OpenRouter over HTTPS (ingestion + 23 searches succeeded); the configured base URL is the default `https://openrouter.ai/api/v1`. Other outbound traffic: none in the code paths exercised and n8n not running. Not packet-captured (no sudo, by policy) | PASS |
| Cleanup | §21–22: `down -v`; images added by the run removed (VM had 0 images before and after); build cache 0; 0 containers, 0 volumes, only default networks; listeners back to :9922 + local DNS; temporary directory (checkout, .env, key file, bundle, driver, demo copy) removed | PASS |

Scores match the local calibration to within ±0.0006 (e.g. bitcoin 0.2499 vs 0.2505): small embedding nondeterminism
(R-30), far from the 0.39 threshold except Barcelona (0.369, margin 0.021, as documented).

## What this does not cover
- The agent / answer generation (next phase).
- REQ-INJ-01.
- A permanent deployment.
- Packet-level egress capture.
