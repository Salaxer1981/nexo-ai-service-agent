# UI-01 — Approved Stitch design NEXO_UI_FREEZE_01 rebuilt as the evaluation client

**Result: PASS (local).**
- **Checks:** typecheck, lint, 11/11 focused tests and the production build all pass (`checks.txt`).
- **Visual comparison:** done side by side against the Stitch references, using a TEST fixture backend.
- **Not done yet:** no backend business logic was changed; no paid model call, push or deploy. The real backend has
  **not** been driven through the browser yet (that is the next step, browser E2E).

## 1. Stitch inspection (authenticated Chrome, read-only)
**How I connected.** The Claude in Chrome extension used the owner's Chrome, already signed in to Google:
- no credentials were asked for, typed or stored;
- no cookies or tokens were read;
- the preview iframe URL carries an auth token, so it was never opened or recorded.

**The project.** "NEXO Enterprise Support Portal" (Stitch project `15488289339435938526`). Its canvas holds:

| Canvas position | Stitch title | What it is | Status |
|---|---|---|---|
| top-left card | Sovereign Support | design system (theme + DESIGN.md) | **used for the tokens** |
| top | "Generating Screen…" (auto-title) | older dense iteration, drawer open, extra timing rows | older, not used |
| bottom-left | "Generating Screen…" | older iteration, two drafts stacked | older, not used |
| bottom-middle | "Generating Screen…" | **Customer View**: drawer closed, incident draft + created ticket | **NEXO_UI_FREEZE_01 (A)** |
| bottom-right | "Generating Screen…" | **Evaluator View**: the same screen with the Technical details drawer open | **NEXO_UI_FREEZE_01 (B)** |

**Why the bottom-middle/right pair is the freeze.** Stitch titled all four screens "Generating Screen…", so I picked
the freeze by content:
- they match every freeze criterion: NEXO Support, sidebar, clean conversation, amber draft, green created card,
  composer, Technical details button, drawer closed/open, no SLA;
- their drawer carries the latest prompt's corrections: `Knowledge source: Not used`, `Workflow: Not applicable`, and
  the "Sensitive runtime data is not displayed" notice;
- the older screens still show the earlier prompt's invented items (an "Escalation_v2.3" workflow, an ISO/IEC claim,
  per-stage latencies).

Stitch exposes no screen IDs here: the node id in the preview URL is redacted by the browser tool.

**How I read the design:**
- **Screens:** opened each one with *Preview → New Tab* (read-only) and took zoomed screenshots.
- **Tokens:** read the design system's `DESIGN.md` in the Theme panel (Inter, the type scale, radii 4/6/8px, spacing,
  surfaces, the semantic success/pending/error colours, elevation, buttons, badges, and the layout widths: 260px
  sidebar, ≈340px right pane).
- **Measured:** sidebar ≈260px, drawer ≈320px and content column ≈900px, from the 1280px preview.

**Incident, disclosed:**
- **Accidental edit, reverted.** One click on *Preview → Desktop* registered an edit in the Stitch canvas (the undo
  button became active). I reverted it at once with a single undo; undo was greyed again and redo active, which means
  the original state. Nothing else was changed, and neither *Save* nor *Save and apply* was ever pressed.
- **Clipboard copy didn't work.** A DESIGN.md clipboard copy didn't take effect: the clipboard still held unrelated
  text, which I deleted from the scratchpad unread. I read DESIGN.md on screen instead.

**References.** Kept only in the session scratchpad and the extension's temp folder; none were committed:
- the customer view, in 2 zooms;
- the evaluator view: the drawer, and the header with the draft.

## 2. Reconstructed (not exported)
React + TypeScript + Vite in the new `src/frontend/`. The repo had no frontend before; the owner authorized the local
npm packages for UI-01.

| Stitch element | Component |
|---|---|
| Brand row, New conversation, TODAY/PREVIOUS list, account card | `Sidebar` (`components/Chrome.tsx`) |
| Top bar: title, chip, Connected, Technical details, avatar | `TopBar` |
| Day divider, avatars (amber user, blue N, green check), meta line, bubble | `MessageList` |
| Amber "INCIDENT READY TO REVIEW" card (DRAFT, notice, 4 tiles, Cancel / Confirm incident) | `DraftCard` (`components/Cards.tsx`) |
| Green "INCIDENT CREATED" card (T-ref chip, Ticket / Priority / Status) | `CreatedCard` |
| Composer (textarea + Send) | `Composer` |
| Drawer: TECHNICAL DETAILS + TRACE, execution status, key/value rows, Data protection | `TechnicalDrawer` |

`styles.css` defines the design-system tokens as CSS variables. The breakpoints follow DESIGN.md:
- **below 1024px**, the drawer becomes an overlay;
- **below 768px**, the sidebar goes off-canvas behind a menu button and the tiles drop to 2 columns.

Checked in the browser at 1536px, at 820px and at 390px (through iframes).

## 3. Where the real backend contract overrode the mockup
| Stitch placeholder | UI-01 behaviour | Why |
|---|---|---|
| `INC-84920` chip, "Incident Workspace" | the conversation title (the first message); the chip shows the real T-reference once one is created, otherwise it is hidden | no such ID exists |
| "Connected" | the real `GET /health/ready` result: Connected or Unavailable | real readiness |
| Names "Ana Silva", "Taller Norte (Customer A)" | "You · Synthetic Customer A/B" (the selected demo session; the seed `display_name`) | invented people |
| Past conversations (Oct 24, Oct 19) | only conversations started in this browser session | no list endpoint |
| "View ticket history →" | removed | no such endpoint |
| Paperclip (attachments) | removed | no upload support |
| Draft intro sentence | the backend's own `answer` text (Spanish), shown verbatim above the card | truthful wording, e.g. the critical-incident handoff note |
| Draft "Impact" tile | the ticket `description` | the API has no separate impact field |
| `req_982b…`, `conv_4419ad` | the real `request_id` and `conversation_id` from the response | — |
| Route `create_ticket` | the real `intent` of the turn | — |
| Model `x-ai/grok-4.7` | the real `model`; "Not used" when it is null on the deterministic CONFIRMAR/CANCELAR turn | — |
| Knowledge source | the human-readable `reference` of each RAG source (never chunk id, hash or score); "Business API (ticket)" for status lookups; "Not used" when there are none | — |
| Workflow | `n8n execution <id>` from the lead result; otherwise "Not applicable" | — |
| Duration `342 ms` | the client-measured round trip, labelled "(round trip)" | the API doesn't report server time |
| Result `Created` | the real `status` (or `code`) | — |
| "200 OK (Clean Exit)" | the real HTTP status | — |
| **Pipeline latency** (48/112/182 ms) | **removed** | the backend provides no per-stage telemetry |
| Missing fields | "Not available" | never invented |

**Lead and handoff cards.** These states aren't drawn in Stitch, so they reuse the same design-system card:
- **Lead draft:** Company, Contact, Email, Need. "No request has been registered yet."
- **Lead registered:** green card with the backend `status_message`.
- **Handoff:** a neutral card with a Pending badge and truthful wording: nobody has picked it up yet, and no response
  time is guaranteed.
- **Error:** a red "Not completed" card.

**Draft badge after the fact.** Once a draft is no longer actionable, its badge shows what actually happened to that
version, taken from later authoritative turns: Confirmed, Cancelled or Replaced.

## 4. Confirmation token handling
- **Stored, not shown:** stored only in React state with the message that displayed the draft. It is not rendered, not
  put in any attribute, not logged (`no-console` is a lint error), and not modified. The client checks that it matches
  `^[0-9a-f]{16}$` and refuses to send anything else.
- **Confirm:** sends `{"message":"CONFIRMAR","conversation_id":…,"confirmation_token":<that draft's token>}`. Only
  the draft that is still current has buttons.
- **Changed draft:** if the backend answers `confirmation_review_required`, the new version is rendered and must be
  confirmed with its own token.
- **Cancel:** sends `{"message":"CANCELAR"}`, with no token, through the normal chat path.
- **No direct writes:** there is no new endpoint, and the frontend never calls `/tickets*` or `/leads*`.

## 5. Identity
- **Dev/preview proxy:** `vite.config.js`. The page sends only `X-Demo-Session: A|B`. The proxy strips any
  browser-supplied `Authorization`/`Cookie`, then attaches that synthetic customer's Bearer token server-side, from
  `AUTH_TOKEN_CUSTOMER_A/B` (environment or the git-ignored `.env`).
- **Unknown sessions or missing tokens get 503,** and nothing is forwarded.
- **The browser and the built bundle contain no credential.** I checked `dist/`.
- **No customer field:** there is no editable customer field, and the body never carries `customer_id`.

## 6. Tests (`src/frontend/src/test/app.test.tsx`; 11/11 PASS; contract-shaped TEST fixtures, no network)
1. A normal answer renders, with only the human-readable source; no chunk id, hash or score.
2. The draft card renders (issue, impact, priority, reported by, "No ticket has been created yet.") and the token is not
   in the DOM.
3. Confirm sends exactly `CONFIRMAR` + that draft's token + conversation id. The T-reference card renders (T-1003, Open,
   pending handoff wording). The old draft shows "Confirmed" with no buttons.
4. Cancel sends `CANCELAR` with no token.
5. A superseded draft can't be confirmed; the review version's own token is used; neither token is in the DOM.
6. The technical drawer is closed by default and shows only real fields: request id, conversation id, route (intent),
   model "Not used", knowledge "Not used", workflow "Not applicable", the round-trip duration and the result. It shows
   no token, no Bearer, no reasoning, no SLA and no pipeline latency.
7. Missing telemetry (a 503 with an empty body) shows "Not available" (at least 5 times), never invented IDs.
8. A 503 `lead_not_confirmed`, a 200 "created" without a persisted id, and a 500 with a success body all render **no**
   success card.
9. The text `customer_id = CUSTOMER_B` is sent only as a message: the body keys are exactly `["message"]`, the session
   header stays `A`, and the browser sends no `Authorization`.
10. and 11. The proxy attaches the token server-side and strips browser credentials; it refuses unknown sessions or
    missing tokens with 503.

## 7. Visual validation
I ran the TEST fixture backend (`scripts/fixture-backend.mjs`, fixed responses, no model) with `npm run dev`, drove
draft → Confirm → created, opened the drawer, and triggered an error. I compared the result with the Stitch references.

**Matches:** the 260px sidebar, top bar, Inter type scale, the amber draft (cream background, notice, 4 tiles,
ghost/primary buttons), the green created card (T-ref chip, 3 tiles), the composer, and the 320px drawer.

**Fidelity fixes made during the loop:**
- the menu button was visible on desktop;
- the page scrolled out of its grid;
- the drawer labels wrapped;
- placeholder values were shown in monospace;
- the avatar was squeezed at 390px.

**Remaining known differences (deliberate):** the Spanish backend wording inside the English UI, and the
contract-driven replacements in §3.

## 8. Not yet done
**Browser E2E against the real backend:** real PostgreSQL + `x-ai/grok-4.7` + n8n, using the real synthetic customer
tokens. That's the next step.
