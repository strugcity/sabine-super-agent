-- Migration: Create tool_audit_log table for persistent tool execution auditing
-- Date: 2026-02-07
-- Purpose: Enable tracking of all tool executions for debugging, compliance, and analysis

-- =============================================================================
-- TOOL AUDIT LOG TABLE
-- =============================================================================
-- Stores detailed audit trail of every tool execution by agents.
-- This enables:
-- 1. Debugging: Query exact tool calls and their results
-- 2. Compliance: Full audit trail of what agents did
-- 3. Analysis: Performance metrics, failure patterns, usage statistics
-- 4. Security: Detect unauthorized repo access attempts

CREATE TABLE IF NOT EXISTS tool_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Context: Who/what triggered this tool call
    user_id UUID,                              -- User who initiated the request (if known)
    session_id TEXT,                           -- Session/conversation context
    task_id UUID REFERENCES task_queue(id),    -- Task that triggered this (if orchestrated)
    agent_role TEXT,                           -- Agent role that executed the tool

    -- Tool Details
    tool_name TEXT NOT NULL,                   -- Name of the tool (e.g., 'github_issues')
    tool_action TEXT,                          -- Specific action (e.g., 'create_file', 'list')

    -- Input/Output (truncated for storage efficiency)
    input_params JSONB DEFAULT '{}',           -- Tool input parameters (sensitive data redacted)
    output_summary JSONB DEFAULT '{}',         -- Summary of output (not full content)

    -- Status and Errors
    status TEXT NOT NULL CHECK (status IN ('success', 'error', 'timeout', 'blocked')),
    error_type TEXT,                           -- Error classification (auth, permission, network, etc.)
    error_message TEXT,                        -- Full error message (for debugging)

    -- Target Resource (for GitHub operations)
    target_repo TEXT,                          -- Repository targeted (e.g., 'strugcity/sabine-super-agent')
    target_path TEXT,                          -- File path or issue number
    artifact_created TEXT,                     -- What was created (file path, issue #, etc.)

    -- Performance Metrics
    execution_time_ms INTEGER,                 -- How long the tool call took

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- =============================================================================
-- INDEXES FOR COMMON QUERIES
-- =============================================================================

-- Query by user (multi-tenant filtering)
CREATE INDEX idx_tool_audit_user_id ON tool_audit_log(user_id) WHERE user_id IS NOT NULL;

-- Query by task (debugging specific task)
CREATE INDEX idx_tool_audit_task_id ON tool_audit_log(task_id) WHERE task_id IS NOT NULL;

-- Query by tool name (usage statistics)
CREATE INDEX idx_tool_audit_tool_name ON tool_audit_log(tool_name);

-- Query by status (find failures)
CREATE INDEX idx_tool_audit_status ON tool_audit_log(status);

-- Query by target repo (repo-specific audit)
CREATE INDEX idx_tool_audit_target_repo ON tool_audit_log(target_repo) WHERE target_repo IS NOT NULL;

-- Time-based queries (recent activity, time ranges)
CREATE INDEX idx_tool_audit_created_at ON tool_audit_log(created_at DESC);

-- Compound index for dashboard queries
CREATE INDEX idx_tool_audit_role_status ON tool_audit_log(agent_role, status);

-- =============================================================================
-- ROW LEVEL SECURITY
-- =============================================================================

ALTER TABLE tool_audit_log ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (for backend operations)
CREATE POLICY "Service role has full access to tool_audit_log"
    ON tool_audit_log
    FOR ALL
    USING (auth.role() = 'service_role');

-- Allow authenticated users to read their own audit logs
CREATE POLICY "Users can view their own tool audit logs"
    ON tool_audit_log
    FOR SELECT
    USING (
        auth.role() = 'authenticated'
        AND (user_id = auth.uid() OR user_id IS NULL)
    );

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get recent tool executions for a task
CREATE OR REPLACE FUNCTION get_task_tool_executions(p_task_id UUID)
RETURNS TABLE (
    id UUID,
    tool_name TEXT,
    tool_action TEXT,
    status TEXT,
    artifact_created TEXT,
    error_message TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT
        id,
        tool_name,
        tool_action,
        status,
        artifact_created,
        error_message,
        execution_time_ms,
        created_at
    FROM tool_audit_log
    WHERE task_id = p_task_id
    ORDER BY created_at ASC;
$$;

-- Function to get tool execution statistics
CREATE OR REPLACE FUNCTION get_tool_execution_stats(
    p_hours INTEGER DEFAULT 24
)
RETURNS TABLE (
    tool_name TEXT,
    total_calls BIGINT,
    success_count BIGINT,
    error_count BIGINT,
    avg_execution_ms NUMERIC,
    success_rate NUMERIC
)
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT
        tool_name,
        COUNT(*) as total_calls,
        COUNT(*) FILTER (WHERE status = 'success') as success_count,
        COUNT(*) FILTER (WHERE status = 'error') as error_count,
        ROUND(AVG(execution_time_ms), 2) as avg_execution_ms,
        ROUND(
            COUNT(*) FILTER (WHERE status = 'success')::NUMERIC /
            NULLIF(COUNT(*), 0) * 100,
            2
        ) as success_rate
    FROM tool_audit_log
    WHERE created_at >= NOW() - (p_hours || ' hours')::INTERVAL
    GROUP BY tool_name
    ORDER BY total_calls DESC;
$$;

-- Function to get blocked repo access attempts (security monitoring)
CREATE OR REPLACE FUNCTION get_blocked_repo_attempts(
    p_hours INTEGER DEFAULT 24
)
RETURNS TABLE (
    agent_role TEXT,
    target_repo TEXT,
    attempt_count BIGINT,
    latest_attempt TIMESTAMPTZ
)
LANGUAGE sql
SECURITY DEFINER
AS $$
    SELECT
        agent_role,
        target_repo,
        COUNT(*) as attempt_count,
        MAX(created_at) as latest_attempt
    FROM tool_audit_log
    WHERE
        status = 'blocked'
        AND created_at >= NOW() - (p_hours || ' hours')::INTERVAL
    GROUP BY agent_role, target_repo
    ORDER BY attempt_count DESC;
$$;

-- =============================================================================
-- CLEANUP POLICY (Optional - for managing table size)
-- =============================================================================
-- Uncomment to enable automatic cleanup of old audit logs

-- CREATE OR REPLACE FUNCTION cleanup_old_tool_audit_logs()
-- RETURNS INTEGER
-- LANGUAGE plpgsql
-- SECURITY DEFINER
-- AS $$
-- DECLARE
--     deleted_count INTEGER;
-- BEGIN
--     DELETE FROM tool_audit_log
--     WHERE created_at < NOW() - INTERVAL '90 days'
--     RETURNING COUNT(*) INTO deleted_count;
--
--     RETURN deleted_count;
-- END;
-- $$;

COMMENT ON TABLE tool_audit_log IS 'Persistent audit trail of all tool executions by Dream Team agents';
COMMENT ON COLUMN tool_audit_log.user_id IS 'User who initiated the request (may be null for system-triggered tasks)';
COMMENT ON COLUMN tool_audit_log.status IS 'success=tool executed successfully, error=tool returned error, timeout=tool timed out, blocked=access denied';
COMMENT ON COLUMN tool_audit_log.input_params IS 'Tool input parameters with sensitive data redacted';
COMMENT ON COLUMN tool_audit_log.artifact_created IS 'What artifact was created (file path, issue number, commit SHA, etc.)';
