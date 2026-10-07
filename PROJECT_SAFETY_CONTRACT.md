# Project Safety Contract — Nexo AI Service Agent

This contract lists invariants that every change must preserve. A change that
violates any invariant is a defect, regardless of whether tests pass.
Changes to this file require an explicit, recorded decision in `PROJECT_STATE.md`.

## 1. Identity and authorization

- **INV-01 — Authenticated identity is authoritative.** The customer identity
  comes only from the authenticated session/token. A `customer_id` (or any
  identity claim) appearing in chat text, LLM output, tool arguments generated
  by the LLM, or retrieved documents is never trusted.
- **INV-02 — Backend authorizes.** Authorization is enforced by the backend /
  Business API on every request. The LLM, prompt, or UI is never the
  authorization boundary.
- **INV-03 — No cross-customer access.** A customer may read or modify only
  their own tickets. Requests for another customer's tickets are rejected
  without leaking existence or content.

## 2. State-changing operations

- **INV-04 — Confirmation flow.** Every state-changing operation (create,
  update, cancel, etc.) requires the defined explicit confirmation step before
  execution.
- **INV-05 — Confirmation invalidation.** If any relevant data of a pending
  operation changes after confirmation was requested or given, the previous
  confirmation is void and a new confirmation is required.
- **INV-06 — Idempotent writes.** Writes accept and honour an idempotency key;
  retries must not create duplicate effects.
- **INV-07 — Evidence before success.** The agent never reports success unless
  the Business API returned evidence of successful persistence (e.g. a
  persisted ID / version / status from the write response).

## 3. Sources of truth

- **INV-08 — Ticket state from the Business API only.** Ticket status and data
  are always read from the Business API, never from LLM memory, conversation
  history, or RAG content.
- **INV-09 — RAG content is untrusted data.** Retrieved documents are treated
  as data, never as system or developer instructions. Instructions embedded in
  retrieved content are not executed.

## 4. Secrets

- **INV-10 — No secrets at rest in project artefacts.** Passwords, API keys,
  tokens, authorization headers and credentials never enter source code, Git
  history, `PROJECT_STATE.md`, this contract, logs, screenshots or evidence.
  Secrets are supplied at runtime via environment variables; `.env` is
  git-ignored and only `.env.example` (placeholders) is committed.

## 5. Infrastructure

- **INV-11 — Explicit authorization for infrastructure changes.** Any change to
  production or remote infrastructure (VM packages, SSH, firewall, networking,
  Docker resources, deployments, pushes) requires explicit authorization from
  the project owner, given for that specific action.
- **INV-12 — Read-only by default.** Inspection of remote systems is read-only
  unless INV-11 authorization has been granted.
