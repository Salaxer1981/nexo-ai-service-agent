"""OpenRouter chat-completions client with structured (JSON-schema) output. Used only by the agent.

The model may only return JSON that matches a schema chosen by the backend; the backend validates it
again before using it. No fallback model: if the served model differs from the configured one, the call fails.
The API key is never logged or returned.
"""
import json
import math
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from app.config import DEFAULT_CHAT_MODEL

CHAT_TIMEOUT_SECONDS = 30


class LLMError(Exception):
    code = "llm_unavailable"


class LLMUnavailable(LLMError):
    code = "llm_unavailable"


class LLMInvalidOutput(LLMError):
    code = "llm_invalid_output"


class LLMModelMismatch(LLMError):
    code = "llm_model_mismatch"


@dataclass
class LLMResult:
    data: dict
    model: str
    usage: dict = field(default_factory=dict)  # prompt/completion/reasoning tokens, cost (USD), ms


class ChatClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict, max_tokens: int) -> LLMResult: ...


class OpenRouterChatClient:
    def __init__(self, api_key: str, model: str = DEFAULT_CHAT_MODEL, base_url: str = "https://openrouter.ai/api/v1",
                 timeout: float = CHAT_TIMEOUT_SECONDS):
        self._api_key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout

    def __repr__(self):  # never expose the key
        return f"OpenRouterChatClient(model={self.model!r})"

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict, max_tokens: int) -> LLMResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": schema_name, "strict": True, "schema": schema}},
            "temperature": 0,
            "max_tokens": max_tokens,
            # Grok 4.7 reasoning cannot be disabled (verified): keep it low and never return it.
            "reasoning": {"effort": "low", "exclude": True},
            # Only providers that honour structured output; never route to another model or provider silently.
            "provider": {"require_parameters": True, "allow_fallbacks": False},
            "usage": {"include": True},
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions", method="POST", data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"})
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise LLMUnavailable(f"chat HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:  # includes timeouts
            raise LLMUnavailable(f"chat request failed: {type(e).__name__}") from None
        return parse_completion(payload, self.model, round((time.perf_counter() - start) * 1000, 1))


def parse_completion(payload, expected_model: str, ms: float = 0.0) -> LLMResult:
    """Validate an OpenRouter chat-completions payload. Raises LLMError subclasses; never returns partial data."""
    if not isinstance(payload, dict) or payload.get("error"):
        raise LLMUnavailable("chat provider returned an error")
    served = payload.get("model")
    if served != expected_model:
        raise LLMModelMismatch("served model differs from the configured model")
    try:
        choice = payload["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMInvalidOutput("no message content") from None
    if choice.get("finish_reason") != "stop":
        raise LLMInvalidOutput(f"incomplete output (finish_reason={choice.get('finish_reason')})")
    if not isinstance(content, str) or len(content) > 20000:
        raise LLMInvalidOutput("content missing or too large")
    try:
        data = json.loads(content)
    except ValueError:
        raise LLMInvalidOutput("content is not JSON") from None
    if not isinstance(data, dict):
        raise LLMInvalidOutput("content is not a JSON object")
    return LLMResult(data=data, model=served, usage=_usage(payload.get("usage"), ms))


def _count(value, name: str):
    """Optional non-negative integer (bool is not a count)."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LLMInvalidOutput(f"usage.{name} is not a non-negative integer")
    return value


def _usage(u, ms: float) -> dict:
    """AGENT01A-01: optional usage metadata is validated too; malformed metadata is invalid output, never a 500."""
    if u is None:
        u = {}
    if not isinstance(u, dict):
        raise LLMInvalidOutput("usage is not an object")
    details = u.get("completion_tokens_details")
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise LLMInvalidOutput("usage.completion_tokens_details is not an object")
    cost = u.get("cost")
    if cost is not None and (isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0):
        raise LLMInvalidOutput("usage.cost is not a non-negative number")
    return {"prompt_tokens": _count(u.get("prompt_tokens"), "prompt_tokens"),
            "completion_tokens": _count(u.get("completion_tokens"), "completion_tokens"),
            "reasoning_tokens": _count(details.get("reasoning_tokens"), "reasoning_tokens"),
            "cost_usd": cost, "ms": ms}


def chat_client_from_settings(settings) -> ChatClient | None:
    if not settings.openrouter_api_key:
        return None
    return OpenRouterChatClient(settings.openrouter_api_key, settings.openrouter_chat_model, settings.openrouter_base_url)
