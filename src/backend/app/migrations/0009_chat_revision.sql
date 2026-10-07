-- 0009 (AGENT-01BF1): a monotonically increasing revision of each conversation's state.
-- Every state change increments it. A turn that interpreted the message against revision N may only publish its
-- proposal (draft/prepare) if the state is still at revision N under the conversation lock; otherwise it fails safe
-- (the model's proposal was based on stale state). Existing rows start at 0.
ALTER TABLE chat_conversations ADD COLUMN revision bigint NOT NULL DEFAULT 0 CHECK (revision >= 0);
