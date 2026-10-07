-- 0008 (AGENT-01B): conversational actions.
--  1. 'cancelled' as a terminal state of prepared actions (a cancelled action can never be confirmed:
--     the existing confirm logic already rejects every status other than 'pending').
--  2. chat_conversations: the MINIMAL state needed to continue an action safely: a pointer to the prepared
--     action (the authoritative payload stays in pending_*_actions) and the fields collected so far for an
--     action that is not prepared yet. No transcripts. One row per (customer, conversation): another customer
--     reusing the same conversation id gets a separate row.
--  3. tickets.reference: a short, immutable, evaluator-friendly reference (PDF journey D: «T-1001»), always
--     resolved together with the authenticated customer (it never replaces the ownership check).

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pending_ticket_actions_status_check')
       OR NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'pending_lead_actions_status_check') THEN
        RAISE EXCEPTION 'expected status check constraints not found';
    END IF;
END $$;

ALTER TABLE pending_ticket_actions DROP CONSTRAINT pending_ticket_actions_status_check;
ALTER TABLE pending_ticket_actions ADD CONSTRAINT pending_ticket_actions_status_check
    CHECK (status IN ('pending', 'consumed', 'superseded', 'expired', 'cancelled'));
ALTER TABLE pending_lead_actions DROP CONSTRAINT pending_lead_actions_status_check;
ALTER TABLE pending_lead_actions ADD CONSTRAINT pending_lead_actions_status_check
    CHECK (status IN ('pending', 'confirmed', 'consumed', 'superseded', 'expired', 'cancelled'));

CREATE TABLE chat_conversations (
    customer_id         text NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    conversation_id     text NOT NULL CHECK (conversation_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    collecting_kind     text CHECK (collecting_kind IN ('ticket', 'lead')),
    draft               jsonb CHECK (draft IS NULL OR (jsonb_typeof(draft) = 'object' AND length(draft::text) <= 12000)),
    action_kind         text CHECK (action_kind IN ('ticket', 'lead')),
    action_id           uuid,
    action_payload_hash text CHECK (action_payload_hash ~ '^[0-9a-f]{64}$'),
    action_status       text CHECK (action_status IN ('pending', 'completed', 'cancelled')),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (customer_id, conversation_id),
    -- the action pointer is all-or-nothing; a draft only exists while collecting
    CONSTRAINT chat_conversations_action_pointer CHECK (
        (action_kind IS NULL AND action_id IS NULL AND action_payload_hash IS NULL AND action_status IS NULL)
        OR (action_kind IS NOT NULL AND action_id IS NOT NULL AND action_payload_hash IS NOT NULL AND action_status IS NOT NULL)),
    CONSTRAINT chat_conversations_draft_kind CHECK ((draft IS NULL) = (collecting_kind IS NULL))
);
CREATE TRIGGER chat_conversations_set_updated_at BEFORE UPDATE ON chat_conversations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE SEQUENCE ticket_reference_seq START WITH 1001;
ALTER TABLE tickets ADD COLUMN reference text;
-- Existing tickets numbered deterministically by creation (seed: CUSTOMER_A's ticket = T-1001, CUSTOMER_B's = T-1002).
WITH ordered AS (SELECT id, row_number() OVER (ORDER BY created_at, id) AS n FROM tickets)
UPDATE tickets t SET reference = 'T-' || (1000 + o.n) FROM ordered o WHERE o.id = t.id;
SELECT setval('ticket_reference_seq', GREATEST(1001, (SELECT count(*) FROM tickets) + 1001), false);
ALTER TABLE tickets ALTER COLUMN reference SET DEFAULT 'T-' || nextval('ticket_reference_seq');
ALTER TABLE tickets ALTER COLUMN reference SET NOT NULL;
ALTER TABLE tickets ADD CONSTRAINT tickets_reference_key UNIQUE (reference);
ALTER TABLE tickets ADD CONSTRAINT tickets_reference_format CHECK (reference ~ '^T-[0-9]{4,9}$');

CREATE FUNCTION tickets_reference_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.reference IS DISTINCT FROM OLD.reference THEN
        RAISE EXCEPTION 'ticket reference is immutable';
    END IF;
    RETURN NEW;
END $$;
CREATE TRIGGER tickets_reference_immutable BEFORE UPDATE ON tickets
    FOR EACH ROW EXECUTE FUNCTION tickets_reference_immutable();
