-- Phase 4: The Gantry - Agent Events Stream
-- Real-time event table for the God View dashboard and Slack integration
-- Enables tracking of all agent activities, task dispatches, and system events

-- Create the agent_events table
CREATE TABLE IF NOT EXISTS agent_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Link to task (optional - some events are system-wide)
    task_id UUID REFERENCES task_queue(id) ON DELETE SET NULL,

    -- Which agent/role generated this event
    role TEXT,

    -- Event classification
    event_type TEXT NOT NULL CHECK (event_type IN (
        'task_started',
        'task_completed',
        'task_failed',
        'agent_thought',
        'tool_call',
        'tool_result',
        'system_startup',
        'system_shutdown',
        'handshake',
        'error',
        'info'
    )),

    -- Event content/message
    content TEXT NOT NULL,

    -- Additional structured data
    metadata JSONB DEFAULT '{}',

    -- Slack thread tracking (for threaded updates)
    slack_thread_ts TEXT,
    slack_channel TEXT,

    -- Timestamp
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for fast lookups by task
CREATE INDEX IF NOT EXISTS idx_agent_events_task_id
    ON agent_events (task_id);

-- Index for filtering by event type
CREATE INDEX IF NOT EXISTS idx_agent_events_type
    ON agent_events (event_type);

-- Index for role-based filtering
CREATE INDEX IF NOT EXISTS idx_agent_events_role
    ON agent_events (role);

-- Index for time-based queries (dashboard, recent events)
CREATE INDEX IF NOT EXISTS idx_agent_events_created_at
    ON agent_events (created_at DESC);

-- Composite index for Slack thread lookups
CREATE INDEX IF NOT EXISTS idx_agent_events_slack_thread
    ON agent_events (task_id, slack_thread_ts)
    WHERE slack_thread_ts IS NOT NULL;

-- Enable Supabase Realtime on this table
-- This allows clients to subscribe to INSERT events
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime' AND tablename = 'agent_events'
    ) THEN
        ALTER PUBLICATION supabase_realtime ADD TABLE agent_events;
    END IF;
END;
$$;

-- Function to get recent events (for dashboard)
CREATE OR REPLACE FUNCTION get_recent_events(
    limit_count INTEGER DEFAULT 50,
    event_types TEXT[] DEFAULT NULL
)
RETURNS SETOF agent_events AS $$
BEGIN
    IF event_types IS NULL THEN
        RETURN QUERY
        SELECT * FROM agent_events
        ORDER BY created_at DESC
        LIMIT limit_count;
    ELSE
        RETURN QUERY
        SELECT * FROM agent_events
        WHERE event_type = ANY(event_types)
        ORDER BY created_at DESC
        LIMIT limit_count;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Function to get events for a specific task
CREATE OR REPLACE FUNCTION get_task_events(target_task_id UUID)
RETURNS SETOF agent_events AS $$
BEGIN
    RETURN QUERY
    SELECT * FROM agent_events
    WHERE task_id = target_task_id
    ORDER BY created_at ASC;
END;
$$ LANGUAGE plpgsql;

-- Comments for documentation
COMMENT ON TABLE agent_events IS 'Real-time event stream for agent activities - powers God View dashboard and Slack notifications';
COMMENT ON COLUMN agent_events.task_id IS 'Optional link to task_queue - NULL for system events';
COMMENT ON COLUMN agent_events.event_type IS 'Classification of event for filtering and display';
COMMENT ON COLUMN agent_events.slack_thread_ts IS 'Slack thread timestamp for threaded updates';
COMMENT ON FUNCTION get_recent_events IS 'Get recent events for dashboard display';
COMMENT ON FUNCTION get_task_events IS 'Get all events for a specific task';
