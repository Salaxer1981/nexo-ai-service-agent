-- 0003: align ticket priority with the official support policy (REQ-KB-02) and add the
-- confirmation + idempotency model for ticket creation (REQ-CONF-01/02, REQ-IDEMP-01/02).
-- Earlier migrations are NOT edited; history stays reproducible.

-- 1. Priority alignment -------------------------------------------------------------------
-- Official semantics: critical = total outage affecting the whole company;
--                     normal   = problem affecting one person without blocking all activity.
-- Mapping of legacy values:
--   low, medium -> normal  (neither can mean a company-wide total outage)
--   high, urgent -> NOT mapped automatically: whether they meant a company-wide outage cannot be
--                   inferred, so the migration aborts and a human must decide. (At the time of
--                   writing only the two synthetic seed tickets exist: 'medium' and 'low'.)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM tickets WHERE priority IN ('high', 'urgent')) THEN
        RAISE EXCEPTION 'tickets with legacy priority high/urgent need a manual critical/normal decision';
    END IF;
END;
$$;

ALTER TABLE tickets DROP CONSTRAINT tickets_priority_check;
UPDATE tickets SET priority = 'normal' WHERE priority IN ('low', 'medium');
ALTER TABLE tickets ADD CONSTRAINT tickets_priority_check CHECK (priority IN ('normal', 'critical'));

-- 2. Pending ticket actions (prepared, not yet confirmed) --------------------------------
CREATE TABLE pending_ticket_actions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id     text NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    conversation_id text CHECK (conversation_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    contact_name    text NOT NULL CHECK (length(contact_name) BETWEEN 1 AND 200),
    subject         text NOT NULL CHECK (length(subject) BETWEEN 1 AND 200),
    description     text NOT NULL CHECK (length(description) BETWEEN 1 AND 5000),
    priority        text NOT NULL CHECK (priority IN ('normal', 'critical')),
    -- SHA-256 of the canonical serialization of exactly the data shown to the user.
    payload_hash    text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'consumed', 'superseded', 'expired')),
    expires_at      timestamptz NOT NULL,
    consumed_at     timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
);
CREATE INDEX pending_ticket_actions_customer_status_idx ON pending_ticket_actions (customer_id, status);
CREATE TRIGGER pending_ticket_actions_set_updated_at BEFORE UPDATE ON pending_ticket_actions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 3. Database-level guarantee: one confirmed action can produce at most ONE ticket.
ALTER TABLE tickets ADD COLUMN source_action_id uuid
    CONSTRAINT tickets_source_action_id_key UNIQUE
    REFERENCES pending_ticket_actions (id) ON DELETE RESTRICT;

-- 4. Idempotency records, written in the SAME transaction as the ticket ------------------
CREATE TABLE idempotency_keys (
    customer_id       text NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    operation         text NOT NULL CHECK (operation IN ('ticket_confirm')),
    idempotency_key   text NOT NULL CHECK (idempotency_key ~ '^[A-Za-z0-9._:-]{1,128}$'),
    request_hash      text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    pending_action_id uuid NOT NULL REFERENCES pending_ticket_actions (id) ON DELETE RESTRICT,
    ticket_id         uuid NOT NULL REFERENCES tickets (id) ON DELETE RESTRICT,
    response_status   integer NOT NULL,
    response_body     jsonb NOT NULL,
    created_at        timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, operation, idempotency_key)
);
