"""RAG-01: referenced retrieval over the assessment knowledge base (no answer generation).

knowledge/*.md  ->  heading-aware chunks  ->  OpenRouter embeddings  ->  pgvector  ->  cosine search

Retrieval returns EVIDENCE (ranked chunks with stable references) or an explicit
"insufficient evidence" state. It never produces an answer. Retrieved text is data,
never instructions (REQ-RAG-05).
"""
import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import psycopg

EMBEDDING_DIMENSION = 1536            # verified live: openai/text-embedding-3-small via OpenRouter -> 1536
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MAX_CHUNK_CHARS = 1200
PROVIDER_TIMEOUT_SECONDS = 30
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


class RagError(RuntimeError):
    """Base class; `code` is a safe, stable identifier for API responses and logs."""
    code = "rag_error"


class ProviderError(RagError):
    code = "embedding_unavailable"


class IndexMismatchError(RagError):
    code = "index_model_mismatch"


class IndexEmptyError(RagError):
    code = "index_not_ready"


class CorpusError(RagError):
    code = "invalid_corpus"


# --- embedding providers ---------------------------------------------------------------------

class EmbeddingProvider(Protocol):
    model: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class OpenRouterEmbeddingProvider:
    """Production provider: POST {base_url}/embeddings. The API key is never logged or returned."""

    def __init__(self, api_key: str, model: str = DEFAULT_EMBEDDING_MODEL,
                 base_url: str = DEFAULT_OPENROUTER_BASE_URL, dimension: int = EMBEDDING_DIMENSION):
        self._api_key, self.model, self.base_url, self.dimension = api_key, model, base_url.rstrip("/"), dimension

    def __repr__(self):  # never expose the key
        return f"OpenRouterEmbeddingProvider(model={self.model!r})"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        req = urllib.request.Request(
            f"{self.base_url}/embeddings", method="POST",
            data=json.dumps({"model": self.model, "input": texts}).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=PROVIDER_TIMEOUT_SECONDS) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise ProviderError(f"embeddings HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise ProviderError(f"embeddings request failed: {type(e).__name__}") from None
        items = sorted(payload.get("data") or [], key=lambda d: d.get("index", 0))
        vectors = [d.get("embedding") for d in items]
        if len(vectors) != len(texts) or any(not isinstance(v, list) or len(v) != self.dimension for v in vectors):
            raise ProviderError("embeddings response has unexpected count or dimension")
        return vectors


def provider_from_settings(settings) -> EmbeddingProvider | None:
    """Real provider when configured; None means RAG is unavailable (503), never a silent fallback."""
    if not settings.openrouter_api_key:
        return None
    return OpenRouterEmbeddingProvider(settings.openrouter_api_key, settings.rag_embedding_model,
                                       settings.openrouter_base_url)


# --- corpus and deterministic chunking ---------------------------------------------------------

@dataclass(frozen=True)
class Chunk:
    chunk_key: str        # stable: "<source_id>#<section-slug>[-<n>]"
    ordinal: int
    section: str
    content: str          # text that is embedded and returned as evidence
    content_sha256: str


@dataclass(frozen=True)
class Document:
    source_id: str
    title: str
    reference: str        # human-readable file reference, e.g. "02_support_policy.md"
    path: str
    content_sha256: str
    chunks: tuple[Chunk, ...]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _slug(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:60] or "section"


def _split_long(body: str) -> list[str]:
    """Group paragraphs up to MAX_CHUNK_CHARS (no overlap: sections are short and self-contained)."""
    parts, current = [], ""
    for para in [p.strip() for p in body.split("\n\n") if p.strip()]:
        if current and len(current) + 2 + len(para) > MAX_CHUNK_CHARS:
            parts.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        parts.append(current)
    return parts


def parse_document(path: Path) -> Document:
    raw = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    meta_match = re.match(r"^---\n(.*?)\n---\n", raw, re.S)
    if not meta_match:
        raise CorpusError(f"{path.name}: missing metadata header")
    meta = dict(line.split(":", 1) for line in meta_match.group(1).splitlines() if ":" in line)
    meta = {k.strip(): v.strip() for k, v in meta.items()}
    for key in ("source_id", "title", "reference"):
        if not meta.get(key):
            raise CorpusError(f"{path.name}: metadata '{key}' missing")
    if not _SOURCE_ID.fullmatch(meta["source_id"]):
        raise CorpusError(f"{path.name}: invalid source_id")
    # RAG01-02: the citation filename must be the REAL file. Editable metadata may not redirect it.
    if meta["reference"] != path.name:
        raise CorpusError(f"{path.name}: metadata reference must equal the file name")
    body = raw[meta_match.end():]
    sections = re.split(r"^## +(.+)$", body, flags=re.M)  # [preamble, heading1, text1, heading2, text2, ...]
    chunks, ordinal, used = [], 0, set()
    for heading, text in zip(sections[1::2], sections[2::2]):
        heading, text = heading.strip(), text.strip()
        if not text:
            continue
        pieces = _split_long(text)
        for i, piece in enumerate(pieces, start=1):
            key = f"{meta['source_id']}#{_slug(heading)}" + (f"-{i}" if len(pieces) > 1 else "")
            if key in used:
                raise CorpusError(f"{path.name}: duplicate section heading '{heading}'")
            used.add(key)
            content = f"{meta['title']} — {heading}\n\n{piece}"
            chunks.append(Chunk(key, ordinal, heading, content, _sha(content)))
            ordinal += 1
    if not chunks:
        raise CorpusError(f"{path.name}: no '## ' sections")
    return Document(meta["source_id"], meta["title"], path.name, path.name, _sha(raw), tuple(chunks))


def load_corpus(directory: Path) -> list[Document]:
    docs = [parse_document(p) for p in sorted(Path(directory).glob("*.md"))]
    ids = [d.source_id for d in docs]
    if len(ids) != len(set(ids)):
        raise CorpusError("duplicate source_id in corpus")
    return docs


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


# --- ingestion (idempotent) ----------------------------------------------------------------------

@dataclass
class IngestReport:
    documents: int = 0
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted_documents: int = 0
    chunks: int = 0
    embedded: int = 0
    deleted_chunks: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


INGEST_LOCK_KEY = int.from_bytes(hashlib.sha256(b"nexo:rag_ingest:v1").digest()[:8], "big", signed=True)
INGEST_MAX_ATTEMPTS = 3


class _Replan(Exception):
    """Internal: a concurrent ingestion changed the index; roll back and plan again."""


def _current_index(conn: psycopg.Connection) -> tuple[dict, dict]:
    """(documents {source_id: (content_sha256, model)}, chunks {chunk_key: (content_sha256, model)})."""
    docs = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT source_id, content_sha256, embedding_model FROM knowledge_documents").fetchall()}
    chunks = {r[0]: (r[1], r[2]) for r in conn.execute(
        "SELECT chunk_key, content_sha256, embedding_model FROM knowledge_chunks").fetchall()}
    return docs, chunks


def _needs_embedding(chunk: Chunk, indexed_chunks: dict, model: str) -> bool:
    return indexed_chunks.get(chunk.chunk_key) != (chunk.content_sha256, model)


def ingest(conn: psycopg.Connection, provider: EmbeddingProvider, directory: Path) -> IngestReport:
    """Synchronize the index with the corpus ALL-OR-NOTHING (RAG01-01).

    1. Parse and validate every file; a corpus error aborts before the DB is touched.
    2. Plan against the current index and obtain EVERY required embedding first. No DB transaction is
       open during provider calls, and a provider failure changes nothing.
    3. ONE transaction: take the dedicated advisory lock (serializes concurrent ingestions; released at
       COMMIT/ROLLBACK), re-read the index under the lock, publish the complete corpus, verify it,
       COMMIT once. If a concurrent ingestion changed the index so an embedding is now missing,
       roll back and re-plan (bounded); never publish a partial or mixed corpus.
    """
    docs = load_corpus(directory)
    desired = {c.chunk_key: c for d in docs for c in d.chunks}
    fresh: dict[str, tuple[str, list[float]]] = {}  # chunk_key -> (content_sha256, vector) for provider.model
    for _attempt in range(INGEST_MAX_ATTEMPTS):
        _, indexed_chunks = _current_index(conn)
        for doc in docs:  # one provider call per document that needs embeddings; nothing is written yet
            missing = [c for c in doc.chunks if _needs_embedding(c, indexed_chunks, provider.model)
                       and fresh.get(c.chunk_key, ("",))[0] != c.content_sha256]
            if missing:
                vectors = provider.embed([c.content for c in missing])
                fresh.update({c.chunk_key: (c.content_sha256, v) for c, v in zip(missing, vectors)})
        try:
            return _publish(conn, provider.model, docs, desired, fresh)
        except _Replan:
            continue
    raise RagError("knowledge index kept changing during ingestion; retry")


def _publish(conn: psycopg.Connection, model: str, docs: list[Document], desired: dict, fresh: dict) -> IngestReport:
    """Publish the whole corpus in ONE transaction (raises _Replan, rolled back, if an embedding is missing)."""
    report = IngestReport(documents=len(docs), chunks=len(desired))
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (INGEST_LOCK_KEY,))
        indexed_docs, indexed_chunks = _current_index(conn)  # authoritative state under the lock
        writes_needed = {k for k, c in desired.items() if _needs_embedding(c, indexed_chunks, model)}
        if any(fresh.get(k, ("",))[0] != desired[k].content_sha256 for k in writes_needed):
            raise _Replan()
        for doc in docs:
            stale = {k for k in indexed_chunks if k.split("#", 1)[0] == doc.source_id} - {c.chunk_key for c in doc.chunks}
            writes = [c for c in doc.chunks if c.chunk_key in writes_needed]
            if indexed_docs.get(doc.source_id) == (doc.content_sha256, model) and not writes and not stale:
                report.unchanged += 1
                continue
            report.new += doc.source_id not in indexed_docs
            report.updated += doc.source_id in indexed_docs
            report.embedded += len(writes)
            report.deleted_chunks += len(stale)
            doc_id = conn.execute(
                "INSERT INTO knowledge_documents (source_id, title, reference, path, content_sha256, embedding_model)"
                " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (source_id) DO UPDATE SET title = EXCLUDED.title,"
                " reference = EXCLUDED.reference, path = EXCLUDED.path, content_sha256 = EXCLUDED.content_sha256,"
                " embedding_model = EXCLUDED.embedding_model RETURNING id",
                (doc.source_id, doc.title, doc.reference, doc.path, doc.content_sha256, model)).fetchone()[0]
            if stale:
                conn.execute("DELETE FROM knowledge_chunks WHERE chunk_key = ANY(%s)", (list(stale),))
            # Ordinals can shift when sections move: park them to avoid transient UNIQUE clashes.
            conn.execute("UPDATE knowledge_chunks SET ordinal = -1 - ordinal WHERE document_id = %s", (doc_id,))
            for c in doc.chunks:
                if c.chunk_key in writes_needed:
                    conn.execute(
                        "INSERT INTO knowledge_chunks (document_id, chunk_key, ordinal, section, content, content_sha256,"
                        " embedding_model, embedding) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)"
                        " ON CONFLICT (chunk_key) DO UPDATE SET document_id = EXCLUDED.document_id,"
                        " ordinal = EXCLUDED.ordinal, section = EXCLUDED.section, content = EXCLUDED.content,"
                        " content_sha256 = EXCLUDED.content_sha256, embedding_model = EXCLUDED.embedding_model,"
                        " embedding = EXCLUDED.embedding",
                        (doc_id, c.chunk_key, c.ordinal, c.section, c.content, c.content_sha256, model,
                         _vector_literal(fresh[c.chunk_key][1])))
                else:
                    conn.execute("UPDATE knowledge_chunks SET ordinal = %s, section = %s WHERE chunk_key = %s",
                                 (c.ordinal, c.section, c.chunk_key))
        present = [d.source_id for d in docs]
        report.deleted_chunks += conn.execute(
            "SELECT count(*) FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id"
            " WHERE NOT (d.source_id = ANY(%s))", (present,)).fetchone()[0]
        report.deleted_documents = conn.execute(
            "DELETE FROM knowledge_documents WHERE NOT (source_id = ANY(%s))", (present,)).rowcount
        # Final consistency check before the single COMMIT: exactly the desired corpus, one model, docs too.
        count, models, any_model = conn.execute(
            "SELECT count(*), count(DISTINCT embedding_model), min(embedding_model) FROM knowledge_chunks").fetchone()
        keys = {r[0] for r in conn.execute("SELECT chunk_key FROM knowledge_chunks").fetchall()}
        doc_models = {r[0] for r in conn.execute("SELECT DISTINCT embedding_model FROM knowledge_documents").fetchall()}
        if count != len(desired) or keys != set(desired) or models != 1 or any_model != model or doc_models != {model}:
            raise RagError("post-publication consistency check failed; corpus rolled back")
    return report


# --- retrieval ---------------------------------------------------------------------------------------

def index_model(conn: psycopg.Connection) -> str:
    models = [r[0] for r in conn.execute("SELECT DISTINCT embedding_model FROM knowledge_chunks").fetchall()]
    if not models:
        raise IndexEmptyError("knowledge index is empty; run the ingestion command")
    if len(models) > 1:
        raise IndexMismatchError("knowledge index mixes embedding models")
    return models[0]


def search_knowledge(conn: psycopg.Connection, provider: EmbeddingProvider, query: str, top_k: int,
                     min_score: float) -> dict:
    indexed = index_model(conn)
    if indexed != provider.model or provider.dimension != EMBEDDING_DIMENSION:
        raise IndexMismatchError("configured embedding model differs from the indexed model")
    [vector] = provider.embed([query])
    literal = _vector_literal(vector)
    rows = conn.execute(
        "SELECT d.source_id, d.title, d.reference, d.content_sha256, c.chunk_key, c.section, c.content,"
        " c.content_sha256, 1 - (c.embedding <=> %s::vector) AS score"
        " FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id"
        " ORDER BY c.embedding <=> %s::vector, c.chunk_key LIMIT %s",
        (literal, literal, top_k)).fetchall()
    candidates = [{
        "source_id": r[0], "title": r[1], "section": r[5], "chunk_id": r[4],
        "reference": f"{r[2]} § {r[5]}", "document_version": r[3][:12], "chunk_sha256": r[7][:12],
        "score": round(float(r[8]), 4), "text": r[6],
    } for r in rows]
    accepted = [c for c in candidates if c["score"] >= min_score]
    return {
        "evidence": "found" if accepted else "insufficient",
        "matches": accepted,
        "best_score": candidates[0]["score"] if candidates else None,
        "min_score": min_score,
        "model": indexed,
    }
