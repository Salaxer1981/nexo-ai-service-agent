"""TEST-ONLY chat client. NEVER used by application code (lives outside src/backend/app).

It replays scripted structured outputs so the agent's ROUTING, VALIDATION and FAILURE handling can be tested
deterministically, including deliberately malicious ("compromised model") outputs. It says nothing about the
real model's language quality: that is covered by the opt-in live smoke (tests/test_agent_live.py).
"""
import json
from dataclasses import dataclass, field

from app.llm import LLMResult, parse_completion


@dataclass
class WebStep:
    """A scripted WEB completion: built into a provider payload and parsed by the REAL app.llm.parse_completion,
    so citation extraction/validation is exercised exactly as in production."""
    data: dict
    annotations: list = field(default_factory=list)
    served_model: str | None = None  # None => the configured model


class ScriptedChatClient:
    def __init__(self, *script, model: str = "test-only/fake-chat", web_search=None):
        self.model, self.script, self.calls, self.web_search = model, list(script), [], web_search

    def complete_json(self, system, user, schema_name, schema, max_tokens, *, web=None):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name, "max_tokens": max_tokens,
                           "web": web})
        if not self.script:
            raise AssertionError(f"unexpected LLM call #{len(self.calls)} ({schema_name})")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        if isinstance(step, WebStep):
            if web is None:
                raise AssertionError("a WebStep was scripted for a call without web=")
            payload = {"model": step.served_model or self.model,
                       "choices": [{"finish_reason": "stop", "message": {
                           "content": json.dumps(step.data), "annotations": step.annotations,
                           "reasoning_details": [{"type": "reasoning.text", "text": "TEST-ONLY hidden reasoning"}]}}],
                       "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.0}}
            return parse_completion(payload, self.model, 1.0, web=True)
        data = step(system, user) if callable(step) else step
        return LLMResult(data=data, model=self.model,
                         usage={"prompt_tokens": 10, "completion_tokens": 5, "reasoning_tokens": 0, "cost_usd": 0.0, "ms": 1.0})


TICKET_KEYS = ("contact_name", "subject", "description", "priority")
LEAD_KEYS = ("company_name", "contact_name", "contact_email", "need")


def intent(name: str, ticket: dict | None = None, lead: dict | None = None, reason: str | None = None) -> dict:
    """A well-formed interpretation (AGENT-01B schema): intent + candidate ticket/lead fields + handoff reason."""
    return {"intent": name, "ticket": {k: (ticket or {}).get(k) for k in TICKET_KEYS},
            "lead": {k: (lead or {}).get(k) for k in LEAD_KEYS}, "handoff_reason": reason}


def answer(text: str, *chunk_ids: str, answerable: bool = True) -> dict:
    return {"answerable": answerable, "answer": text, "used_chunk_ids": list(chunk_ids)}


def citation(url: str, title: str = "Fuente", content: str = "") -> dict:
    """One provider url_citation annotation (as OpenRouter returns them)."""
    return {"type": "url_citation", "url_citation": {"url": url, "title": title, "content": content,
                                                      "start_index": 0, "end_index": 10}}


def web_answer(text: str, *used_urls: str, annotations: list = (), answerable: bool = True, served_model=None) -> WebStep:
    return WebStep({"answerable": answerable, "answer": text, "used_source_urls": list(used_urls)}, list(annotations),
                   served_model)
