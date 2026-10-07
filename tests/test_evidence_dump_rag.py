"""Opt-in: pgvector/ingestion/reference evidence (set NEXO_EVIDENCE_DIR).

Embeddings here come from the TEST-ONLY HashingEmbeddingProvider: this documents MECHANICS (schema, pgvector
storage, idempotent ingestion, updates, deletions, reference resolution). Real-model facts live in
evidence/10-rag/live-embedding-smoke.json and calibration.json.
"""
import hashlib
import os
import shutil
from pathlib import Path

import pytest

from app import rag
from conftest import ROOT
from rag_fakes import HashingEmbeddingProvider

OUT = os.environ.get("NEXO_EVIDENCE_DIR")


@pytest.mark.skipif(not OUT, reason="evidence dump only when NEXO_EVIDENCE_DIR is set")
def test_dump_rag_db_evidence(pg_server, fresh_db, tmp_path):
    from app.migrate import apply_migrations
    corpus = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", corpus)
    provider = HashingEmbeddingProvider()
    lines = ["# RAG-01 database / pgvector / ingestion evidence: LOCAL real PostgreSQL 17.11 + pgvector 0.8.7",
             "# Embeddings: TEST-ONLY HashingEmbeddingProvider (mechanics only; real model: live-embedding-smoke.json).", ""]
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
        lines.append("pg_extension vector: " + str(conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]))
        lines.append("knowledge_chunks.embedding type: " + conn.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute WHERE attrelid='knowledge_chunks'::regclass"
            " AND attname='embedding'").fetchone()[0])
        lines += ["", "## Ingestion sequence (report = counts only, as printed by `python -m app.rag_ingest`)"]
        lines.append("1. first ingest:            " + str(rag.ingest(conn, provider, corpus).as_dict()))
        lines.append("2. re-ingest unchanged:     " + str(rag.ingest(conn, provider, corpus).as_dict()))
        ids_before = dict(conn.execute("SELECT chunk_key, id FROM knowledge_chunks").fetchall())
        p = corpus / "03_commercial_policy.md"
        p.write_bytes(p.read_bytes().replace("120 €".encode(), "150 €".encode()))
        lines.append("3. 120 € -> 150 € edited:   " + str(rag.ingest(conn, provider, corpus).as_dict()))
        tarifas = conn.execute("SELECT id, content, content_sha256 FROM knowledge_chunks WHERE chunk_key='commercial-policy#tarifas'").fetchone()
        lines.append(f"   commercial-policy#tarifas: same row id {tarifas[0] == ids_before['commercial-policy#tarifas']}, "
                     f"contains '150 €' {'150 €' in tarifas[1]}, contains '120 €' {'120 €' in tarifas[1]}, new sha {tarifas[2][:12]}")
        lines.append("   rows still containing '120 €': " + str(conn.execute(
            "SELECT count(*) FROM knowledge_chunks WHERE content LIKE '%120 €%'").fetchone()[0]))
        (corpus / "01_services.md").unlink()
        lines.append("4. 01_services.md deleted:  " + str(rag.ingest(conn, provider, corpus).as_dict()))
        shutil.copy(ROOT / "knowledge" / "01_services.md", corpus / "01_services.md")
        lines.append("5. 01_services.md restored: " + str(rag.ingest(conn, provider, corpus).as_dict()))
        lines += ["", "## Indexed rows (no vectors printed)", "chunk_key | ordinal | model | dims | document | doc sha256 (12) | chunk sha256 (12)"]
        for r in conn.execute("SELECT c.chunk_key, c.ordinal, c.embedding_model, vector_dims(c.embedding), d.reference,"
                              " left(d.content_sha256,12), left(c.content_sha256,12) FROM knowledge_chunks c"
                              " JOIN knowledge_documents d ON d.id=c.document_id ORDER BY d.source_id, c.ordinal"):
            lines.append(" | ".join(str(x) for x in r))
        lines += ["", "## Reference resolution for one search (query: 'precio diagnóstico inicial')"]
        res = rag.search_knowledge(conn, provider, "precio diagnóstico inicial", 3, 0.2)
        for m in res["matches"]:
            doc = conn.execute("SELECT reference, content_sha256 FROM knowledge_documents WHERE source_id=%s", (m["source_id"],)).fetchone()
            file_sha = hashlib.sha256((corpus / doc[0]).read_bytes().decode().replace("\r\n", "\n").encode()).hexdigest()
            lines.append(f"- {m['reference']} (chunk {m['chunk_id']}, score {m['score']}) -> file {doc[0]} "
                         f"sha {file_sha[:12]} == indexed {doc[1][:12]}: {file_sha == doc[1]}")
    Path(OUT, "db-ingestion-references-evidence.txt").write_bytes(("\n".join(lines) + "\n").encode("utf-8"))


@pytest.mark.skipif(not OUT, reason="evidence dump only when NEXO_EVIDENCE_DIR is set")
def test_dump_rag01f1_proofs(pg_server, fresh_db, tmp_path):
    """RAG-01F1 proofs (TEST-ONLY providers; real PostgreSQL 17.11 + pgvector 0.8.7)."""
    import threading
    from app.migrate import apply_migrations
    from rag_fakes import FlakyEmbeddingProvider, HookedEmbeddingProvider
    out = Path(OUT)
    corpus = tmp_path / "knowledge"
    shutil.copytree(ROOT / "knowledge", corpus)
    V1, V2, V3 = "test-only/hashing-v1", "test-only/hashing-v2", "test-only/hashing-v3"
    hdr = ["# RAG-01F1 {}: LOCAL real PostgreSQL 17.11 + pgvector 0.8.7; embeddings from TEST-ONLY providers", ""]

    def state(c):
        docs = c.execute("SELECT source_id, reference, left(content_sha256,12), embedding_model FROM knowledge_documents ORDER BY source_id").fetchall()
        chunks = c.execute("SELECT chunk_key, left(content_sha256,12), embedding_model, md5(embedding::text) FROM knowledge_chunks ORDER BY chunk_key").fetchall()
        return docs, chunks

    def table(docs, chunks):
        return ([f"  doc   {d[0]} | {d[1]} | sha {d[2]} | {d[3]}" for d in docs]
                + [f"  chunk {c[0]} | sha {c[1]} | {c[2]} | vector md5 {c[3][:12]}" for c in chunks])

    with pg_server.connect(fresh_db) as conn, pg_server.connect(fresh_db) as conn_b:
        apply_migrations(conn)
        # 1. failed model migration (audit scenario)
        rag.ingest(conn, HashingEmbeddingProvider(model=V1), corpus)
        before = state(conn)
        L = [hdr[0].format("failed model migration V1 -> V2"), hdr[1], "BEFORE (indexed with V1):"] + table(*before)
        flaky = FlakyEmbeddingProvider(fail_on_call=2, model=V2)
        try:
            rag.ingest(conn, flaky, corpus)
            L.append("UNEXPECTED: ingestion succeeded")
        except rag.ProviderError as exc:
            L += ["", f"ATTEMPT with V2: provider call 1 succeeded, call 2 failed -> {type(exc).__name__} (code {exc.code}); calls made: {flaky.calls}"]
        after = state(conn)
        L += ["", "AFTER:"] + table(*after) + ["",
              f"identical to BEFORE (docs, references, hashes, models, vector checksums): {after == before}",
              f"chunks with model V2: {sum(c[2] == V2 for c in after[1])}; documents with model V2: {sum(d[3] == V2 for d in after[0])}",
              f"search with V1 afterwards: {rag.search_knowledge(conn, HashingEmbeddingProvider(model=V1), 'horario de atención', 1, 0.2)['evidence']}"]
        (out / "failed-model-migration-proof.txt").write_bytes(("\n".join(L) + "\n").encode())

        # 2. concurrent ingestion: B (V2) runs completely inside A's (V1) 2nd embedding call
        L = [hdr[0].format("concurrent ingestion"), hdr[1],
             "Index currently V1. Scenario: A (model V3) starts; during A's 2nd provider call, B (model V2) runs a COMPLETE ingestion on another",
             "connection. With the original per-document commits, A had already committed document 1 => mixed index.", ""]
        seen = {}

        def run_b():
            seen["b"] = rag.ingest(conn_b, HashingEmbeddingProvider(model=V2), corpus).as_dict()
            seen["after_b"] = sorted({r[0] for r in conn_b.execute("SELECT DISTINCT embedding_model FROM knowledge_chunks")})
        ra = rag.ingest(conn, HookedEmbeddingProvider(hook_on_call=2, hook=run_b, model=V3), corpus).as_dict()
        final = state(conn)
        L += [f"B report: {seen['b']}", f"models in index right after B committed: {seen['after_b']}",
              f"A report: {ra}", "", "FINAL:"] + table(*final) + ["",
              f"distinct chunk models: {sorted({c[2] for c in final[1]})}; distinct document models: {sorted({d[3] for d in final[0]})}",
              f"chunks: {len(final[1])} (desired 10) -> one complete generation, no mix: {len({c[2] for c in final[1]} | {d[3] for d in final[0]}) == 1}", ""]
        # lock wait: hold the ingestion lock in another session, observe the waiter, release
        conn_b.execute("SELECT pg_advisory_lock(%s)", (rag.INGEST_LOCK_KEY,))
        res = {}
        with pg_server.connect(fresh_db) as conn_w:
            w = threading.Thread(target=lambda: res.update(r=rag.ingest(conn_w, HashingEmbeddingProvider(model=V2), corpus).as_dict()))
            w.start()
            key = rag.INGEST_LOCK_KEY & 0xFFFFFFFFFFFFFFFF
            import time
            deadline = time.monotonic() + 20
            while not conn.execute("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted AND classid=%s::bigint::oid"
                                   " AND objid=%s::bigint::oid", (key >> 32, key & 0xFFFFFFFF)).fetchone()[0]:
                assert time.monotonic() < deadline
                time.sleep(0.02)
            waiting_state_unchanged = state(conn) == final
            conn_b.execute("SELECT pg_advisory_unlock(%s)", (rag.INGEST_LOCK_KEY,))
            w.join(30)
        L += ["Serialization: another session holds the ingestion advisory lock; a V2 ingestion is started.",
              "  observed in pg_locks: ingestion WAITING on the advisory lock (not granted)",
              f"  index unchanged while it waited: {waiting_state_unchanged}",
              f"  after release it published: {res['r']}; models now {sorted({c[2] for c in state(conn)[1]})}"]
        (out / "concurrent-ingestion-proof.txt").write_bytes(("\n".join(L) + "\n").encode())

        # 3. reference mismatch
        before = state(conn)
        p = corpus / "01_services.md"
        good = p.read_bytes()
        p.write_bytes(good.replace(b"reference: 01_services.md", b"reference: 02_support_policy.md"))
        prov = HashingEmbeddingProvider(model=V2)
        L = [hdr[0].format("reference binding"), hdr[1], "File 01_services.md with front matter `reference: 02_support_policy.md`:"]
        try:
            rag.ingest(conn, prov, corpus)
            L.append("UNEXPECTED: accepted")
        except rag.CorpusError as exc:
            L.append(f"  ingestion refused: CorpusError({exc}) ; provider calls: {prov.calls} ; index unchanged: {state(conn) == before}")
        p.write_bytes(good)
        L += ["", "Normal corpus: every returned reference resolves to the real file:"]
        res = rag.search_knowledge(conn, HashingEmbeddingProvider(model=V2), "servicios soporte sistemas redes", 5, 0.0)
        for m in res["matches"]:
            fname = m["reference"].split(" § ")[0]
            sha = hashlib.sha256((corpus / fname).read_bytes().decode().replace("\r\n", "\n").encode()).hexdigest()
            L.append(f"  {m['reference']} | chunk {m['chunk_id']} | version {m['document_version']} == sha256({fname})[:12] {sha[:12]}: "
                     f"{sha[:12] == m['document_version']}")
        (out / "reference-mismatch-proof.txt").write_bytes(("\n".join(L) + "\n").encode())
