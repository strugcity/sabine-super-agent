-- =============================================================================
-- Create push_back_log table (Phase 2D — Active Inference)
-- =============================================================================
-- Logs VoI calculations and push-back events per PRD 4.5.
--
-- Requirements:
--   DECIDE-004: Log all VoI calculations for tuning
--   PUSH-003:   User override logged for learning (updates λ_α calibration)
--   PUSH-004:   Push-back rate tracked per user (target: 5-15%)
-- =============================================================================

CREATE TABLE IF NOT EXISTS push_back_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT,
    trace_id TEXT,

    -- Action classification (DECIDE-001)
    action_type TEXT NOT NULL CHECK (action_type IN ('irreversible', 'reversible', 'informational')),
    tool_name TEXT,

    -- VoI components (DECIDE-002, DECIDE-003)
    c_error FLOAT NOT NULL CHECK (c_error >= 0.0 AND c_error <= 1.0),
    p_error FLOAT NOT NULL CHECK (p_error >= 0.0 AND p_error <= 1.0),
    c_int FLOAT NOT NULL CHECK (c_int >= 0.0 AND c_int <= 1.0),
    voi_score FLOAT NOT NULL,

    -- Push-back details (PUSH-001, PUSH-002)
    push_back_triggered BOOLEAN NOT NULL DEFAULT false,
    evidence_memory_ids UUID[] DEFAULT '{}',
    alternatives_offered JSONB DEFAULT '[]',

    -- User response (PUSH-003)
    user_accepted BOOLEAN,
    user_chose_alternative INTEGER,

    -- λ_α calibration impact (PUSH-003)
    lambda_alpha_before FLOAT,
    lambda_alpha_after FLOAT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for push-back rate tracking per user (PUSH-004)
CREATE INDEX IF NOT EXISTS idx_push_back_log_user_rate
    ON push_back_log(user_id, created_at DESC)
    WHERE push_back_triggered = true;

-- Index for VoI analysis and tuning (DECIDE-004)
CREATE INDEX IF NOT EXISTS idx_push_back_log_voi
    ON push_back_log(action_type, voi_score);

-- Index for session-level analysis
CREATE INDEX IF NOT EXISTS idx_push_back_log_session
    ON push_back_log(session_id)
    WHERE session_id IS NOT NULL;

-- RLS
ALTER TABLE push_back_log ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE push_back_log IS 'Logs VoI calculations and push-back events for Active Inference (Phase 2D)';
COMMENT ON COLUMN push_back_log.action_type IS 'Classified action reversibility: irreversible (C=1.0), reversible (C=0.5), informational (C=0.2)';
COMMENT ON COLUMN push_back_log.voi_score IS 'Value of Information: (C_error * P_error) - C_int. Positive = should ask clarification';
COMMENT ON COLUMN push_back_log.push_back_triggered IS 'True if VoI exceeded threshold and push-back was sent to user';
COMMENT ON COLUMN push_back_log.user_accepted IS 'Null=pending, True=accepted push-back, False=overrode push-back';
