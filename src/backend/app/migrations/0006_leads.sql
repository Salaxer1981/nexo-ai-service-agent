-- 0006: confirmed lead creation through n8n (REQ-LEAD-01..03, REQ-CONF-03, REQ-RESP-03/04, REQ-API-03).
-- Invariant: a lead row can only be written by the private lead-write path that n8n calls with a
-- dedicated service credential, for an action the user explicitly confirmed.

-- 1. Machine credentials, separate from customer credentials (different table = different namespace:
--    a customer token can never authenticate here). Only the SHA-256 of the token is stored.
CREATE TABLE service_credentials (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name         text NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9-]{1,64}$'),
    scope        text NOT NULL CHECK (scope IN ('lead_write')),
    token_sha256 text NOT NULL UNIQUE CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER service_credentials_set_updated_at BEFORE UPDATE ON service_credentials
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 2. Prepared lead actions: exact data shown to the user, awaiting confirmation.
--    pending -> confirmed (Idempotency-Key bound, dispatched to n8n) -> consumed (lead persisted)
--    pending -> superseded | expired
CREATE TABLE pending_lead_actions (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    requested_by_customer_id text NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    conversation_id          text CHECK (conversation_id ~ '^[A-Za-z0-9._-]{1,64}$'),
    company_name             text NOT NULL CHECK (length(company_name) BETWEEN 1 AND 200),
    contact_name             text NOT NULL CHECK (length(contact_name) BETWEEN 1 AND 200),
    contact_email            text NOT NULL CHECK (length(contact_email) BETWEEN 3 AND 254
                                                  AND contact_email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    need                     text NOT NULL CHECK (length(need) BETWEEN 1 AND 2000),
    payload_hash             text NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
    status                   text NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'confirmed', 'consumed', 'superseded', 'expired')),
    -- SHA-256 of the Idempotency-Key bound at confirmation (the raw key is not stored).
    confirm_key_sha256       text CHECK (confirm_key_sha256 ~ '^[0-9a-f]{64}$'),
    expires_at               timestamptz NOT NULL,
    confirmed_at             timestamptz,
    consumed_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CHECK ((status IN ('confirmed', 'consumed')) = (confirm_key_sha256 IS NOT NULL AND confirmed_at IS NOT NULL)),
    CHECK ((status = 'consumed') = (consumed_at IS NOT NULL))
);
-- One pending action per (session, conversation) group (same rule as tickets, APP02-01).
CREATE UNIQUE INDEX pending_lead_actions_one_pending_per_group
    ON pending_lead_actions (requested_by_customer_id, coalesce(conversation_id, ''))
    WHERE status = 'pending';
-- An Idempotency-Key confirms at most one action per session.
CREATE UNIQUE INDEX pending_lead_actions_confirm_key
    ON pending_lead_actions (requested_by_customer_id, confirm_key_sha256)
    WHERE confirm_key_sha256 IS NOT NULL;
CREATE TRIGGER pending_lead_actions_set_updated_at BEFORE UPDATE ON pending_lead_actions
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- 3. Leads (REQ-API-03: company_name, contact_name, contact_email, need, generated id).
CREATE TABLE leads (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name             text NOT NULL CHECK (length(company_name) BETWEEN 1 AND 200),
    contact_name             text NOT NULL CHECK (length(contact_name) BETWEEN 1 AND 200),
    contact_email            text NOT NULL CHECK (length(contact_email) BETWEEN 3 AND 254
                                                  AND contact_email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
    need                     text NOT NULL CHECK (length(need) BETWEEN 1 AND 2000),
    -- Session that requested and confirmed it (prototype identity; not a customer relationship).
    requested_by_customer_id text NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    -- One lead per confirmed action, enforced by the database.
    source_action_id         uuid NOT NULL UNIQUE REFERENCES pending_lead_actions (id) ON DELETE RESTRICT,
    -- n8n execution that delivered the write: evidence that the workflow was in the path.
    workflow_execution_id    text NOT NULL CHECK (workflow_execution_id ~ '^[A-Za-z0-9._:-]{1,64}$'),
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
CREATE TRIGGER leads_set_updated_at BEFORE UPDATE ON leads
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
