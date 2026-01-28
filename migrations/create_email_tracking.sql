-- Email tracking table for preventing duplicate replies
-- This table persists across Railway deploys (unlike local files)

CREATE TABLE IF NOT EXISTS email_tracking (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255) UNIQUE,
    thread_id VARCHAR(255) UNIQUE,
    tracking_type VARCHAR(50) NOT NULL,  -- 'processed_message' or 'replied_thread'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_email_tracking_message_id ON email_tracking(message_id) WHERE message_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_email_tracking_thread_id ON email_tracking(thread_id) WHERE thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_email_tracking_created_at ON email_tracking(created_at);

-- Clean up old records (older than 30 days) to prevent unbounded growth
-- Run this periodically or set up a cron job
-- DELETE FROM email_tracking WHERE created_at < NOW() - INTERVAL '30 days';
