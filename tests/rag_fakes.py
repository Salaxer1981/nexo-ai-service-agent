"""TEST-ONLY embedding providers. NEVER used by application code (lives outside src/backend/app).

They make retrieval MECHANICS testable without paid calls: storage, ranking order, references,
updates, failures. They say nothing about the real model's semantic quality; that is measured by
evidence/10-rag/calibrate.py and the opt-in live smoke (tests/test_rag_live.py).
"""
import hashlib
import math
import re
import unicodedata

from app.rag import EMBEDDING_DIMENSION, ProviderError


def _tokens(text: str) -> list[str]:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z0-9]+", ascii_) if len(t) > 2]


class HashingEmbeddingProvider:
    """TEST-ONLY: deterministic bag-of-words hashing into 1536 dims, L2-normalised."""

    def __init__(self, model: str = "test-only/hashing-v1", dimension: int = EMBEDDING_DIMENSION):
        self.model, self.dimension, self.calls, self.texts_embedded = model, dimension, 0, 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.texts_embedded += len(texts)
        out = []
        for text in texts:
            v = [0.0] * self.dimension
            for tok in _tokens(text):
                v[int(hashlib.sha256(tok.encode()).hexdigest(), 16) % self.dimension] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm for x in v])
        return out


class FailingEmbeddingProvider(HashingEmbeddingProvider):
    """TEST-ONLY: simulates the embeddings API being down."""

    def embed(self, texts):
        raise ProviderError("simulated embeddings outage")


class FlakyEmbeddingProvider(HashingEmbeddingProvider):
    """TEST-ONLY: succeeds until call number `fail_on_call`, then raises (audit scenario RAG01-01)."""

    def __init__(self, fail_on_call: int, **kw):
        super().__init__(**kw)
        self.fail_on_call = fail_on_call

    def embed(self, texts):
        if self.calls + 1 >= self.fail_on_call:
            self.calls += 1
            raise ProviderError("simulated failure on a later embeddings call")
        return super().embed(texts)


class HookedEmbeddingProvider(HashingEmbeddingProvider):
    """TEST-ONLY: runs `hook()` right before answering call number `hook_on_call` (deterministic interleaving)."""

    def __init__(self, hook_on_call: int, hook, **kw):
        super().__init__(**kw)
        self.hook_on_call, self.hook = hook_on_call, hook

    def embed(self, texts):
        if self.calls + 1 == self.hook_on_call:
            self.hook()
        return super().embed(texts)
