-- 0002: deterministic SYNTHETIC assessment data. No real people or companies.
-- Credentials are NOT seeded here; they are provisioned at runtime from the environment
-- (see app/provision_auth.py) so no secret is ever part of the repository.

INSERT INTO customers (id, display_name, created_at) VALUES
    ('CUSTOMER_A', 'Synthetic Customer A', '2026-10-01T09:00:00Z'),
    ('CUSTOMER_B', 'Synthetic Customer B', '2026-10-01T09:00:00Z');

INSERT INTO tickets (id, customer_id, contact_name, subject, description, priority, status, created_at, updated_at) VALUES
    ('a0000000-0000-4000-8000-000000000001', 'CUSTOMER_A', 'Test Contact A',
     'Synthetic: cannot access dashboard',
     'Synthetic test ticket for CUSTOMER_A. Contains no real data.',
     'medium', 'open', '2026-10-01T10:00:00Z', '2026-10-01T10:00:00Z'),
    ('b0000000-0000-4000-8000-000000000001', 'CUSTOMER_B', 'Test Contact B',
     'Synthetic: invoice copy request',
     'Synthetic test ticket for CUSTOMER_B. Contains no real data.',
     'low', 'in_progress', '2026-10-01T11:00:00Z', '2026-10-01T11:00:00Z');
