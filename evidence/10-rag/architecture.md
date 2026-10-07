> **SUPERSEDED IN PART (2026-10-07):** the *Ingestion* bullet below describes RAG-01's original per-document
> transactions. **RAG-01F1** replaced it: plan → all embeddings first → ONE advisory-locked transaction (all-or-nothing,
> serialized), and references bound to the real file name. See `rag01f1/root-cause.md` and `PROJECT_STATE.md`.
> VM validation: `vm-validation.md`. The rest of this document is unchanged.

# RAG-01 — Referenced pgvector retrieval (retrieval only, no answer generation)

Status: **local PASS** with real PostgreSQL 17.11 + **pgvector 0.8.7** (built from the official source, same version as
production) and a **live OpenRouter embeddings smoke**. No chat/completions call. Not deployed.

## Requirements (PDF authoritative)
| Requirement | Implementation |
|-------------|----------------|
| REQ-RAG-07 / REQ-KB-01..04: create and index the four §5 documents | `knowledge/01_services.md`, `02_support_policy.md`, `03_commercial_policy.md`, `04_security_policy.md`: PDF text **verbatim** (test), plus a metadata header and `##` section headings |
| REQ-RAG-02: references to document **and section** | every hit carries `reference = "<file> § <section>"`, `chunk_id`, `document_version` (sha256 prefix) |
| REQ-RAG-03: acknowledge absent information | calibrated threshold → `evidence: "insufficient"` with zero matches |
| REQ-RAG-01/04: answer via RAG, invent nothing | retrieval returns evidence only; no generated text exists in this phase |
| REQ-RAG-05 / REQ-INJ-02: documents are data | chunks are returned as data fields; nothing in them is executed or interpreted |
| REQ-RAG-06: RAG doesn't replace live data | the corpus holds no ticket/lead state; ticket status stays in the Business API |
| REQ-RAG-08: 120 € → 150 € update | edit the file, re-run ingestion: only that chunk is re-embedded; no "120 €" row remains (evidence) |
| REQ-LLM-02/03: OpenRouter; document the embeddings strategy | this document + PROJECT_STATE |
| REQ-TRACE-02 (model, sources) | `rag_search` audit: model, chunk_ids, source_ids, scores, latency |

**Corpus scope decision:** the RAG-01 brief suggested a "ticket/help guidance" document. The PDF names exactly four
documents with fixed content and nothing about incident-reporting guidance, so that document was **not** created
(it would invent facts). The PDF wins.

## Pipeline
```
knowledge/*.md ──parse──► sections (## headings) ──► chunks (title — section + body; sha256)
        │                                                     │ only new/changed chunks
        │                                                     ▼
        │                                OpenRouter POST /api/v1/embeddings
        │                                model openai/text-embedding-3-small → vector(1536)
        ▼                                                     ▼
knowledge_documents (source_id, reference, content_sha256, embedding_model)
knowledge_chunks    (chunk_key, section, content, content_sha256, embedding_model, embedding vector(1536))
        ▲
POST /rag/search ──embed query (same model)──► ORDER BY embedding <=> query (exact cosine) LIMIT top_k
        └──► score = 1 - distance; accepted iff score ≥ RAG_MIN_SCORE → {evidence: found|insufficient, matches[...]}
```

## Design facts
- **Embeddings:** OpenRouter `openai/text-embedding-3-small`. Dimension **verified live = 1536** before the schema was
  frozen (2 probe vectors, 12 tokens, $0.00000024). The provider sits behind a small `EmbeddingProvider` interface;
  production uses `OpenRouterEmbeddingProvider` (response order and dimension checked). Without `OPENROUTER_API_KEY`
  the provider is `None` and search answers 503: **never a silent fake**. The TEST-ONLY hashing provider lives in
  `tests/rag_fakes.py`, outside the application package.
- **Chunking:** deterministic and heading-aware. One chunk per `##` section; paragraphs grouped up to 1200 chars only if a
  section is longer; no overlap (sections are short and self-contained). Chunk text is prefixed with `<title> — <section>`
  so the vector carries context. Key `<source_id>#<slug(section)>` stays stable when other sections change. CRLF/LF
  doesn't change identity.
- **Ingestion** (`python -m app.rag_ingest [--dir]`): checksums the documents, embeds only chunks whose
  `(content_sha256, model)` changed, upserts, deletes stale chunks, deletes documents whose file disappeared (chunks
  cascade), one transaction per document (embeddings fetched **before** the transaction, so a provider outage leaves the
  previous index intact), and prints **counts only**.
- **Retrieval:** exact cosine through pgvector (`<=>`); no ANN/HNSW (10 chunks). Ties are broken by `chunk_key` for
  determinism.
- **Model/index consistency:** each chunk stores its `embedding_model`. Search refuses (503 `index_model_mismatch`) if the
  index mixes models or the configured model differs from the indexed one; the column type rejects any other dimension.
  An empty index answers 503 `index_not_ready` (not "no evidence").
- **Threshold:** calibrated with the real model (`calibration.json`): **0.39** = midpoint between the highest
  non-supported score (unrelated or in-domain-absent, 0.369) and the lowest supported expected-chunk score (0.4195).
  Supported 15/15 accepted; non-supported 0/9 accepted. Margin ~±0.03: a conservative default, overridable with
  `RAG_MIN_SCORE`.
- **Shared corpus:** identity is required (authenticated endpoint) but can't scope or change results (tested: A and B
  get identical matches; `customer_id` fields are rejected).

## API (diagnostic; later used by the agent)
`POST /rag/search` (Bearer), body `{query: 1..500 chars, top_k: 1..5 (default 3)}`, unknown fields → 422; invalid
`X-Conversation-ID` → 400. Response: `{query, evidence: found|insufficient, matches: [{source_id, title, section,
chunk_id, reference, document_version, chunk_sha256, score, text}], best_score, min_score, model}`. **No `answer` field.**
Failures → 503 with a code: `rag_unavailable` (no key), `embedding_unavailable`, `index_model_mismatch`, `index_not_ready`,
`database_unavailable`.

## Traceability
Audit `rag_search`: request_id, conversation_id, customer_id, `query_length`, `query_fp` (sha256 prefix, **not the raw
query**), top_k, model, result (found/insufficient/error), accepted, best_score, chunk_ids, source_ids, duration, error
code. Never logged: key, Authorization header, embeddings, raw query, chunk text (tested). Ingestion prints counts only.

## Data sent to OpenRouter (REQ-SEC-03)
Ingestion sends the four synthetic corpus chunks; search sends the user's query text. Nothing else is sent: no customer
ID, tokens, ticket or lead data. Queries are user-typed and may contain personal data in a real deployment, so the
agent phase should keep queries minimal.

## Future prompt-injection boundary (not solved here; for the agent phase)
- The user query is **untrusted input**; it's only embedded, never interpreted as instructions.
- Retrieved chunks are **evidence/data** (REQ-RAG-05, REQ-KB-04): the agent must quote them as data, never follow them as
  system instructions.
- Citations must come **only** from `matches[].reference`/`chunk_id`; the model must not invent references.
- Tool permissions (tickets/leads/handoffs) come from the backend's auth/confirmation rules, never from retrieved text.
- REQ-INJ-01 (an injection test document) belongs to the agent phase, where there is an LLM to try to subvert.

## Known limitations
Thin threshold margin on a small (24-query) evaluation set; embeddings vary slightly between calls (e.g. 0.2501 vs
0.2505); the threshold proves *relevance*, not that a chunk *answers* the question (the agent must still check);
Spanish corpus (queries in other languages work but score lower, e.g. the English paraphrase 0.511); no automatic
re-ingestion on file change (run the command; the PDF allows this); local test pgvector is a source build
(production uses the official image).
