-- 0001: customers, credential mapping and tickets.
-- Ownership is enforced by the database: every ticket must reference an existing customer.

CREATE TABLE customers (
    id           text PRIMARY KEY CHECK (id ~ '^[A-Z0-9_]{1,64}$'),
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    created_at   timestamptz NOT NULL DEFAULT now()
);

-- Synthetic assessment authentication: maps a bearer token to a customer.
-- Only the SHA-256 of the token is stored; raw tokens never reach the database.
CREATE TABLE api_credentials (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_id  text NOT NULL REFERENCES customers (id) ON DELETE CASCADE,
    label        text NOT NULL,
    token_sha256 text NOT NULL UNIQUE CHECK (token_sha256 ~ '^[0-9a-f]{64}$'),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (customer_id, label)
);

CREATE TABLE tickets (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id  text NOT NULL REFERENCES customers (id) ON DELETE RESTRICT,
    contact_name text NOT NULL CHECK (length(contact_name) BETWEEN 1 AND 200),
    subject      text NOT NULL CHECK (length(subject) BETWEEN 1 AND 200),
    description  text NOT NULL CHECK (length(description) BETWEEN 1 AND 5000),
    priority     text NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    status       text NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX tickets_customer_id_idx ON tickets (customer_id);

CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE TRIGGER tickets_set_updated_at BEFORE UPDATE ON tickets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER api_credentials_set_updated_at BEFORE UPDATE ON api_credentials
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
