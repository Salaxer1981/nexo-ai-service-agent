# Known limitations (declared at delivery)

## Open findings
| ID | Severity | Limitation |
|---|---|---|
| AGENT01BF3-01 | LOW (backend) | `_touch()` (advance the conversation revision before a mutation) doesn't create a `chat_conversations` row when none exists. It affects only the secondary concurrency signal; the authoritative action recheck still guarantees correctness. No blocker observed in the VM or browser runs |
| UI02-01 | LOW (UI) | When the backend re-shows the *same* draft (`confirmation_review_required`), the earlier copy is badged "Replaced". It's correctly not actionable, but the wording overstates it |
| UI02-02 | LOW (UI) | A sidebar entry's time is when its empty conversation slot was created, not when its first message was sent |
| UI02-04 | LOW (UI) | The "Connected" badge checks readiness only when the page loads; during an outage it updates on reload. Requests always report the failure honestly |
| UI02-03 | LOW (UI) | Around 820 px with the sidebar visible, the four draft tiles are about 100 px wide and long values are truncated (the full value is in the tooltip) |

## Validation scope
- **Responsive layout:**
  - **desktop:** validated in a real browser against the real stack;
  - **390 px and 820 px:** checked on the **identical frontend code**, locally, against a TEST fixture backend. The
    automated browser window couldn't be resized, and the production web runtime correctly forbids framing. Layout
    is pure CSS, independent of backend data.
- **Price update (120 € → 150 €):** validated on the VM at retrieval and chat level, then restored (FINAL-02).
- **Backup and restore** were executed on the VM (FINAL-02). The destructive reset (`down -v`) is documented but wasn't
  run on the evaluation deployment, on purpose.
- **Outages:** real n8n, backend and PostgreSQL outages were exercised on the VM. LLM timeout/429/5xx were proven with
  stub servers (TEST).
- **Deployments:** the validation runs (AV1, BV1, UI-02) were temporary. FINAL-02 left the stack running on the VM for
  evaluation (owner-authorized), with backups in `~/nexo-eval-backups`.

## Security and identity model (evaluation-only)
- **Two demo customers:** two synthetic customers with static bearer tokens. No expiry, rotation, user accounts or MFA.
  **Not a production identity platform.**
- **The web port is the demo login:** the web client's server-side boundary attaches the demo credential for the
  session the browser selects. Anyone who can reach the **loopback** web port (on the host, or through an SSH tunnel)
  can act as either synthetic customer. That's acceptable for evaluation only.
- **Secrets:** they live in a host `.env` (mode 600), with no production secret manager. Nothing is certified (no
  ISO/SOC claims).
- **Data sent to OpenRouter / xAI:** user messages, retrieved knowledge sections and minimal conversation context.
  Never customer IDs, tokens, credentials or ticket rows.
- **VM address in git history:** it appeared in 3 earlier commits (no credentials). It's redacted from the current
  files.

## Functional
- **No SLA:** no response or resolution time is promised; handoffs are only ever "pending".
- **No restored history:** the conversation history isn't restored after a page reload (not a backend feature).
  Server-side records (tickets, leads, handoffs) persist.
- **Model latency:** a turn usually takes 2–15 s. Turns over 30 s answer 503 `llm_unavailable`; that's safe, with no
  false success. Intent classification depends on the model and may ask for clarification.
- **No grounding entailment:** the guard checks citations and figures, not full logical entailment.
- **No rate limits:** there's no rate limit or per-customer LLM budget (OpenRouter account limit only).
- **No connection pool:** one database connection per operation, which is fine at assessment load.
- **Python lockfile:** only direct Python dependencies are pinned (no hash lockfile). npm dependencies are locked.

## Improvements before production
- **Identity:** real authentication (OIDC), per-user sessions, and token rotation.
- **Secrets:** a secret manager.
- **Network edge:** TLS termination and a reverse proxy with rate limiting.
- **Operations:** a connection pool, centralized logs with retention, alerting, and scheduled backups with tested
  restores.
- **UI:** fix UI02-01..04, and persist conversation history server-side if needed.
- **Backend:** fix AGENT01BF3-01 (create the row in `_touch()`).
