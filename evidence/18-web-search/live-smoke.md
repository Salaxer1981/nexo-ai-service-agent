# P0.4 — Grounded web search (OpenRouter web plugin, Exa): design, probe, implementation and validation

Runs on **2026-10-09**, local workstation, before commit. **Web search is in the code but OFF by default
(`WEB_SEARCH_ENABLED=false`) and NOT active in production** (see Limitations).

## Objective
Answer public, current questions from outside Nexo (events, news, today's opening of a public place) without letting
`general_chat` invent them and without sending Nexo questions to the internet. Principle: *the search engine provides
evidence; the backend decides which evidence is valid; the LLM only synthesizes the answer.*

## Architecture
- New intent `web_search` (read-only: no proposal, no writes, no actions). The classifier's label is only a proposal.
- `_web_guarded()` order: typed ticket id → `_ticket()` (PostgreSQL, customer-scoped); Nexo business wording →
  `_knowledge()`; RAG probe finds evidence → `_knowledge()`; web disabled → `insufficient_web_evidence` with **no
  external call**; only then `_web()`.
- `_web()`: one call with the OpenRouter **web plugin** (`engine: exa`, `max_results: 3`), the same strict JSON schema,
  `require_parameters: true`, `allow_fallbacks: false` and exact-model check. Only the question is sent (no customer id,
  no conversation context).
- Evidence = the provider's `url_citation` annotations, validated in `app.llm` (http/https, host, no user/password,
  <= 2048 chars, deduplicated, max 5). Sources returned to the client are built from them (`kind, title, domain, url`);
  page content is never returned.
- Deterministic web grounding: cited URLs must be a subset of the annotation URLs; no URL in the answer text; no
  statement about Nexo, tickets/incidents or actions; every figure/date must appear in the content of a cited result.
  Otherwise `answer_blocked` or `insufficient_web_evidence` with fixed, honest messages.
- Failures: transport/429/provider error/deadline → 503 `web_search_unavailable` (no retry); malformed output →
  `llm_invalid_output`; other model → `llm_model_mismatch`.
- Audit: intent, interpreted intent, guard, `web_search_used`, `web_engine`, source count and **domains only**,
  per-stage `ms` and `cost_usd`, result. Never URLs/query strings, page content, question, answer or reasoning.
- Frontend: web sources shown as plain text «Web · domain» (never links); technical details «Web · title — domain».

## Engine decision — probe P0.4A (2 calls, same model, prompt and schema)
| | native (xAI) | **exa** |
|---|---|---|
| Model / JSON schema / finish | `x-ai/grok-4.7` / PASS / stop | `x-ai/grok-4.7` / PASS / stop |
| url_citations | 30 (ignored `max_results: 3`) | 3 |
| `content` in citations | **none** | **all 3** (602–1174 chars) |
| Prompt tokens / cost / latency | 26 055 / 0.0716 USD / 17.1 s | 2 282 / 0.0119 USD / 5.2 s |

Exa is the only engine whose citations carry verifiable content, so it is the only one allowed (`WEB_SEARCH_ENGINE`
accepts `exa` only). `usage.server_tool_use` is `null` with the plugin, so the number of searches is not recorded.

## Implementation (P0.4B) and the deadline defect (P0.4C)
- P0.4B live (2 questions): Fuengirola → `insufficient_web_evidence` (model declined; safe), Nvidia news → answered
  with 2 grounded sources; but the web call took **71.9 s against a 45 s timeout**.
- Root cause: `urllib`'s timeout applies to each socket operation, so a server that keeps sending bytes resets it.
- Fix (web calls only): `http.client` with a watchdog that shuts the connected socket down at the deadline, every
  operation capped at the deadline, incremental reads with the clock checked between reads, and any body that completes
  after the deadline discarded (also when the cut looks like a normal EOF, as on Linux). Calls without `web` keep the
  previous `urlopen` path unchanged.
- Deterministic deadline tests (local stubs, 1 s deadline): silent server, keep-alive trickle (the live case), body
  completed only after the deadline (with/without Content-Length), Linux EOF semantics, normal calls unaffected, and
  end-to-end `/chat` → 503 `web_search_unavailable` with nothing partial and exactly one web call.

## Scripted validation
- `tests/test_web_search.py`: **74 passed** — routing (web vs general vs RAG vs ticket vs actions), Nexo/ticket
  questions disguised as web search, grounding (invented/non-subset URLs, figures and dates not in content, URL in
  answer, Nexo/action claims, no annotations, invalid and duplicate URLs), prompt injection and credentials inside page
  content treated as data, pending action intact, failures, HTTP layer payloads, configuration, deadline, and a full
  battery with web disabled (0 web requests).
- Mutation checks: **15/15 detected** (12 guard mutations + 3 deadline mutations); files restored byte-identical.
- Full suite: **515 passed, 9 skipped** (opt-in live and evidence-dump tests). Frontend: **18 passed**, eslint and
  `tsc --noEmit` clean.

## Live validation
- **General battery (`tests/test_agent_live.py`) with the new intent: 21/21 PASS**, `business_tables_unchanged: true`,
  0.125 USD. No turn was routed to `web_search`; «¿Qué es inteligencia artificial?» stays `general_chat → general_answer`.
- **Final web transport check (P0.4D), one question** «¿Qué noticias recientes hay sobre nuevos chips de Nvidia?»:

| Check | Result |
|---|---|
| HTTP / route | 200 / `web_search → answered` |
| Model / finish / JSON | `x-ai/grok-4.7` exact / stop / strict schema valid |
| TLS | TLSv1.3 to `openrouter.ai`, `CERT_REQUIRED`, hostname checked, certificate validated |
| Web stage / whole turn | **18.3 s** (< 45 s deadline) / 24.0 s |
| Annotations | 3 real `url_citation`, all with content (global.techradar.com, tecnologia-informatica.com, www.infobae.com) |
| Cited sources | 2 (tecnologia-informatica.com, www.infobae.com), both HTTP 200 |
| `used_source_urls` ⊂ annotations / grounding | PASS / PASS |
| `business_tables_unchanged` | true |
| Cost | **0.0198 USD** |

## Limitations
- **`WEB_SEARCH_ENABLED=false` by default, and production does not enable it**: `compose.yaml` does not pass
  `WEB_SEARCH_*` to the backend container yet; that change is a separate, explicitly approved phase.
- With web disabled, a message the classifier labels `web_search` answers `insufficient_web_evidence`.
- The Nexo business-term guard is deliberately broad: third-party «horario», «precio» or «servicio» questions use RAG.
- A «today» question depends on the page content stating the date; otherwise the answer is declined or blocked.
- The question leaves for the search provider (Exa through OpenRouter); messages with ticket ids or Nexo wording never do.

No API key, Authorization header, reasoning, page content, `.env`, tokens or full payloads are included.
