"""OPT-IN live smoke with the REAL OpenRouter embeddings provider (no chat/completions).

Runs only with NEXO_LIVE_OPENROUTER=1 and an OPENROUTER_API_KEY (env or git-ignored .env). Uses only the
synthetic assessment corpus. Never prints the key or embeddings. Writes sanitized facts to
$NEXO_EVIDENCE_DIR/live-embedding-smoke.json when that variable is set.
"""
import json
import math
import os
from pathlib import Path

import pytest

from app import rag
from app.config import DEFAULT_RAG_MIN_SCORE
from conftest import ROOT

ENABLED = os.environ.get("NEXO_LIVE_OPENROUTER") == "1"


def _key():
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"].strip()
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


@pytest.mark.skipif(not ENABLED, reason="live OpenRouter smoke is opt-in (NEXO_LIVE_OPENROUTER=1)")
def test_live_openrouter_embeddings_through_pgvector(pg_server, fresh_db):
    key = _key()
    assert key, "OPENROUTER_API_KEY not available"
    provider = rag.OpenRouterEmbeddingProvider(key)
    assert "sk-or" not in repr(provider)
    # Batch ordering: the provider must return vectors in input order.
    a, b = "Horario de atención del soporte", "Diagnóstico inicial: precio"
    ab, ba = provider.embed([a, b]), provider.embed([b, a])
    order_ok = _cos(ab[0], ba[1]) > 0.99 and _cos(ab[1], ba[0]) > 0.99 and _cos(ab[0], ab[1]) < 0.99
    assert order_ok and len(ab) == 2 and all(len(v) == 1536 for v in ab)

    from app.migrate import apply_migrations
    with pg_server.connect(fresh_db) as conn:
        apply_migrations(conn)
        report = rag.ingest(conn, provider, ROOT / "knowledge")
        dims = conn.execute("SELECT DISTINCT vector_dims(embedding) FROM knowledge_chunks").fetchall()
        known = rag.search_knowledge(conn, provider, "¿Cuál es el horario de atención del soporte?", 3, DEFAULT_RAG_MIN_SCORE)
        unrelated = rag.search_knowledge(conn, provider, "receta de paella valenciana", 3, DEFAULT_RAG_MIN_SCORE)
        rerun = rag.ingest(conn, provider, ROOT / "knowledge")
    assert dims == [(1536,)] and report.embedded == 10
    assert known["evidence"] == "found" and known["matches"][0]["chunk_id"] == "support-policy#horario-de-atencion"
    assert unrelated["evidence"] == "insufficient" and unrelated["matches"] == []
    assert rerun.embedded == 0 and rerun.unchanged == 4

    out = os.environ.get("NEXO_EVIDENCE_DIR")
    if out:
        facts = {
            "provider": "OpenRouter /api/v1/embeddings", "model": provider.model, "dimension": dims[0][0],
            "batch_order_preserved": order_ok, "first_ingest": report.as_dict(), "second_ingest": rerun.as_dict(),
            "known_query": {"query": "¿Cuál es el horario de atención del soporte?", "evidence": known["evidence"],
                            "top": [(m["chunk_id"], m["reference"], m["score"]) for m in known["matches"]]},
            "unrelated_query": {"query": "receta de paella valenciana", "evidence": unrelated["evidence"],
                                "best_score": unrelated["best_score"]},
            "min_score": DEFAULT_RAG_MIN_SCORE, "pgvector_type": "vector(1536)",
        }
        Path(out, "live-embedding-smoke.json").write_bytes((json.dumps(facts, ensure_ascii=False, indent=2) + "\n").encode())
