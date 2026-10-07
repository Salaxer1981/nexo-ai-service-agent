"""RAG-01F1 regressions (real PostgreSQL 17.11 + pgvector 0.8.7; TEST-ONLY providers).

RAG01-01: corpus synchronization is all-or-nothing and serialized.
RAG01-02: the citation filename is bound to the real source file.
Tests marked [ORIGINAL-FAILS] fail against the original RAG-01 implementation (43ead8d); the others
protect behaviour the fix must keep (re-plan path, normal references).
"""
import hashlib
import shutil
import threading
import time

import psycopg
import pytest

from app import rag
from conftest import ROOT
from rag_fakes import FlakyEmbeddingProvider, HashingEmbeddingProvider, HookedEmbeddingProvider

KNOWLEDGE = ROOT / "knowledge"
V1, V2 = "test-only/hashing-v1", "test-only/hashing-v2"


@pytest.fixture
def db(pg_server, fresh_db, tmp_path):
    from app.migrate import apply_migrations
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
    corpus = tmp_path / "knowledge"
    shutil.copytree(KNOWLEDGE, corpus)
    conns = []

    def connect():
        c = pg_server.connect(fresh_db)
        conns.append(c)
        return c
    yield connect, corpus
    for c in conns:
        c.close()


def snapshot(conn):
    """Everything that defines the published corpus, including the stored vectors and row ids."""
    docs = conn.execute("SELECT id, source_id, title, reference, path, content_sha256, embedding_model, updated_at"
                        " FROM knowledge_documents ORDER BY source_id").fetchall()
    chunks = conn.execute("SELECT id, document_id, chunk_key, ordinal, section, content, content_sha256, embedding_model,"
                          " embedding::text, updated_at FROM knowledge_chunks ORDER BY chunk_key").fetchall()
    return docs, chunks


def models(conn):
    return ({r[0] for r in conn.execute("SELECT DISTINCT embedding_model FROM knowledge_chunks")},
            {r[0] for r in conn.execute("SELECT DISTINCT embedding_model FROM knowledge_documents")})


# ===================================== RAG01-01: atomicity ================================

def test_failed_model_migration_preserves_previous_index(db):
    """[ORIGINAL-FAILS] Audit scenario: indexed with V1; switch to V2; first embedding call succeeds, a later one fails."""
    connect, corpus = db
    conn = connect()
    rag.ingest(conn, HashingEmbeddingProvider(model=V1), corpus)
    before = snapshot(conn)
    flaky = FlakyEmbeddingProvider(fail_on_call=2, model=V2)
    with pytest.raises(rag.ProviderError):
        rag.ingest(conn, flaky, corpus)
    assert flaky.calls == 2  # the first call DID succeed: the failure happened mid-corpus
    after = snapshot(conn)
    assert after == before  # every document, chunk, hash, vector, model value and timestamp unchanged
    assert models(conn) == ({V1}, {V1})
    assert len(after[0]) == 4 and len(after[1]) == 10
    result = rag.search_knowledge(conn, HashingEmbeddingProvider(model=V1), "horario de atención soporte", 3, 0.2)
    assert result["evidence"] == "found" and result["model"] == V1


def test_database_failure_during_publication_rolls_back_everything(db):
    """[ORIGINAL-FAILS] All embeddings succeed; a DB statement late in publication fails."""
    connect, corpus = db
    conn = connect()
    rag.ingest(conn, HashingEmbeddingProvider(model=V1), corpus)
    before = snapshot(conn)
    conn.execute("CREATE FUNCTION fail_last() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN"
                 " IF NEW.chunk_key = 'support-policy#limites-del-agente-y-escalado' THEN"
                 " RAISE EXCEPTION 'simulated failure late in publication'; END IF; RETURN NEW; END; $$")
    conn.execute("CREATE TRIGGER fail_last BEFORE INSERT OR UPDATE ON knowledge_chunks FOR EACH ROW EXECUTE FUNCTION fail_last()")
    try:
        with pytest.raises(psycopg.errors.RaiseException):
            rag.ingest(conn, HashingEmbeddingProvider(model=V2), corpus)  # all embeddings succeed; DB fails late
        assert snapshot(conn) == before and models(conn) == ({V1}, {V1})
    finally:
        conn.execute("DROP TRIGGER fail_last ON knowledge_chunks")
        conn.execute("DROP FUNCTION fail_last()")


def test_provider_failure_does_not_delete_stale_content(db):
    """[ORIGINAL-FAILS] Second required embedding fails: no update, stale deletion or doc deletion may happen."""
    connect, corpus = db
    conn = connect()
    rag.ingest(conn, HashingEmbeddingProvider(model=V1), corpus)
    before = snapshot(conn)
    (corpus / "01_services.md").unlink()                                   # would delete a document
    p = corpus / "04_security_policy.md"
    p.write_text(p.read_text(encoding="utf-8").split("## Acciones y borrados")[0], encoding="utf-8")  # stale chunk
    p = corpus / "02_support_policy.md"
    p.write_bytes(p.read_bytes().replace("09:00".encode(), "08:00".encode()))  # needs an embedding (call 1)
    p = corpus / "03_commercial_policy.md"
    p.write_bytes(p.read_bytes().replace("120 €".encode(), "150 €".encode()))  # needs an embedding (call 2: fails)
    with pytest.raises(rag.ProviderError):
        rag.ingest(conn, FlakyEmbeddingProvider(fail_on_call=2, model=V1), corpus)
    assert snapshot(conn) == before


# ===================================== RAG01-01: serialization ============================

def _waiting_on_ingest_lock(conn) -> bool:
    key = rag.INGEST_LOCK_KEY & 0xFFFFFFFFFFFFFFFF
    return conn.execute("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted"
                        " AND classid = %s::bigint::oid AND objid = %s::bigint::oid",
                        (key >> 32, key & 0xFFFFFFFF)).fetchone()[0] > 0


def test_concurrent_generations_never_mix(db):
    """[ORIGINAL-FAILS] A (V1) embeds doc 1, then pauses before doc 2 while B (V2) runs a complete ingestion.
    Original code: A had already committed doc 1 => B overwrites all => A writes docs 2-4 as V1 => MIXED."""
    connect, corpus = db
    conn_a, conn_b = connect(), connect()
    b_report = {}

    def run_b():  # executed INSIDE A's 2nd embedding call, i.e. between A's per-document steps
        b_report["r"] = rag.ingest(conn_b, HashingEmbeddingProvider(model=V2), corpus)
        assert models(conn_b) == ({V2}, {V2})  # B published a complete V2 generation

    a = HookedEmbeddingProvider(hook_on_call=2, hook=run_b, model=V1)
    report_a = rag.ingest(conn_a, a, corpus)
    assert b_report["r"].embedded == 10
    chunk_models, doc_models = models(conn_a)
    assert chunk_models == doc_models == {V1}  # one complete generation (A published last), never a mix
    assert conn_a.execute("SELECT count(*) FROM knowledge_chunks").fetchone()[0] == 10
    assert report_a.embedded == 10


def test_second_ingestion_waits_for_the_lock(db):
    """[ORIGINAL-FAILS] While another session holds the ingestion lock, ingestion waits and publishes nothing."""
    connect, corpus = db
    control, worker_conn = connect(), connect()
    rag.ingest(control, HashingEmbeddingProvider(model=V1), corpus)
    before = snapshot(control)
    control.execute("SELECT pg_advisory_lock(%s)", (rag.INGEST_LOCK_KEY,))  # hold the ingestion lock
    result = {}
    worker = threading.Thread(target=lambda: result.update(r=rag.ingest(worker_conn, HashingEmbeddingProvider(model=V2), corpus)))
    try:
        worker.start()
        deadline = time.monotonic() + 20
        while not _waiting_on_ingest_lock(control):
            assert time.monotonic() < deadline, "ingestion never waited on the lock"
            time.sleep(0.02)
        assert snapshot(control) == before  # while waiting: nothing published, nothing partial
    finally:
        control.execute("SELECT pg_advisory_unlock(%s)", (rag.INGEST_LOCK_KEY,))
    worker.join(30)
    assert not worker.is_alive() and result["r"].embedded == 10
    assert models(control) == ({V2}, {V2})


def test_concurrent_change_forces_replan_not_partial_publication(db, tmp_path):
    """Between A's planning and publication, B publishes different content with the SAME model.
    A no longer has the embedding it needs for that chunk: it must re-plan and publish its full corpus."""
    connect, corpus_a = db
    conn_a, conn_b = connect(), connect()
    rag.ingest(conn_a, HashingEmbeddingProvider(model=V1), corpus_a)
    corpus_b = tmp_path / "corpus_b"
    shutil.copytree(corpus_a, corpus_b)
    p = corpus_b / "03_commercial_policy.md"
    p.write_bytes(p.read_bytes().replace("120 €".encode(), "999 €".encode()))
    p = corpus_a / "02_support_policy.md"  # A's own change, so A has something to embed
    p.write_bytes(p.read_bytes().replace("09:00".encode(), "08:00".encode()))

    a = HookedEmbeddingProvider(hook_on_call=1, model=V1,
                                hook=lambda: rag.ingest(conn_b, HashingEmbeddingProvider(model=V1), corpus_b))
    rag.ingest(conn_a, a, corpus_a)
    assert a.calls == 2  # planned once, re-planned after B's publication, embedded the missing chunk
    tarifas = conn_a.execute("SELECT content FROM knowledge_chunks WHERE chunk_key = 'commercial-policy#tarifas'").fetchone()[0]
    horario = conn_a.execute("SELECT content FROM knowledge_chunks WHERE chunk_key = 'support-policy#horario-de-atencion'").fetchone()[0]
    assert "120 €" in tarifas and "999 €" not in tarifas and "08:00" in horario  # exactly A's corpus
    shas = dict(conn_a.execute("SELECT source_id, content_sha256 FROM knowledge_documents").fetchall())
    assert shas == {d.source_id: d.content_sha256 for d in rag.load_corpus(corpus_a)}


# ===================================== RAG01-02: source-bound references ==================

def test_reference_mismatch_fails_closed_before_any_mutation(db):
    """[ORIGINAL-FAILS] 01_services.md claiming reference 02_support_policy.md is refused before any provider/DB work."""
    connect, corpus = db
    conn = connect()
    rag.ingest(conn, HashingEmbeddingProvider(model=V1), corpus)
    before = snapshot(conn)
    p = corpus / "01_services.md"
    p.write_text(p.read_text(encoding="utf-8").replace("reference: 01_services.md", "reference: 02_support_policy.md"),
                 encoding="utf-8")
    provider = HashingEmbeddingProvider(model=V1)
    with pytest.raises(rag.CorpusError, match="reference must equal the file name"):
        rag.ingest(conn, provider, corpus)
    assert provider.calls == 0 and snapshot(conn) == before
    assert conn.execute("SELECT count(*) FROM knowledge_documents WHERE source_id = 'services'"
                        " AND reference <> '01_services.md'").fetchone()[0] == 0


def test_returned_references_are_the_real_files(db):
    connect, corpus = db
    conn = connect()
    rag.ingest(conn, HashingEmbeddingProvider(model=V1), corpus)
    result = rag.search_knowledge(conn, HashingEmbeddingProvider(model=V1), "soporte de sistemas y redes servicios", 5, 0.0)
    services = [m for m in result["matches"] if m["source_id"] == "services"]
    assert services and all(m["reference"].startswith("01_services.md § ") for m in services)
    for m in result["matches"]:
        filename, section = m["reference"].split(" § ", 1)
        real = corpus / filename
        assert real.exists() and section == m["section"]
        sha = hashlib.sha256(real.read_bytes().decode().replace("\r\n", "\n").encode()).hexdigest()
        assert sha[:12] == m["document_version"]
        assert m["chunk_id"] in {c.chunk_key for c in rag.parse_document(real).chunks}
