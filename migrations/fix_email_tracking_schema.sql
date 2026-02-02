-- Fix email tracking table schema for proper deduplication
-- Problem: UNIQUE constraints on nullable columns allow multiple NULLs
-- Solution: Create partial unique indexes that only apply when column is NOT NULL

-- Drop old constraints if they exist
ALTER TABLE email_tracking DROP CONSTRAINT IF EXISTS email_tracking_message_id_key;
ALTER TABLE email_tracking DROP CONSTRAINT IF EXISTS email_tracking_thread_id_key;

-- Drop old indexes if they exist (we'll recreate them)
DROP INDEX IF EXISTS idx_email_tracking_message_id;
DROP INDEX IF EXISTS idx_email_tracking_thread_id;
DROP INDEX IF EXISTS idx_email_tracking_unique_message;
DROP INDEX IF EXISTS idx_email_tracking_unique_thread;

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

-- Keep the created_at index for cleanup queries
CREATE INDEX IF NOT EXISTS idx_email_tracking_created_at ON email_tracking(created_at);

-- Add index on tracking_type for faster queries
CREATE INDEX IF NOT EXISTS idx_email_tracking_type ON email_tracking(tracking_type);

-- Clean up duplicate records (keep the oldest one)
-- This is a safety measure in case duplicates were created before this fix
DELETE FROM email_tracking a
USING email_tracking b
WHERE a.id > b.id
AND a.message_id IS NOT NULL
AND a.message_id = b.message_id
AND a.tracking_type = b.tracking_type;

DELETE FROM email_tracking a
USING email_tracking b
WHERE a.id > b.id
AND a.thread_id IS NOT NULL
AND a.thread_id = b.thread_id
AND a.tracking_type = b.tracking_type;

-- Comment explaining the fix
COMMENT ON TABLE email_tracking IS 'Tracks processed email messages and replied threads to prevent duplicate responses. Fixed schema uses partial unique indexes for proper deduplication.';
