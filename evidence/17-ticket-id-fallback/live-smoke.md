# P0.3B — Unclear ticket-identifier fallback: discovery, RCA, fix and validation

Run locally on **2026-10-09**, before commit. Code under test: `src/backend/app/agent.py` (P0.3B working tree).

## Problem found during the P0.3 deployment
The first deployment of the guarded `general_chat` routing (`68e9717`) was technically correct (checkout, backend
rebuild, health/readiness and port exposure all PASS), but the read-only smoke was **8/9**:

| Case | Customer | Result |
|------|----------|--------|
| «¿Cómo está T-1001?» | A | `unsupported_or_unclear` → `clarification_needed` (expected `ticket_status` → `ticket_found`) |
| «¿Cómo está T-1001?» | B | `ticket_status` → `ticket_not_found` (correct) |

The deploy script's **automatic rollback PASSED**: the VM returned to `16c587f` and the backend was rebuilt healthy.
No business data was touched.

## Root cause (read-only RCA)
- **Pre-existing design gap:** a ticket identifier typed by the customer was honoured only when the classifier chose
  `ticket_status` (or, since P0.2, `general_chat`). The `unsupported_or_unclear` branch of `_route()` never looked at
  `_TICKET_REF` / `_UUID`, in `16c587f` as well.
- **Harness fragility:** the terse wording «¿Cómo está T-1001?» had never been validated live (the validated wording is
  «¿En qué estado está mi ticket T-1001?»). The model input was identical for both customers (the customer id is never
  sent to the model), so the different interpretation is model non-determinism, not customer-dependent behaviour.
- Not a code regression of `general_chat`: the affected branch is unchanged since `16c587f`.

## Fix (4 lines, `_route()`, `unsupported_or_unclear` branch only)
If the interpretation is `unsupported_or_unclear` and the message contains a `T-xxxx` reference or a UUID, the
backend uses the existing read-only `_ticket()` path (PostgreSQL, filtered by the authenticated customer). Without an
identifier the behaviour is unchanged (`clarification_needed`). No global pre-routing: explicit intents
(`request_human`, `create_ticket`, `create_lead`, collecting data) keep precedence. Several identifiers are delegated
to `_ticket()`, which answers `needs_ticket_id`.

Audit of the fallback: `interpreted_intent = unsupported_or_unclear`, `unclear_guard = ticket_identifier`,
`intent = ticket_status` (effective route), `result`, `ticket_lookup`; LLM stages `["intent"]` only; no message text.

## Scripted tests (test-only chat client, real PostgreSQL)
10 new tests in `tests/test_agent.py`, all PASS: unclear + «¿Cómo está T-1001?» → customer A `ticket_found`, customer B
`ticket_not_found`; unclear + owner's UUID → found, foreign UUID → not found (nothing leaked); two identifiers →
`needs_ticket_id`; no identifier → unchanged `clarification_needed`; `request_human` + T-1001 → handoff (not diverted);
`create_ticket` + T-1001 → `collecting_info` (not diverted); injection + foreign id → `ticket_not_found`, DB unchanged;
pending action + unclear + T-1001 → ticket read, `next_step` and full DB snapshot unchanged; audit facts without text.

- **Mutation check:** fallback disabled → 7 tests fail (including the customer-A case); the 4 non-diversion tests
  still pass, as intended; file restored byte-identical.
- Focused regression (`test_agent.py`, `test_chat_actions*.py`, `test_rag.py`): **209 passed**.
- Full suite: **441 passed, 8 skipped** (opt-in live and evidence-dump tests). No existing test was modified.

## Live smoke (`tests/test_agent_live.py`, opt-in `NEXO_LIVE_OPENROUTER=1`)
- **Chat model:** `x-ai/grok-4.7` (served model always `x-ai/grok-4.7`); **embeddings:** `openai/text-embedding-3-small`;
  fresh PostgreSQL 17 + pgvector database, synthetic customers A and B, synthetic messages only.
- **Result: 21/21 PASS**, `business_tables_unchanged: true`, 29 LLM calls, **≈ 0.107 USD** (0.107426).

| Case | Customer | Intent → status | Evidence |
|------|----------|-----------------|----------|
| «¿Cómo está T-1001?» | A | ticket_status → ticket_found | reference T-1001, source `business_api` |
| «¿Cómo está T-1001?» | B | ticket_status → ticket_not_found | no sources, no data of A |
| «¿En qué estado está mi ticket T-1001?» | A | ticket_status → ticket_found | reference T-1001 |
| «¿En qué estado está mi ticket T-1001?» | B | ticket_status → ticket_not_found | no sources, no data of A |

All other turns (knowledge, absent data, actions, injection, `general_chat`) passed as in
`evidence/16-general-chat/live-smoke.md`; this run the disguised company question was answered with a source
(`03_commercial_policy.md § Implantaciones de IA y descuentos`), a safe outcome.

The live JSON does not record `interpreted_intent`, so it does not show whether the classifier or the fallback produced
`ticket_status` in this run; the fallback itself is proven by the scripted tests and the mutation check.

No secrets, tokens, `.env` content or internal prompts are included in this evidence.
