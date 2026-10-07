-- 0004 (APP02-01 backstop): at most ONE pending ticket action per confirmation group
-- (customer_id + conversation scope). prepare() serializes per group with an advisory lock;
-- this index makes the invariant hold for any execution order or future code path.

-- Normalize existing data first: keep only the newest pending action per group.
UPDATE pending_ticket_actions AS p
   SET status = 'superseded'
 WHERE p.status = 'pending'
   AND EXISTS (
       SELECT 1 FROM pending_ticket_actions AS q
        WHERE q.status = 'pending'
          AND q.customer_id = p.customer_id
          AND q.conversation_id IS NOT DISTINCT FROM p.conversation_id
          AND (q.created_at, q.id) > (p.created_at, p.id));

-- '' can never be a real conversation_id (CHECK requires 1-64 chars), so it safely
-- represents "no conversation" in the index.
CREATE UNIQUE INDEX pending_ticket_actions_one_pending_per_group
    ON pending_ticket_actions (customer_id, coalesce(conversation_id, ''))
    WHERE status = 'pending';
