-- =============================================================================
-- Reminder System Database Migration - Step 1.1
-- =============================================================================
-- Creates the foundational `reminders` table for the hybrid reminder system
-- supporting SMS, email, Slack, and calendar event notifications.
-- 
-- Features:
-- - One-time and recurring reminders (daily, weekly, monthly, yearly)
-- - Multi-channel notification support
-- - Flexible metadata for custom context
-- - Integration with existing user system
-- =============================================================================

-- Create the reminders table
CREATE TABLE IF NOT EXISTS reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Core reminder data
    title TEXT NOT NULL,
    description TEXT,

    -- Type and scheduling
    reminder_type TEXT NOT NULL DEFAULT 'sms'
        CHECK (reminder_type IN ('sms', 'email', 'slack', 'calendar_event')),
    scheduled_time TIMESTAMPTZ NOT NULL,

    -- Recurrence (null = one-time)
    repeat_pattern TEXT
        CHECK (repeat_pattern IS NULL OR repeat_pattern IN ('daily', 'weekly', 'monthly', 'yearly')),

    -- Status tracking
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    last_triggered_at TIMESTAMPTZ,

    -- Multi-channel notification config
    notification_channels JSONB NOT NULL DEFAULT '{"sms": true}',

    -- Flexible metadata (tags, context, scheduler job ID, etc.)
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookup of active reminders for a user, ordered by scheduled time
CREATE INDEX IF NOT EXISTS idx_reminders_user_active_scheduled
    ON reminders(user_id, scheduled_time)
    WHERE is_active = TRUE;

-- Fast lookup of reminders due to fire (for scheduler polling)
CREATE INDEX IF NOT EXISTS idx_reminders_scheduled_active
    ON reminders(scheduled_time)
    WHERE is_active = TRUE AND is_completed = FALSE;

-- Metadata queries (JSONB GIN index)
CREATE INDEX IF NOT EXISTS idx_reminders_metadata
    ON reminders USING gin(metadata);

-- Auto-update updated_at on modification
CREATE TRIGGER update_reminders_updated_at
    BEFORE UPDATE ON reminders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Enable Row Level Security
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;

-- Service role has full access (matches existing pattern)
-- Note: Additional policies can be added for user-level access if needed

-- Table and column comments
COMMENT ON TABLE reminders IS 'Scheduled reminders with support for SMS, email, Slack, and calendar notifications';
COMMENT ON COLUMN reminders.reminder_type IS 'Notification type: sms, email, slack, or calendar_event';
COMMENT ON COLUMN reminders.repeat_pattern IS 'Recurrence pattern: null (one-time), daily, weekly, monthly, yearly';
COMMENT ON COLUMN reminders.notification_channels IS 'JSON config for which channels to notify (e.g., {"sms": true, "slack": true})';
COMMENT ON COLUMN reminders.metadata IS 'Flexible metadata (scheduler job ID, tags, custom context)';
COMMENT ON COLUMN reminders.last_triggered_at IS 'When this reminder was last fired (for recurring reminders)';