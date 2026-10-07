-- 0005: persisted human handoffs (REQ-HANDOFF-01..04, REQ-API-01/03: conversation_id, reason,
-- summary, status, generated id). The row itself carries its idempotency key, so the escalation
-- and its idempotency state are created by ONE insert and can never disagree.

CREATE TABLE handoffs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- From the authenticated context only, never from request content.
    customer_id     text NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    conversation_id text NOT NULL CHECK (conversation_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    -- The three escalation triggers named by the assessment (REQ-HANDOFF-01). Deciding WHICH
    -- applies is the agent's job (later phase); the API only validates and persists.
    reason          text NOT NULL CHECK (reason IN ('critical_incident', 'human_requested', 'unsafe_to_resolve')),
    summary         text NOT NULL CHECK (length(summary) BETWEEN 1 AND 2000),
    -- Only 'pending' exists: nothing in the system can yet evidence that a person picked it up
    -- (REQ-HANDOFF-03). New states require a migration plus a real, evidenced transition.
    status          text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending')),
    idempotency_key text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
    request_hash    text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT handoffs_customer_idempotency_key UNIQUE (customer_id, idempotency_key)
);

CREATE INDEX handoffs_status_created_idx ON handoffs (status, created_at);

CREATE TRIGGER handoffs_set_updated_at BEFORE UPDATE ON handoffs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
