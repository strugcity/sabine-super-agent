-- Email tracking table for preventing duplicate replies
-- This table persists across Railway deploys (unlike local files)
-- V2: Uses partial unique indexes for proper deduplication with nullable columns

-- Create the table
CREATE TABLE IF NOT EXISTS email_tracking (
    id SERIAL PRIMARY KEY,
    message_id VARCHAR(255),
    thread_id VARCHAR(255),
    tracking_type VARCHAR(50) NOT NULL,  -- 'processed_message' or 'replied_thread'
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create proper partial unique indexes
-- These ensure uniqueness only when the column is NOT NULL
CREATE UNIQUE INDEX IF NOT EXISTS idx_email_tracking_unique_message
    ON email_tracking(message_id)
    WHERE message_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_tracking_unique_thread
    ON email_tracking(thread_id)
    WHERE thread_id IS NOT NULL;

-- Add composite unique constraint for tracking_type + message_id (for processed_message records)
CREATE UNIQUE INDEX IF NOT EXISTS idx_email_tracking_type_message
    ON email_tracking(tracking_type, message_id)
    WHERE message_id IS NOT NULL AND tracking_type = 'processed_message';

-- Add composite unique constraint for tracking_type + thread_id (for replied_thread records)
CREATE UNIQUE INDEX IF NOT EXISTS idx_email_tracking_type_thread
    ON email_tracking(tracking_type, thread_id)
    WHERE thread_id IS NOT NULL AND tracking_type = 'replied_thread';

-- Index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_email_tracking_created_at ON email_tracking(created_at);

-- Index on tracking_type for faster queries
CREATE INDEX IF NOT EXISTS idx_email_tracking_type ON email_tracking(tracking_type);

-- Comment explaining the table
COMMENT ON TABLE email_tracking IS 'Tracks processed email messages and replied threads to prevent duplicate responses. Uses partial unique indexes for proper deduplication.';
