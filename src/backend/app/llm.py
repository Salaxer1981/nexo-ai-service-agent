"""OpenRouter chat-completions client with structured (JSON-schema) output. Used only by the agent.

The model may only return JSON that matches a schema chosen by the backend; the backend validates it
again before using it. No fallback model: if the served model differs from the configured one, the call fails.
The API key is never logged or returned.
"""
import http.client
import json
import math
import socket
import threading
import time
import urllib.error
import urllib.parse
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


class WebSearchUnavailable(LLMError):
    code = "web_search_unavailable"


@dataclass(frozen=True)
class WebSearchConfig:
    """OpenRouter web plugin settings (P0.4: Exa only, the engine whose citations carry verifiable content)."""
    engine: str = "exa"
    max_results: int = 3
    timeout: float = 45.0


@dataclass
class LLMResult:
    data: dict
    model: str
    usage: dict = field(default_factory=dict)  # prompt/completion/reasoning tokens, cost (USD), ms
    # Validated url_citation annotations of the provider response (never from the model's JSON). Web calls only.
    citations: list = field(default_factory=list)


class ChatClient(Protocol):
    model: str

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict, max_tokens: int, *,
                      web: WebSearchConfig | None = None) -> LLMResult: ...


class OpenRouterChatClient:
    def __init__(self, api_key: str, model: str = DEFAULT_CHAT_MODEL, base_url: str = "https://openrouter.ai/api/v1",
                 timeout: float = CHAT_TIMEOUT_SECONDS, web_search: WebSearchConfig | None = None):
        self._api_key, self.model, self.base_url, self.timeout = api_key, model, base_url.rstrip("/"), timeout
        self.web_search = web_search  # None => web search disabled (no external search is ever requested)

    def __repr__(self):  # never expose the key
        return f"OpenRouterChatClient(model={self.model!r})"

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict, max_tokens: int, *,
                      web: WebSearchConfig | None = None) -> LLMResult:
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
        if web is not None:  # P0.4: OpenRouter web plugin; calls without `web` send exactly the body above
            body["plugins"] = [{"id": "web", "engine": web.engine, "max_results": web.max_results}]
        data = json.dumps(body).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"}
        start = time.perf_counter()
        if web is not None:  # TOTAL deadline (urlopen's timeout is per socket operation; see _post_with_deadline)
            payload = _post_with_deadline(f"{self.base_url}/chat/completions", data, headers, web.timeout)
            return parse_completion(payload, self.model, round((time.perf_counter() - start) * 1000, 1), web=True)
        req = urllib.request.Request(f"{self.base_url}/chat/completions", method="POST", data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                payload = json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise LLMUnavailable(f"chat HTTP {e.code}") from None
        except (urllib.error.URLError, OSError, ValueError) as e:  # includes timeouts
            raise LLMUnavailable(f"chat request failed: {type(e).__name__}") from None
        return parse_completion(payload, self.model, round((time.perf_counter() - start) * 1000, 1))


MAX_WEB_RESPONSE_BYTES = 5 * 1024 * 1024


def _post_with_deadline(url: str, data: bytes, headers: dict, deadline: float):
    """POST and read the whole JSON response within `deadline` seconds IN TOTAL, or raise WebSearchUnavailable.

    urllib's timeout applies to each socket operation, so a server that keeps sending small pieces (keep-alive bytes)
    can stretch a request far past it (P0.4B live: 71.9 s against 45 s). Here a watchdog shuts the connected socket
    down when the deadline expires, which unblocks any read in progress; each socket operation is also capped at the
    deadline, and the body is read incrementally with the clock checked between reads. No retry; nothing partial is
    returned."""
    parts = urllib.parse.urlsplit(url)
    conn_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    end = time.monotonic() + deadline
    conn = conn_cls(parts.hostname, parts.port, timeout=deadline)
    expired, connected = threading.Event(), []

    def watchdog():
        expired.set()
        for sock in connected:  # the real socket (http.client may drop conn.sock while the body is still read)
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    timer = threading.Timer(deadline, watchdog)
    timer.daemon = True
    timer.start()

    def overdue() -> bool:
        return expired.is_set() or time.monotonic() >= end
    try:
        conn.connect()
        connected.append(conn.sock)
        if overdue():
            raise TimeoutError("web deadline exceeded")
        conn.request("POST", parts.path + (f"?{parts.query}" if parts.query else ""), body=data, headers=headers)
        resp = conn.getresponse()
        chunks, size = [], 0
        while not overdue():
            chunk = resp.read1(65536)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_WEB_RESPONSE_BYTES:
                raise ValueError("web response too large")
            chunks.append(chunk)
        if overdue():  # also covers a read cut short by the watchdog: a partial body is never parsed
            raise TimeoutError("web deadline exceeded")
        if not 200 <= resp.status < 300:  # includes 429: no automatic retry
            raise WebSearchUnavailable(f"chat HTTP {resp.status}")
        return json.loads(b"".join(chunks))
    except WebSearchUnavailable:
        raise
    except (OSError, ValueError, http.client.HTTPException) as e:  # includes timeouts and the watchdog shutdown
        raise WebSearchUnavailable(f"web request failed: {'deadline exceeded' if overdue() else type(e).__name__}") from None
    finally:
        timer.cancel()
        conn.close()


def parse_completion(payload, expected_model: str, ms: float = 0.0, web: bool = False) -> LLMResult:
    """Validate an OpenRouter chat-completions payload. Raises LLMError subclasses; never returns partial data.
    Only `content` (and, for web calls, url_citation annotations) is read: reasoning fields are never touched."""
    if not isinstance(payload, dict) or payload.get("error"):
        raise (WebSearchUnavailable if web else LLMUnavailable)("chat provider returned an error")
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
    citations = valid_citations(choice["message"].get("annotations")) if web else []
    return LLMResult(data=data, model=served, usage=_usage(payload.get("usage"), ms), citations=citations)


MAX_CITATIONS = 5
MAX_URL_CHARS = 2048
MAX_CITATION_CONTENT_CHARS = 20000


def valid_citations(annotations) -> list[dict]:
    """url_citation annotations reduced to url/title/content/start_index/end_index. Invalid entries are dropped,
    never repaired: http(s) only, a host, no embedded user/password, <= 2048 chars; deduplicated; at most 5."""
    out, seen = [], set()
    for a in annotations if isinstance(annotations, list) else []:
        if not isinstance(a, dict) or a.get("type") != "url_citation" or not isinstance(a.get("url_citation"), dict):
            continue
        c = a["url_citation"]
        url = c.get("url")
        if not isinstance(url, str) or not url or len(url) > MAX_URL_CHARS or url in seen or any(ch.isspace() for ch in url):
            continue
        try:
            parts = urllib.parse.urlsplit(url)
            host = parts.hostname
        except ValueError:
            continue
        if parts.scheme not in ("http", "https") or not host or parts.username is not None or parts.password is not None:
            continue
        title, content = c.get("title"), c.get("content")
        seen.add(url)
        out.append({"url": url, "domain": host.lower(),
                    "title": title.strip()[:300] if isinstance(title, str) else "",
                    "content": content[:MAX_CITATION_CONTENT_CHARS] if isinstance(content, str) else "",
                    "start_index": c.get("start_index") if isinstance(c.get("start_index"), int) else None,
                    "end_index": c.get("end_index") if isinstance(c.get("end_index"), int) else None})
        if len(out) == MAX_CITATIONS:
            break
    return out


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
    web = (WebSearchConfig(settings.web_search_engine, settings.web_search_max_results, settings.web_search_timeout_seconds)
           if settings.web_search_enabled else None)
    return OpenRouterChatClient(settings.openrouter_api_key, settings.openrouter_chat_model, settings.openrouter_base_url,
                                web_search=web)
