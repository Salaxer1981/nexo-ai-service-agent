"""RAG-01 threshold calibration with the REAL embedding model (openai/text-embedding-3-small via OpenRouter).

Embeds the real corpus chunks and an evaluation query set, computes cosine similarity (identical to
pgvector's `1 - (a <=> b)`), and derives a conservative threshold from the measured score gap.
Writes scores only: no embeddings, no API key. Usage (repo root):
    .venv/Scripts/python.exe evidence/10-rag/calibrate.py
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src" / "backend"))
from app import rag  # noqa: E402

EVAL = [  # (category, query, expected chunk_key or None)
    ("known", "¿Cuál es el horario de atención del soporte?", "support-policy#horario-de-atencion"),
    ("known", "¿Cuánto cuesta el diagnóstico inicial?", "commercial-policy#tarifas"),
    ("known", "¿Qué servicios ofrecéis?", "services#catalogo-de-servicios"),
    ("known", "¿Cuándo se considera crítica una incidencia?", "support-policy#clasificacion-de-incidencias"),
    ("known", "¿El agente puede reiniciar un servidor?", "support-policy#limites-del-agente-y-escalado"),
    ("known", "¿Puedo darle mi contraseña al agente?", "security-policy#datos-sensibles-y-privacidad"),
    ("known", "¿Cuánto cuesta una implantación de IA?", "commercial-policy#implantaciones-de-ia-y-descuentos"),
    ("known", "¿Cuándo estará lista una nueva implantación?", "services#nuevas-implantaciones-y-plazos"),
    ("paraphrase", "¿A qué hora puedo contactar con vosotros entre semana?", "support-policy#horario-de-atencion"),
    ("paraphrase", "precio mensual del soporte gestionado", "commercial-policy#tarifas"),
    ("paraphrase", "toda la oficina se ha quedado sin internet, ¿qué prioridad tiene?", "support-policy#clasificacion-de-incidencias"),
    ("paraphrase", "¿me podéis hacer un descuento?", "commercial-policy#implantaciones-de-ia-y-descuentos"),
    ("paraphrase", "¿cuánto tardáis en resolver una incidencia?", "support-policy#limites-del-agente-y-escalado"),
    ("paraphrase", "quiero que borréis mis datos", "security-policy#acciones-y-borrados"),
    ("paraphrase", "what are your support hours?", "support-policy#horario-de-atencion"),
    ("unrelated", "receta de paella valenciana", None),
    ("unrelated", "¿Quién ganó el mundial de fútbol de 2010?", None),
    ("unrelated", "¿Cuál es la capital de Australia?", None),
    ("unrelated", "cómo cambiar el aceite del coche", None),
    ("unrelated", "precio del bitcoin hoy", None),
    ("unrelated", "escríbeme un poema sobre el mar", None),
    ("absent_in_domain", "¿Tenéis oficina en Barcelona?", None),
    ("absent_in_domain", "¿Cuál es vuestro número de teléfono?", None),
    ("absent_in_domain", "¿Desarrolláis aplicaciones móviles?", None),
]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def main():
    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text(encoding="utf-8").splitlines() if "=" in l)
    provider = rag.OpenRouterEmbeddingProvider(env["OPENROUTER_API_KEY"].strip())
    chunks = [c for d in rag.load_corpus(ROOT / "knowledge") for c in d.chunks]
    chunk_vecs = provider.embed([c.content for c in chunks])
    query_vecs = provider.embed([q for _, q, _ in EVAL])
    rows = []
    for (category, query, expected), qv in zip(EVAL, query_vecs):
        ranked = sorted(((cosine(qv, cv), c.chunk_key) for c, cv in zip(chunks, chunk_vecs)), reverse=True)
        top_score, top_key = ranked[0]
        expected_score = next((s for s, k in ranked if k == expected), None)
        rows.append({"category": category, "query": query, "expected": expected, "top1": top_key,
                     "top1_score": round(top_score, 4), "top1_correct": (top_key == expected) if expected else None,
                     "expected_score": round(expected_score, 4) if expected_score is not None else None,
                     "second_score": round(ranked[1][0], 4), "_ranked": ranked[:3]})
    supported = [r["expected_score"] for r in rows if r["category"] in ("known", "paraphrase")]
    unrelated = [r["top1_score"] for r in rows if r["category"] == "unrelated"]
    absent = [r["top1_score"] for r in rows if r["category"] == "absent_in_domain"]
    # Policy: midpoint between the HIGHEST score of any non-supported query (unrelated OR absent-in-domain)
    # and the LOWEST expected-chunk score of any supported query. Unrelated-only midpoint shown for comparison.
    lo, hi = max(unrelated + absent), min(supported)
    threshold = round((lo + hi) / 2, 2) if hi > lo else None
    for r in rows:
        ranked = r.pop("_ranked")
        r["accepted_at_threshold"] = [k for s, k in ranked if threshold is not None and s >= threshold]
        r["expected_accepted"] = (r["expected"] in r["accepted_at_threshold"]) if r["expected"] else None
    summary = {"model": provider.model, "dimension": len(chunk_vecs[0]), "chunks": len(chunks), "queries": len(rows),
               "min_supported_expected_score": hi, "max_unrelated_top1_score": max(unrelated),
               "max_absent_in_domain_top1_score": max(absent), "max_non_supported_score": lo,
               "gap": round(hi - lo, 4),
               "unrelated_only_midpoint_for_comparison": round((max(unrelated) + hi) / 2, 2),
               "top1_correct": f"{sum(1 for r in rows if r['top1_correct'])}/{sum(1 for r in rows if r['expected'])}"}
    summary["threshold"] = threshold
    summary["supported_with_expected_chunk_accepted"] = f"{sum(1 for r in rows if r['expected_accepted'])}/{len(supported)}"
    summary["non_supported_with_any_accepted"] = f"{sum(1 for r in rows if not r['expected'] and r['accepted_at_threshold'])}/{len(unrelated) + len(absent)}"
    out = {"summary": summary, "rows": rows}
    (Path(__file__).parent / "calibration.json").write_bytes(
        (json.dumps(out, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print(json.dumps(summary, indent=2))
    for r in rows:
        print(f"{r['category']:16} top1={r['top1_score']:.4f} exp={r['expected_score']} ok={r['top1_correct']} accepted={r['accepted_at_threshold']}  {r['query']}")


if __name__ == "__main__":
    main()
