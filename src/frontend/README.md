# Nexo evaluation client (UI-01)

A web chat for evaluating the agent (REQ-ARCH-06). It is a faithful rebuild of the approved Stitch design
**NEXO_UI_FREEZE_01** and talks only to the existing `POST /chat` API.

## Run locally
```bash
cd src/frontend
npm ci                                  # installs the locked dependencies into node_modules (git-ignored)
# The backend must be running on 127.0.0.1:8000 (or set NEXO_BACKEND_URL).
# The synthetic demo credentials are read server-side by the dev proxy from the environment, else from the repo's .env:
AUTH_TOKEN_CUSTOMER_A=... AUTH_TOKEN_CUSTOMER_B=... npm run dev    # http://127.0.0.1:5173
```
`npm run build` produces `dist/`, and `npm run preview` serves it with the same proxy.

## Evaluator runtime (Docker Compose, UI-02)
The `web` service in `compose.yaml` builds this folder: `npm ci` from the lockfile, typecheck and `vite build`. The service
then runs `server/server.mjs`, which uses the Node.js standard library only and has no dependencies. That server:
- serves `dist/` with security headers (CSP, `nosniff`, `no-referrer`, `DENY` framing);
- proxies **only** `POST /api/chat` → `/chat` and `GET /api/health/ready` → `/health/ready`, and answers `404` for every other
  `/api/*` path;
- attaches the session's synthetic Bearer token from its **runtime environment** (`AUTH_TOKEN_CUSTOMER_A/B`). It never
  receives tokens as build args, and never puts them in the bundle;
- forwards only `Content-Type` and a valid `X-Conversation-ID`, and drops every other browser header (`Authorization`,
  `Cookie`, ...).

It listens on `127.0.0.1:${WEB_PORT:-8080}`, on the `web` network only, so it can reach the backend but not PostgreSQL or n8n.

## Identity
- **The browser never holds a credential.** The page names a demo session (`X-Demo-Session: A|B`). The Vite proxy
  removes any browser `Authorization`/`Cookie` header and attaches that session's synthetic Bearer token server-side.
- **Unknown sessions and missing credentials get 503,** and nothing is forwarded.
- **The backend decides who the customer is.** The UI never sends a `customer_id`; text such as
  `customer_id = CUSTOMER_B` is only a message.

## Confirmation
- **Draft card:** a prepared action renders as the amber draft card. Its `confirmation_token` is kept in memory only;
  it is never rendered, logged or modified.
- **Confirm:** sends `{"message": "CONFIRMAR", "confirmation_token": <that draft's token>}`. Only the draft that is
  still current is actionable. If the backend answers `confirmation_review_required`, the new version is shown and must
  be confirmed again.
- **Cancel:** sends `{"message": "CANCELAR"}`.
- **Success card:** the green card renders only for HTTP 200 with a persisted object in `result`.

## Checks
`npm run typecheck`, `npm run lint`, `npm test` (Vitest + Testing Library, TEST fixtures only), `npm run build`.

`scripts/fixture-backend.mjs` is a **TEST-only** fixed-response stand-in, used for visual checks without a model call.
It is not the Nexo backend.
