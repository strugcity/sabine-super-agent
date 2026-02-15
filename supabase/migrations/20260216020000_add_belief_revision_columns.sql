-- =============================================================================
-- Add Belief Revision columns to memories table (Phase 2C)
-- =============================================================================
-- Supports the non-monotonic belief revision formula: v' = a * lambda_alpha + v
-- where v = current confidence, a = argument force, lambda_alpha = open-mindedness.
--
-- PRD Requirements: MEM-005 (conflict detection), MEM-006 (version tagging),
-- MEM-007 (temporary deviation with 7-day expiry), BELIEF-004 through BELIEF-007.
-- =============================================================================

-- Confidence score for belief strength (v in the formula)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS confidence FLOAT DEFAULT 1.0
    CHECK (confidence >= 0.0 AND confidence <= 1.0);

-- Version counter for belief revision history (MEM-006)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS belief_version INTEGER DEFAULT 1
    CHECK (belief_version >= 1);

-- Temporary deviation flag with auto-expiry (MEM-007)
ALTER TABLE memories ADD COLUMN IF NOT EXISTS is_temporary_deviation BOOLEAN DEFAULT false;
ALTER TABLE memories ADD COLUMN IF NOT EXISTS deviation_expires_at TIMESTAMPTZ;

-- Index for querying temporary deviations that need expiry cleanup
CREATE INDEX IF NOT EXISTS idx_memories_deviation_expiry
    ON memories(deviation_expires_at)
    WHERE is_temporary_deviation = true AND deviation_expires_at IS NOT NULL;

-- Index for filtering by confidence level
CREATE INDEX IF NOT EXISTS idx_memories_confidence
    ON memories(user_id, confidence DESC);

-- Comment on new columns
COMMENT ON COLUMN memories.confidence IS 'Belief strength score (0.0-1.0). Used in revision formula: v_new = a * lambda_alpha + v';
COMMENT ON COLUMN memories.belief_version IS 'Monotonically increasing version counter for belief revision tracking (MEM-006)';
COMMENT ON COLUMN memories.is_temporary_deviation IS 'True if this memory contradicts >3 related memories and is flagged as a temporary deviation (MEM-007)';
COMMENT ON COLUMN memories.deviation_expires_at IS '7-day expiry timestamp for temporary deviations. Auto-promoted to permanent if reconfirmed before expiry (MEM-007)';
