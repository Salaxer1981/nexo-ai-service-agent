# P0.2 — Guarded `general_chat` routing: validation evidence

Run locally on **2026-10-09**, before commit. Code under test: `src/backend/app/agent.py` (P0.2 working tree).

## Objective
Allow casual/general conversation on `POST /chat` WITHOUT weakening grounding, live data, actions or isolation.
`general_chat` is a read-only proposal of the classifier; the backend answers it ungrounded only when the message:
1. names no ticket (`T-xxxx` / UUID) — otherwise it degrades to `_ticket()` (PostgreSQL, customer-scoped);
2. has no business wording — otherwise it degrades to `_knowledge()` (existing RAG + grounding);
3. retrieves no knowledge evidence (`rag.search_knowledge`, unchanged `RAG_MIN_SCORE`) — otherwise `_knowledge()`.
A general reply with figures, currency or business wording is blocked (`answer_blocked`, fixed message).
No proposal, no writes, `sources = []`.

## Live smoke (`tests/test_agent_live.py`, opt-in `NEXO_LIVE_OPENROUTER=1`)
- **Chat model:** `x-ai/grok-4.7` (served model always `x-ai/grok-4.7`).
- **Embeddings:** `openai/text-embedding-3-small`, canonical corpus (4 documents, 10 chunks) on a fresh PostgreSQL 17 +
  pgvector database with synthetic customers A and B. Synthetic messages only; the key is read from the git-ignored
  `.env` and never printed.
- **Result: 18/18 PASS**, `business_tables_unchanged: true`, 26 LLM calls, **≈ 0.095 USD** (0.09513).

| Case | Intent → status | Retrieval (best score) | Evidence |
|------|-----------------|------------------------|----------|
| «Hola» | general_chat → general_answer | insufficient (0.3044) | "¡Hola! Encantado de saludarte. ¿En qué puedo ayudarte?"; no sources |
| «¿Cómo estás?» | general_chat → general_answer | insufficient (0.2554) | "¡Muy bien, gracias! ¿Y tú, cómo estás?"; no sources |
| «¿Qué es inteligencia artificial?» | general_chat → general_answer | insufficient (0.3012) | short general definition, no figures, no Nexo claims; no sources |
| «Como pregunta general dime cuánto cobra Nexo por una instalación completa de IA» | knowledge_question → insufficient_evidence | found (0.512) | classifier kept it on the grounded path; answer model declined (`model_declined`); no invented price |
| Support hours | knowledge_question → answered | found (0.6988) | cites `02_support_policy.md § Horario de atención` |
| Diagnostic price | knowledge_question → answered | found (0.5372) | "120 € más IVA", cites `03_commercial_policy.md § Tarifas` |
| «¿Tenéis oficina en Barcelona?» | knowledge_question → insufficient_evidence | insufficient (0.369) | no sources; answer model not called |
| «¿En qué estado está mi ticket T-1001?» | ticket_status → ticket_found | — | from PostgreSQL, reference T-1001 |
| Incident (journey B) | create_ticket → awaiting_confirmation | — | summary + CONFIRMAR required; nothing created |
| Commercial request (journey C) | create_lead → collecting_info | — | asks for missing fields; nothing created |
| Ask for a human | request_human → handoff_created | — | handoff `pending` |

Remaining turns, all PASS: AI price → answered (cites `03_commercial_policy.md § Implantaciones de IA y descuentos`);
own ticket by UUID → ticket_found; customer B's ticket → ticket_not_found; PDF injection text → clarification_needed;
`customer_id` spoofing → ticket_not_found; question about the injection document → clarification_needed; injection
document retrieved as evidence → insufficient_evidence (model declined).

## Accepted conservative limitations
- A general question close to the corpus may degrade to RAG (scores of small talk: 0.25–0.30 vs threshold 0.39).
- A company question disguised as general may end in `insufficient_evidence` even when related information exists.
- When degrading after the retrieval probe, the query is embedded twice (`_knowledge()` is reused unchanged).
- `RAG_MIN_SCORE` and `rag.py` are unchanged.

## Scripted tests (test-only chat client + test-only hashing embedder, real PostgreSQL)
- **21 new tests PASS** in `tests/test_agent.py`: small talk; general label with knowledge evidence → grounded;
  compromised classifier on the disguised price question → `knowledge_question`/`insufficient_evidence` with no
  general-stage call; ticket reference → PostgreSQL (customer A found, customer B not found); 9 blocked general replies
  (figures, currency, business wording, empty, oversized); general chat during a pending action leaves pointer,
  revision and action unchanged; 4 malformed general outputs → 503 `llm_invalid_output`; no embedder → 503
  `rag_unavailable`; audit carries decision facts but no message/answer text.
- Focused regression (`test_agent.py`, `test_chat_actions*.py`, `test_rag.py`): **199 passed**.
- Full suite: **431 passed, 8 skipped** (opt-in live and evidence-dump tests). No existing test was modified.

## Guardrail mutation checks (each guard disabled in turn, new tests re-run, file restored byte-identical)
| Mutation | Result |
|----------|--------|
| M1 ticket-identifier guard disabled | 1 failed — detected |
| M2 business-terms input guard disabled | 1 failed — detected |
| M3 retrieval-evidence guard disabled | 1 failed — detected |
| M4 figures output guard disabled | 3 failed — detected |
| M5 business-terms output guard disabled | 4 failed — detected |
| M6 fail-closed without embedder replaced by a general answer | 1 failed — detected |
