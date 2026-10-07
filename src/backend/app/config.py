"""Application configuration, read exclusively from environment variables.

Secrets never have defaults and are never included in repr/str output.
"""
import os
from dataclasses import dataclass, field

REQUIRED_VARS = ("POSTGRES_HOST", "POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD")
DEFAULT_N8N_LEAD_WEBHOOK_URL = "http://n8n:5678/webhook/nexo-lead-create"
# RAG relevance threshold (cosine similarity). Calibrated with the REAL model (RAG-01,
# evidence/10-rag/calibration.json): midpoint between the highest non-supported score (unrelated or
# in-domain-absent, 0.369) and the lowest supported expected-chunk score (0.4195). Margin ~0.03: thin.
DEFAULT_RAG_MIN_SCORE = 0.39
# Chat model (AGENT-01A): verified in the OpenRouter catalogue and by a live structured-output probe.
DEFAULT_CHAT_MODEL = "x-ai/grok-4.7"


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid. Never contains values."""


@dataclass(frozen=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str = field(repr=False)
    # Private n8n webhook of the lead workflow (reachable only on the Docker `automation` network).
    n8n_lead_webhook_url: str = DEFAULT_N8N_LEAD_WEBHOOK_URL
    # RAG (embeddings only). The OpenRouter key is optional: without it RAG answers 503, nothing else breaks.
    openrouter_api_key: str | None = field(default=None, repr=False)
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    rag_embedding_model: str = "openai/text-embedding-3-small"
    rag_min_score: float = DEFAULT_RAG_MIN_SCORE
    rag_knowledge_dir: str = "/srv/knowledge"
    # Agent chat model (no fallback model: a different served model is an error).
    openrouter_chat_model: str = DEFAULT_CHAT_MODEL


def load_settings(environ=None) -> Settings:
    env = os.environ if environ is None else environ
    missing = [name for name in REQUIRED_VARS if not env.get(name)]
    if missing:
        raise ConfigError(f"Missing required environment variables: {', '.join(missing)}")

    raw_port = env.get("POSTGRES_PORT", "5432")
    try:
        port = int(raw_port)
    except ValueError:
        raise ConfigError("POSTGRES_PORT must be an integer") from None
    if not 1 <= port <= 65535:
        raise ConfigError("POSTGRES_PORT must be between 1 and 65535")

    return Settings(
        postgres_host=env["POSTGRES_HOST"],
        postgres_port=port,
        postgres_db=env["POSTGRES_DB"],
        postgres_user=env["POSTGRES_USER"],
        postgres_password=env["POSTGRES_PASSWORD"],
        n8n_lead_webhook_url=env.get("N8N_LEAD_WEBHOOK_URL") or DEFAULT_N8N_LEAD_WEBHOOK_URL,
        openrouter_api_key=(env.get("OPENROUTER_API_KEY") or "").strip() or None,
        openrouter_base_url=env.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1",
        rag_embedding_model=env.get("RAG_EMBEDDING_MODEL") or "openai/text-embedding-3-small",
        rag_min_score=_score(env.get("RAG_MIN_SCORE")),
        rag_knowledge_dir=env.get("RAG_KNOWLEDGE_DIR") or "/srv/knowledge",
        openrouter_chat_model=(env.get("OPENROUTER_CHAT_MODEL") or "").strip() or DEFAULT_CHAT_MODEL,
    )


def _score(raw: str | None) -> float:
    if not raw:
        return DEFAULT_RAG_MIN_SCORE
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError("RAG_MIN_SCORE must be a number between 0 and 1") from None
    if not 0.0 <= value <= 1.0:
        raise ConfigError("RAG_MIN_SCORE must be a number between 0 and 1")
    return value
