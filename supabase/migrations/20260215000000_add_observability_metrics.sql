-- Add observability metrics to task queue
-- This enables comprehensive metrics collection for monitoring and alerting
--
-- Features:
-- - completed_at timestamp for duration calculation
-- - duration_ms for task execution time
-- - error_type for error categorization
-- - task_metrics table for time-series aggregation
-- - Functions for metrics queries

-- =============================================================================
-- Task Queue Enhancements
-- =============================================================================

-- Add completed_at timestamp for accurate duration tracking
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;

-- Add duration_ms calculated field (in milliseconds)
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS duration_ms INTEGER;

-- Add error_type for categorized error tracking
-- Categories: timeout, dependency_failed, agent_error, tool_error,
--             validation_error, external_service, cancelled, unknown
ALTER TABLE task_queue ADD COLUMN IF NOT EXISTS error_type TEXT;

-- Index for metrics queries
CREATE INDEX IF NOT EXISTS idx_task_queue_completed_at ON task_queue(completed_at);
CREATE INDEX IF NOT EXISTS idx_task_queue_error_type ON task_queue(error_type);
CREATE INDEX IF NOT EXISTS idx_task_queue_role_status ON task_queue(role, status);

-- =============================================================================
-- Task Metrics Time-Series Table
-- =============================================================================

-- Stores periodic snapshots of queue health for trend analysis
CREATE TABLE IF NOT EXISTS task_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Queue depth metrics
    total_queued INTEGER NOT NULL DEFAULT 0,
    total_in_progress INTEGER NOT NULL DEFAULT 0,
    total_completed_1h INTEGER NOT NULL DEFAULT 0,  -- Completed in last hour
    total_failed_1h INTEGER NOT NULL DEFAULT 0,     -- Failed in last hour

    -- Health indicators
    blocked_count INTEGER NOT NULL DEFAULT 0,
    stale_1h_count INTEGER NOT NULL DEFAULT 0,
    stale_24h_count INTEGER NOT NULL DEFAULT 0,
    stuck_count INTEGER NOT NULL DEFAULT 0,
    pending_retries INTEGER NOT NULL DEFAULT 0,

    -- Performance metrics (from completed tasks in last hour)
    avg_duration_ms INTEGER,
    p50_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    p99_duration_ms INTEGER,

    -- Success rates (percentage, 0-100)
    success_rate_1h NUMERIC(5,2),

    -- Error breakdown (counts in last hour)
    errors_timeout INTEGER NOT NULL DEFAULT 0,
    errors_dependency INTEGER NOT NULL DEFAULT 0,
    errors_agent INTEGER NOT NULL DEFAULT 0,
    errors_tool INTEGER NOT NULL DEFAULT 0,
    errors_external INTEGER NOT NULL DEFAULT 0,
    errors_other INTEGER NOT NULL DEFAULT 0
);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_task_metrics_recorded_at ON task_metrics(recorded_at DESC);

-- =============================================================================
-- Role Performance Metrics Table
-- =============================================================================

-- Stores aggregated metrics per role for SLA tracking
CREATE TABLE IF NOT EXISTS role_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    role TEXT NOT NULL,

    -- Counts for the period
    total_completed INTEGER NOT NULL DEFAULT 0,
    total_failed INTEGER NOT NULL DEFAULT 0,

    -- Duration stats (milliseconds)
    avg_duration_ms INTEGER,
    min_duration_ms INTEGER,
    max_duration_ms INTEGER,
    p50_duration_ms INTEGER,
    p95_duration_ms INTEGER,

    -- Success rate (percentage, 0-100)
    success_rate NUMERIC(5,2),

    -- Error types breakdown
    errors_by_type JSONB DEFAULT '{}'::JSONB
);

-- Indexes for role queries
CREATE INDEX IF NOT EXISTS idx_role_metrics_recorded_at ON role_metrics(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_role_metrics_role ON role_metrics(role);

-- =============================================================================
-- Functions for Metrics Collection
-- =============================================================================

-- Function to record current queue snapshot
CREATE OR REPLACE FUNCTION record_task_metrics()
RETURNS UUID AS $$
DECLARE
    metrics_id UUID;
    completed_tasks RECORD;
    queue_health RECORD;
BEGIN
    -- Get queue health
    SELECT * INTO queue_health FROM get_task_queue_health();

    -- Calculate completion metrics from last hour
    SELECT
        COUNT(*) FILTER (WHERE status = 'completed') as completed_count,
        COUNT(*) FILTER (WHERE status = 'failed') as failed_count,
        AVG(duration_ms) FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as avg_duration,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as p50_duration,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as p95_duration,
        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as p99_duration,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'timeout') as timeout_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'dependency_failed') as dep_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'agent_error') as agent_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'tool_error') as tool_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type = 'external_service') as external_errors,
        COUNT(*) FILTER (WHERE status = 'failed' AND error_type NOT IN ('timeout', 'dependency_failed', 'agent_error', 'tool_error', 'external_service')) as other_errors
    INTO completed_tasks
    FROM task_queue
    WHERE (completed_at >= NOW() - INTERVAL '1 hour' AND status = 'completed')
       OR (updated_at >= NOW() - INTERVAL '1 hour' AND status = 'failed');

    -- Insert metrics record
    INSERT INTO task_metrics (
        total_queued,
        total_in_progress,
        total_completed_1h,
        total_failed_1h,
        blocked_count,
        stale_1h_count,
        stale_24h_count,
        stuck_count,
        pending_retries,
        avg_duration_ms,
        p50_duration_ms,
        p95_duration_ms,
        p99_duration_ms,
        success_rate_1h,
        errors_timeout,
        errors_dependency,
        errors_agent,
        errors_tool,
        errors_external,
        errors_other
    ) VALUES (
        queue_health.total_queued,
        queue_health.total_in_progress,
        COALESCE(completed_tasks.completed_count, 0),
        COALESCE(completed_tasks.failed_count, 0),
        queue_health.blocked_by_failed_deps,
        queue_health.stale_queued_1h,
        queue_health.stale_queued_24h,
        queue_health.stuck_tasks,
        queue_health.pending_retries,
        completed_tasks.avg_duration::INTEGER,
        completed_tasks.p50_duration::INTEGER,
        completed_tasks.p95_duration::INTEGER,
        completed_tasks.p99_duration::INTEGER,
        CASE
            WHEN (COALESCE(completed_tasks.completed_count, 0) + COALESCE(completed_tasks.failed_count, 0)) > 0
            THEN ROUND(100.0 * COALESCE(completed_tasks.completed_count, 0) /
                 (COALESCE(completed_tasks.completed_count, 0) + COALESCE(completed_tasks.failed_count, 0)), 2)
            ELSE NULL
        END,
        COALESCE(completed_tasks.timeout_errors, 0),
        COALESCE(completed_tasks.dep_errors, 0),
        COALESCE(completed_tasks.agent_errors, 0),
        COALESCE(completed_tasks.tool_errors, 0),
        COALESCE(completed_tasks.external_errors, 0),
        COALESCE(completed_tasks.other_errors, 0)
    )
    RETURNING id INTO metrics_id;

    RETURN metrics_id;
END;
$$ LANGUAGE plpgsql;

-- Function to record role-level metrics
CREATE OR REPLACE FUNCTION record_role_metrics()
RETURNS INTEGER AS $$
DECLARE
    roles_recorded INTEGER := 0;
BEGIN
    -- Insert metrics for each role with activity in last hour
    INSERT INTO role_metrics (
        role,
        total_completed,
        total_failed,
        avg_duration_ms,
        min_duration_ms,
        max_duration_ms,
        p50_duration_ms,
        p95_duration_ms,
        success_rate,
        errors_by_type
    )
    SELECT
        role,
        COUNT(*) FILTER (WHERE status = 'completed') as total_completed,
        COUNT(*) FILTER (WHERE status = 'failed') as total_failed,
        AVG(duration_ms) FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL)::INTEGER as avg_duration,
        MIN(duration_ms) FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as min_duration,
        MAX(duration_ms) FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL) as max_duration,
        (PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL))::INTEGER as p50_duration,
        (PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY duration_ms)
            FILTER (WHERE status = 'completed' AND duration_ms IS NOT NULL))::INTEGER as p95_duration,
        CASE
            WHEN COUNT(*) > 0
            THEN ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'completed') / COUNT(*), 2)
            ELSE NULL
        END as success_rate,
        jsonb_object_agg(
            COALESCE(error_type, 'unknown'),
            error_count
        ) FILTER (WHERE error_type IS NOT NULL OR error_count > 0) as errors_by_type
    FROM (
        SELECT
            role,
            status,
            duration_ms,
            error_type,
            COUNT(*) OVER (PARTITION BY role, error_type) as error_count
        FROM task_queue
        WHERE (completed_at >= NOW() - INTERVAL '1 hour' AND status = 'completed')
           OR (updated_at >= NOW() - INTERVAL '1 hour' AND status = 'failed')
    ) subq
    GROUP BY role
    HAVING COUNT(*) > 0;

    GET DIAGNOSTICS roles_recorded = ROW_COUNT;
    RETURN roles_recorded;
END;
$$ LANGUAGE plpgsql;

-- Function to get latest metrics snapshot
CREATE OR REPLACE FUNCTION get_latest_metrics()
RETURNS TABLE (
    recorded_at TIMESTAMPTZ,
    total_queued INTEGER,
    total_in_progress INTEGER,
    total_completed_1h INTEGER,
    total_failed_1h INTEGER,
    success_rate_1h NUMERIC,
    avg_duration_ms INTEGER,
    p95_duration_ms INTEGER,
    blocked_count INTEGER,
    stuck_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.recorded_at,
        m.total_queued,
        m.total_in_progress,
        m.total_completed_1h,
        m.total_failed_1h,
        m.success_rate_1h,
        m.avg_duration_ms,
        m.p95_duration_ms,
        m.blocked_count,
        m.stuck_count
    FROM task_metrics m
    ORDER BY m.recorded_at DESC
    LIMIT 1;
END;
$$ LANGUAGE plpgsql;

-- Function to get metrics trend (last N hours)
CREATE OR REPLACE FUNCTION get_metrics_trend(hours INTEGER DEFAULT 24)
RETURNS TABLE (
    recorded_at TIMESTAMPTZ,
    total_queued INTEGER,
    total_in_progress INTEGER,
    success_rate_1h NUMERIC,
    avg_duration_ms INTEGER,
    blocked_count INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.recorded_at,
        m.total_queued,
        m.total_in_progress,
        m.success_rate_1h,
        m.avg_duration_ms,
        m.blocked_count
    FROM task_metrics m
    WHERE m.recorded_at >= NOW() - (hours || ' hours')::INTERVAL
    ORDER BY m.recorded_at ASC;
END;
$$ LANGUAGE plpgsql;

-- Function to get role performance summary
CREATE OR REPLACE FUNCTION get_role_performance(time_window INTERVAL DEFAULT '24 hours')
RETURNS TABLE (
    role TEXT,
    total_tasks BIGINT,
    success_rate NUMERIC,
    avg_duration_ms NUMERIC,
    p95_duration_ms NUMERIC,
    total_failures BIGINT
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        t.role,
        COUNT(*) as total_tasks,
        ROUND(100.0 * COUNT(*) FILTER (WHERE t.status = 'completed') / NULLIF(COUNT(*), 0), 2) as success_rate,
        AVG(t.duration_ms) FILTER (WHERE t.status = 'completed')::NUMERIC as avg_duration_ms,
        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY t.duration_ms)
            FILTER (WHERE t.status = 'completed')::NUMERIC as p95_duration_ms,
        COUNT(*) FILTER (WHERE t.status = 'failed') as total_failures
    FROM task_queue t
    WHERE t.created_at >= NOW() - time_window
      AND t.status IN ('completed', 'failed')
    GROUP BY t.role
    ORDER BY total_tasks DESC;
END;
$$ LANGUAGE plpgsql;

-- Function to get error breakdown
CREATE OR REPLACE FUNCTION get_error_breakdown(time_window INTERVAL DEFAULT '24 hours')
RETURNS TABLE (
    error_type TEXT,
    count BIGINT,
    percentage NUMERIC,
    sample_error TEXT
) AS $$
DECLARE
    total_errors BIGINT;
BEGIN
    SELECT COUNT(*) INTO total_errors
    FROM task_queue
    WHERE status = 'failed'
      AND created_at >= NOW() - time_window;

    RETURN QUERY
    SELECT
        COALESCE(t.error_type, 'unknown') as error_type,
        COUNT(*) as count,
        ROUND(100.0 * COUNT(*) / NULLIF(total_errors, 0), 2) as percentage,
        (array_agg(LEFT(t.error, 200) ORDER BY t.updated_at DESC))[1] as sample_error
    FROM task_queue t
    WHERE t.status = 'failed'
      AND t.created_at >= NOW() - time_window
    GROUP BY COALESCE(t.error_type, 'unknown')
    ORDER BY count DESC;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Comments
-- =============================================================================

COMMENT ON TABLE task_metrics IS 'Time-series metrics snapshots for queue health and performance trends';
COMMENT ON TABLE role_metrics IS 'Aggregated performance metrics per agent role';
COMMENT ON FUNCTION record_task_metrics() IS 'Record current queue metrics snapshot (call periodically, e.g., every 5 minutes)';
COMMENT ON FUNCTION record_role_metrics() IS 'Record role-level metrics (call periodically with task metrics)';
COMMENT ON FUNCTION get_latest_metrics() IS 'Get most recent metrics snapshot';
COMMENT ON FUNCTION get_metrics_trend(INTEGER) IS 'Get metrics trend for last N hours';
COMMENT ON FUNCTION get_role_performance(INTERVAL) IS 'Get performance summary by role for time window';
COMMENT ON FUNCTION get_error_breakdown(INTERVAL) IS 'Get error type breakdown for time window';
