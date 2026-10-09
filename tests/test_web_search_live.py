"""OPT-IN live smoke of web_search (P0.4) with the REAL OpenRouter chat model, the REAL Exa web plugin and REAL
embeddings. Runs only with NEXO_LIVE_OPENROUTER=1 AND NEXO_LIVE_WEB=1 (each run makes paid web searches).

Exactly two public, non-sensitive questions; fresh database (real PostgreSQL + pgvector), canonical corpus ingested
so the RAG guard runs for real. Each web source must come from a provider url_citation (captured in process) that
carries content. Writes sanitized evidence (no key, no content, no reasoning) when NEXO_EVIDENCE_DIR is set.
"""
import json
import logging
import os
import secrets
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import rag
from conftest import ROOT, bearer

LIVE = os.environ.get("NEXO_LIVE_OPENROUTER") == "1" and os.environ.get("NEXO_LIVE_WEB") == "1"
QUESTIONS = [
    ("local, current", "¿Hay algún evento público hoy en Fuengirola, Málaga?"),
    ("recent technology news", "¿Qué noticias recientes hay sobre nuevos chips de Nvidia?"),
]


def _snapshot(conn):
    tables = ["tickets", "leads", "handoffs", "pending_ticket_actions", "pending_lead_actions", "chat_conversations"]
    return {t: conn.execute(f"SELECT count(*), md5(coalesce(string_agg(x::text,'|' ORDER BY x::text),'')) FROM {t} x").fetchone()
            for t in tables}


def _reachable(url: str) -> int | None:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 (nexo-live-smoke)"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


@pytest.mark.skipif(not LIVE, reason="live web smoke only when NEXO_LIVE_OPENROUTER=1 and NEXO_LIVE_WEB=1")
def test_live_web_search_smoke(pg_server, fresh_db, monkeypatch, caplog):
    from app.config import load_settings
    from app.main import app
    from app.migrate import apply_migrations
    from app.provision_auth import provision
    key = next((l.split("=", 1)[1].strip() for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines()
                if l.startswith("OPENROUTER_API_KEY=")), "")
    assert key, "OPENROUTER_API_KEY missing in the git-ignored .env"
    tokens = {"CUSTOMER_A": secrets.token_urlsafe(32), "CUSTOMER_B": secrets.token_urlsafe(32)}
    with pg_server.connect(fresh_db) as conn:
        conn.autocommit = False
        apply_migrations(conn)
        provision(conn, tokens)
        conn.commit()
    for k, v in pg_server.env(fresh_db).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("OPENROUTER_API_KEY", key)
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")  # controlled test environment only
    for var in ("RAG_MIN_SCORE", "RAG_EMBEDDING_MODEL", "OPENROUTER_CHAT_MODEL", "OPENROUTER_BASE_URL", "WEB_SEARCH_ENGINE",
                "WEB_SEARCH_MAX_RESULTS", "WEB_SEARCH_TIMEOUT_SECONDS"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings()
    with pg_server.connect(fresh_db) as conn:
        rag.ingest(conn, rag.provider_from_settings(settings), ROOT / "knowledge")
    caplog.set_level(logging.INFO, logger="nexo.audit")
    results = []
    with TestClient(app) as client, pg_server.connect(fresh_db) as conn:
        chat_client = client.app.state.chat_client
        assert chat_client.model == "x-ai/grok-4.7" and chat_client.web_search is not None
        assert chat_client.web_search.engine == "exa" and chat_client.web_search.max_results == 3
        captured = []  # provider citations of each web call (in process only; never written with content)
        real = chat_client.complete_json

        def spy(*a, **kw):
            res = real(*a, **kw)
            if kw.get("web") is not None:
                captured.append(res.citations)
            return res
        chat_client.complete_json = spy
        before = _snapshot(conn)
        for i, (label, question) in enumerate(QUESTIONS):
            n = len(captured)
            t0 = time.perf_counter()
            r = client.post("/chat", json={"message": question},
                            headers={**bearer(tokens["CUSTOMER_A"]), "X-Conversation-ID": f"live-web-{i}"})
            seconds = round(time.perf_counter() - t0, 2)
            b = r.json()
            ev = [json.loads(x.getMessage()) for x in caplog.records if x.name == "nexo.audit"][-1]
            cites = captured[n] if len(captured) > n else []
            by_url = {c["url"]: c for c in cites}
            src = b.get("sources") or []
            from_annotations = bool(src) and all(s.get("kind") == "web" and s.get("url") in by_url for s in src)
            with_content = bool(src) and all(by_url[s["url"]]["content"] for s in src if s.get("url") in by_url)
            ok = (r.status_code == 200 and b.get("intent") == "web_search" and b.get("status") == "answered"
                  and 1 <= len(src) <= 3 and from_annotations and with_content and ev.get("web_result") == "ok")
            results.append({
                "label": label, "question": question, "http": r.status_code, "intent": b.get("intent"),
                "status": b.get("status"), "answer": b.get("answer"), "seconds": seconds,
                "sources": [{"title": s.get("title"), "domain": s.get("domain"), "url": s.get("url"),
                             "content_chars": len(by_url.get(s.get("url"), {}).get("content", "")),
                             "http_get": _reachable(s["url"]) if s.get("url") else None} for s in src],
                "citations_returned": len(cites), "sources_from_annotations": from_annotations, "content_present": with_content,
                "audit": {k: ev.get(k) for k in ("intent", "interpreted_intent", "web_guard", "retrieval", "best_score",
                                                 "web_search_used", "web_engine", "web_source_count", "web_source_domains",
                                                 "web_result", "result", "status")},
                "llm": ev.get("llm"), "pass": ok})
        after = _snapshot(conn)
    assert key not in json.dumps(results)
    cost = sum((c.get("cost_usd") or 0) for r in results for c in (r["llm"] or []))
    summary = {"chat_model": "x-ai/grok-4.7", "engine": "exa", "questions": len(results), "passed": sum(r["pass"] for r in results),
               "business_tables_unchanged": before == after, "total_cost_usd": round(cost, 6),
               "web_call_seconds": [next((c["ms"] / 1000 for c in r["llm"] or [] if c["stage"] == "web"), None) for r in results]}
    if os.environ.get("NEXO_EVIDENCE_DIR"):
        Path(os.environ["NEXO_EVIDENCE_DIR"], "live-web-smoke.json").write_bytes(
            json.dumps({"summary": summary, "turns": results}, ensure_ascii=False, indent=1).encode("utf-8"))
    assert before == after, "the web route mutated business data"
