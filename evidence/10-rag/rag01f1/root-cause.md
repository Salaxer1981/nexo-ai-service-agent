# RAG-01F1 — Root cause and fix for audit findings RAG01-01 and RAG01-02

Baseline: `43ead8d` (RAG-01). Audit: independent Codex, FAIL (0 BLOCKER, 0 HIGH, 2 MEDIUM, 4 LOW, 2 INFO).
This phase fixes ONLY the two MEDIUM findings. Retrieval, threshold, auth, corpus content and provider are unchanged.
The original RAG-01 evidence in `evidence/10-rag/` is kept as it was; its `architecture.md` describes the old
per-document ingestion and is superseded on that point by this file.

## RAG01-01 (MEDIUM): ingestion was neither atomic nor serialized

**Root cause.** `ingest()` looped over documents, and each iteration did *embed this document → open a transaction →
write it → COMMIT*. Removed documents were deleted in a final, separate transaction. So:
- a provider failure on document N left documents 1..N-1 already committed. During a model change this produced a
  **mixed-model index**: search then answers 503 `index_model_mismatch` until someone re-runs ingestion successfully;
- a DB failure part-way had the same effect;
- two ingestions running at the same time could interleave per-document commits. The result mixed two corpus
  versions or two models, because no lock existed.

The old claim that "a provider outage leaves the previous index intact" was only true per document, not per corpus.

**Fix** (`src/backend/app/rag.py`, `ingest()` / `_publish()`):
1. **Plan**: parse and validate *all* files (a corpus error aborts before any provider/DB work), then read the current
   index without locks.
2. **Embed everything first**: every chunk whose `(content_sha256, model)` differs from the index is embedded.
   No transaction is open during OpenRouter calls. Any provider error propagates **before any write**.
3. **Publish once**: ONE transaction →
   `pg_advisory_xact_lock(INGEST_LOCK_KEY)` (dedicated, stable key derived from `sha256("nexo:rag_ingest:v1")`) →
   **re-read the index under the lock** → upsert all documents, upsert changed chunks with their vectors, update
   ordinals, delete stale chunks, delete removed documents → **final consistency check** (chunk keys == desired
   set, exactly one model, documents on the same model) → single COMMIT. Any failure rolls back everything; the lock
   is released automatically at COMMIT/ROLLBACK.
4. **Re-check after the lock**: if another ingestion committed between our plan and our lock, a chunk we need may
   now differ from what we embedded. We then roll back and re-plan, at most 3 attempts. Otherwise we raise and
   publish nothing. We never publish a chunk without its matching embedding.

**Concurrency semantics.** Publications are serialized. Each one replaces the index with one **complete** corpus
generation; the last one to publish wins as a whole. A second ingestion **waits** on the lock (it doesn't fail or
interleave). The lock is held only for the publication (milliseconds for 10 chunks), never during provider calls.

**Cost of the design.** If another ingestion wins the race, embeddings may be computed twice (a re-plan). That's
acceptable for a 4-document corpus that is updated by hand.

## RAG01-02 (MEDIUM): citation filename came from editable metadata

**Root cause.** `parse_document()` returned `Document.reference = meta["reference"]`, read from the front matter.
A file `01_services.md` whose header said `reference: 02_support_policy.md` would be indexed and cited as
`02_support_policy.md § …`, so the citation would point at the wrong document.

**Fix (option B, smallest change compatible with the corpus format).** The `reference:` line is kept for readability, but:
- ingestion **fails closed** (`CorpusError`, before any provider call or DB write) unless `reference == path.name`;
- the stored reference is taken from `path.name`, not from the metadata.
The four canonical files already satisfy this, so no corpus change was needed.

## Proof
| Item | File |
|------|------|
| Failed V1→V2 migration (call 1 OK, call 2 fails): index byte-identical, no V2 rows, V1 search works | `failed-model-migration-proof.txt` |
| B runs a full ingestion inside A's embedding phase: final index = one complete generation; lock wait observed in `pg_locks` | `concurrent-ingestion-proof.txt` |
| `01_services.md` claiming `02_support_policy.md`: refused, 0 provider calls, index unchanged; normal references resolve to real files | `reference-mismatch-proof.txt` |
| New tests on the fix: 8/8 pass | `atomicity-tests-fixed.txt` |
| Same tests vs original `43ead8d`: the 6 `[ORIGINAL-FAILS]` tests fail | `atomicity-tests-vs-original-43ead8d.txt` |
| Mutations F1–F5 on the fix (lock removed, re-plan removed, reference check removed, single transaction removed, early deletion): all caught | `mutation-checks.txt` |
| Regression + full suite ×2: 256 passed | `regression.txt`, `pytest-full.txt` |

## Still open (not in scope)
The LOW/INFO items stay open:
- threshold/evaluation margin (R-30);
- what is sent to OpenRouter (R-31);
- manual ingestion (R-32);
- malformed provider-response hardening (R-34);
- VM runtime validation pending (R-33).
