-- Skill Effectiveness Tracker
-- PRD Requirements: TRAIN-001, TRAIN-002, TRAIN-003
--
-- Adds telemetry table for tracking skill execution outcomes
-- and effectiveness scoring columns on skill_versions.

-- Skill execution telemetry: one row per invocation of a promoted skill
CREATE TABLE IF NOT EXISTS skill_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_version_id UUID NOT NULL REFERENCES skill_versions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id TEXT,
    -- Outcome signals
    execution_status TEXT NOT NULL CHECK (execution_status IN ('success', 'error', 'timeout')),
    user_edited_output BOOLEAN DEFAULT false,
    user_sent_thank_you BOOLEAN DEFAULT false,
    user_repeated_request BOOLEAN DEFAULT false,
    conversation_turns INT,
    -- Metadata
    execution_time_ms INT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_skill_executions_version ON skill_executions(skill_version_id, created_at DESC);
CREATE INDEX idx_skill_executions_user ON skill_executions(user_id, created_at DESC);

-- Add effectiveness score columns to skill_versions
ALTER TABLE skill_versions ADD COLUMN IF NOT EXISTS effectiveness_score FLOAT DEFAULT NULL;
ALTER TABLE skill_versions ADD COLUMN IF NOT EXISTS total_executions INT DEFAULT 0;
ALTER TABLE skill_versions ADD COLUMN IF NOT EXISTS last_scored_at TIMESTAMPTZ DEFAULT NULL;
