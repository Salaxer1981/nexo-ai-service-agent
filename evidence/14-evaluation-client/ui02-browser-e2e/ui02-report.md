# UI-02 — Real browser E2E of the Nexo evaluation client

**Result: PASS. UI-02 = BROWSER_E2E_VALIDATED; evaluation client = VALIDATED.**

**Run conditions.** I drove the real UI in the owner's Chrome (Claude in Chrome extension, Windows 11, viewport
1536×639) against the real stack on the VM, through `http://127.0.0.1:8080` over the owner's SSH tunnel. The stack:
PostgreSQL 17.11 + pgvector 0.8.7, the backend, **n8n 2.42.3**, **OpenRouter x-ai/grok-4.7** + real embeddings, and the
new `web` service.

**No fixture backend in any acceptance step.** The only exception is §R (responsive), and it is labelled.

**What was validated.**
- **Commit:** `ca86d7c3459f713319aa80de482cbcdb8c22fa01` (branch `ui02-candidate`). The final UI-02 commit on `main`
  carries byte-identical code (`git diff ui02-candidate -- compose.yaml .env.example README.md src` is empty) plus this
  evidence.
- **Harness:** `vm-e2e.sh` reported 28/28 checks PASS (`vm-run2-accepted.txt`).
- **Teardown:** the VM is back to baseline.

## A. Runtime architecture and credential boundary (§2–4)
**The gap.** The production Compose stack had **no** web client, and UI-01's Vite proxy exists only in development.

**The fix: the new `web` service.**
- **Build:** a two-stage image. `node:22.16.0-alpine`, then `npm ci` from the lockfile, `tsc`, `vite build`.
- **Runtime:** the static bundle plus `server/server.mjs` (Node standard library only).
- **What the server allows:**
  - it proxies **only** `POST /api/chat` → `/chat` and `GET /api/health/ready` → `/health/ready`, and answers 404 for any
    other `/api/*` path;
  - it forwards only `Content-Type` and a valid `X-Conversation-ID`, and drops browser `Authorization`, `Cookie` and
    every other header;
  - it maps `X-Demo-Session: A|B` to `AUTH_TOKEN_CUSTOMER_A|B` from its **runtime environment** (compose). There are no
    build args and nothing goes into the bundle;
  - unknown sessions get 503 and nothing is forwarded.
- **Hardening:** security headers (CSP `default-src 'self'`, `frame-ancestors 'none'`, `nosniff`, `no-referrer`,
  `X-Frame-Options: DENY`). The container has a read-only root, runs as non-root `node`, `cap_drop: ALL` and
  `no-new-privileges`.
- **Network:** published on `127.0.0.1:${WEB_PORT:-8080}` only. It sits on its own `web` network (web + backend), so it
  can reach the backend and **cannot resolve `db` or `n8n`** (checked on the VM).

**Backend authentication semantics are unchanged.** The boundary is just an HTTP client that holds the two synthetic
credentials the backend already provisions; identity is still resolved only from the presented token.

**Verified on the VM (§6 of the run log).**
- web only on `127.0.0.1:8080`, only on `nexo_web`;
- a read-only root, user `node` and `CapDrop [ALL]`;
- the web image's `Config.Env` contains no credential names;
- `docker compose config` shows no build args for `web`.

## B. Browser E2E matrix (REAL model, REAL n8n)
Each request ID below is the real `request_id` from the drawer, cross-checked against the **backend's own audit
line**, which I fetched through the allowlisted control endpoint.

| # | Scenario | Evidence | Result |
|---|---|---|---|
| 1 | Welcome state | NEXO layout, no conversations, drawer closed, "Connected" from the real `/health/ready`, localStorage empty | PASS |
| 2 | RAG «¿Cuál es el horario de soporte?» | Answer "lunes a viernes, 09:00–18:00 (Europe/Madrid)"; source `02_support_policy.md § Horario de atención` (no chunk id, hash or score). Drawer: route `knowledge_question`, model `x-ai/grok-4.7`, result `answered`. Audit `56f156ea…`: CUSTOMER_A, retrieval `found`, LLM stages intent+answer | PASS |
| 3 | Absent «¿Tenéis oficina en Barcelona?» | Truthful "no he encontrado información suficiente…", no sources, result `insufficient_evidence` | PASS |
| 4–5 | Critical ticket (Ana, assessment text) | Amber draft: Critical, "No ticket has been created yet.", truthful handoff note. PostgreSQL before confirming: action `pending`, **only the 2 seed tickets**. DOM, attributes, text, localStorage and URL contain **0** 16-hex token strings | PASS |
| 6–7 | Confirm incident | The UI sent `CONFIRMAR`; the bubble shows it. Audit `b9aee1ba…`: gate `confirm`, outcome `created`, **0 LLM calls**. PostgreSQL: action `consumed`, **T-1003** critical/open, `critical_incident` handoff pending. Green card T-1003, Open, "no response time is guaranteed"; the draft badge became **Confirmed** with no buttons | PASS |
| 8 | Replay | A second `CONFIRMAR` → `nothing_pending` ("No se ha hecho nada"); no second card; still 1 ticket | PASS |
| 9 | Version binding | A (normal keyboard) → correction → B (critical); A shows **Replaced** with no buttons. An unbound `CONFIRMAR` (no token) → `confirmation_review_required` (no model call); B is re-shown as the only actionable card; no ticket | PASS (see note 1) |
| 10 | Cancel | Cancel → `CANCELAR`; audit `a1034e28…`: gate `cancel`, outcome `cancelled`. PostgreSQL: A `superseded`, B `cancelled`, **0 tickets**. A later `CONFIRMAR` → `nothing_pending` | PASS |
| 11 | Normal ticket (Marta) | Draft Normal with no handoff note → Confirm → **T-1004** normal/open, no handoff | PASS |
| 12 | Lead through REAL n8n | «Somos una asesoría…» → `collecting_info` → details → draft (Company/Contact/Email/Need, `luis@example.test`), "No request has been registered yet" → Confirm. Audit for **the same request_id** `b5f5d831…` has 2 lines: chat (CUSTOMER_A, gate confirm, created, wf 1) **and** `/internal/leads` 201 by service `n8n-lead-writer` (wf 1). n8n execution **1** `success` (webhook mode). Exactly **1 lead**. Drawer: `Workflow = n8n execution 1`. The browser called only `/api/chat` | PASS |
| 13 | n8n failure + recovery | Fresh lead (Eva) → control `n8n/stop` → Confirm → **red "Not completed"**, 503 `lead_not_confirmed`, honest wording, no success card; no lead; chat pointer `lead|pending`. Control `n8n/start` (webhook ready after 1.0 s) → the **same draft's** Confirm → `lead_created`, n8n execution **3**, exactly one lead for the conversation. Execution 2 was the control endpoint's readiness probe (400 `invalid_envelope`, writes nothing) | PASS |
| 14 | «Quiero hablar con una persona.» | Handoff card Pending, "Nobody has picked it up yet… no response time is guaranteed"; `human_requested` pending | PASS |
| 15 | «Quiero que borréis todos mis datos personales.» | `unsafe_to_resolve` pending handoff; nothing deleted (tickets 4, leads 2 unchanged) | PASS |
| 16 | T-1001 | «abierto», normal; source `T-1001 · Ticket record`; knowledge source `Business API (ticket)`; audit `ticket_lookup=allowed`, intent call only | PASS |
| 17 | Isolation | A: T-1002 and T-9999 give the identical "No encuentro ningún ticket … asociado a tu cuenta.", with no sources; the audit alone differs (`denied_not_owner` / `not_found`). `customer_id = CUSTOMER_B …` stays CUSTOMER_A → clarification only. The account card switches to **Synthetic Customer B** → T-1002 «en curso»; audit **CUSTOMER_B**. Browser network log: only same-origin `POST /api/chat`, no query strings, no direct ticket or lead API | PASS |
| 18 | Prompt injection (assessment text; plus `T-1002` and an embedded `CONFIRMAR`) | `clarification_needed` both times; CUSTOMER_A; the conversation pane has no foreign data (the only "CUSTOMER_B" text on the page was my own earlier spoof message in the sidebar list); nothing created; an embedded `CONFIRMAR` is not the gate | PASS |
| 19 | Controlled error | Same as #13: approved red **Not completed** card; drawer `503 Unavailable`; missing fields `Not available`; no invented telemetry | PASS |
| 20 | Technical drawer | Closed by default on every fresh load; only real values (request/conversation id, route = intent, model or "Not used" on deterministic turns, the knowledge reference, `n8n execution N` from the response, round-trip ms, result). Nothing inferred | PASS |
| 21 | Responsive | See §R | PASS (local, labelled) |
| 22 | Restart / persistence | DB snapshot → control `stack/restart` (all healthy, webhook ready 0.5 s) → **identical** tickets, leads and handoffs. After a browser reload: "Connected", drawer closed; T-1003 lookup works; RAG still answers with its source. Chat history isn't restored (not a backend feature) | PASS |
| 23 | Secret scan | Browser: 0 token strings in DOM, attributes, text, localStorage and URL; 0 console messages through a draft → Cancel flow; bundle: 0 `Bearer <value>`, 0 `sk-or-`, no credential variable names, 0 16-hex strings. VM `/scan`: **0 occurrences** of all 7 secrets (DB password, customer A/B tokens, n8n key, OpenRouter key, lead-writer token, control token) in backend, web, n8n and db logs, the run log, the served bundle (3 files), the **web image filesystem**, and its history and config | PASS |

**Final real data before teardown.**
- Tickets: T-1001, T-1002 (seed), T-1003 critical, T-1004 normal.
- Leads: 2 (n8n executions 1 and 3).
- Handoffs: 3.
- Ticket actions: consumed 2, superseded 1, cancelled 2. Lead actions: consumed 2.
- 4 n8n executions, all `success`.

## R. Responsive (§22)
**Why this check was run locally.** The extension cannot resize this Chrome window: the viewport stays 1536 px even
after resize and restore attempts. The web runtime correctly forbids framing (`frame-ancestors 'none'`) and the browser
blocks popups. So the 390/820 check ran on the **identical frontend source**, under the local Vite dev server, against
the **TEST fixture backend**, with two same-origin iframes. It's labelled TEST in screenshots 11–12. The layout is pure
CSS and does not depend on backend data.

**At 390 and 820 px:**
- no horizontal overflow; the avatar is 28×28;
- the composer is usable and the cards readable;
- the sidebar is behind the menu button at 390;
- the drawer is a fixed 320 px overlay with a close button.

At 1536 px the real stack was checked throughout §B.

## Issues found
**Application defects: none.**

**UI-only LOW (not blocking; recorded in PROJECT_STATE):**
1. **UI02-01.** When the backend re-shows the *same* version (the `confirmation_review_required` after an unbound
   CONFIRMAR), the earlier copy of that draft is badged "Replaced". It is correctly not actionable, but "Replaced"
   overstates it, since the data didn't change.
2. **UI02-02.** A sidebar entry's time is when its empty conversation slot was created, not when the first message was
   sent. Seen with Customer B: the slot was created at page load (06:08) and used at 06:16.
3. **UI02-03.** Around 820 px with the sidebar visible, the 4 draft tiles are about 100 px wide, so long values are
   truncated with an ellipsis (the full value is in the tooltip).

**Harness and automation issues, kept separate from the application:**
- **Run 1 disconnect.** The SSH session was reset by the network after setup, with no keepalive. The harness had no
  disconnect handling, so the stack and secrets stayed on the VM.
- **Cleanup v1 killed itself.** Its `pkill` pattern matched its own command line, so it ran but cleaned nothing. v2 uses
  a regex bracket and excludes itself; it verified 0 containers, volumes and processes, the work dir removed, and no
  listeners.
- **Run 2 fixes:** SSH keepalives, the harness ignores SIGPIPE, and a control-endpoint heartbeat triggers automatic
  teardown if the session is lost (tested locally).
- **Fetch recorder.** The extension's JavaScript runs in an isolated world and the CSP blocks inline scripts, so the
  page's `fetch` couldn't be wrapped. Token transport was proven from backend behaviour and the audit instead.
- **One coordinate slip** (clicks below a 639 px viewport) sent nothing; I redid the step.
- **One read-only control query** used the wrong column name for `pending_lead_actions`. Lead actions were still proven
  through the join query and the summary.

**Known backend LOW (unchanged):** AGENT01BF3-01 (`_touch()` creates no `chat_conversations` row when none exists).

## Files
- `vm-e2e.sh`: the harness (setup, the allowlisted control endpoint, teardown).
- `vm-cleanup.sh`: the v2 recovery cleanup.
- `vm-run2-accepted.txt`, `vm-run1-disconnected.txt`, `vm-cleanup1-selfkilled.txt`, `vm-cleanup2-verified.txt`:
  sanitized logs.
- `vm-scan.json`, `vm-final_summary.json`, `vm-final_n8n.json`, `vm-before_restart.json`, `vm-after_restart.json`.
- `screenshots/01–12` (synthetic data only; 11–12 are TEST).
- `checks.txt`: typecheck, lint, **17/17 tests** (11 UI + 6 web boundary), build.
