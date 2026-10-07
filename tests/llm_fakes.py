"""TEST-ONLY chat client. NEVER used by application code (lives outside src/backend/app).

It replays scripted structured outputs so the agent's ROUTING, VALIDATION and FAILURE handling can be tested
deterministically, including deliberately malicious ("compromised model") outputs. It says nothing about the
real model's language quality: that is covered by the opt-in live smoke (tests/test_agent_live.py).
"""
from app.llm import LLMResult


class ScriptedChatClient:
    def __init__(self, *script, model: str = "test-only/fake-chat"):
        self.model, self.script, self.calls = model, list(script), []

    def complete_json(self, system, user, schema_name, schema, max_tokens):
        self.calls.append({"system": system, "user": user, "schema_name": schema_name, "max_tokens": max_tokens})
        if not self.script:
            raise AssertionError(f"unexpected LLM call #{len(self.calls)} ({schema_name})")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
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
