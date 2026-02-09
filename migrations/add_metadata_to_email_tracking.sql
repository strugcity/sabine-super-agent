-- Add metadata column to email_tracking table for storing draft information
-- This enables storing work email draft details when tracking_type='draft_pending'

ALTER TABLE email_tracking 
ADD COLUMN IF NOT EXISTS metadata JSONB;

-- Add index on metadata for faster queries on draft status
CREATE INDEX IF NOT EXISTS idx_email_tracking_metadata 
    ON email_tracking USING GIN (metadata);

-- Comment explaining the column
COMMENT ON COLUMN email_tracking.metadata IS 'JSONB field for storing additional tracking data, such as draft information for work emails';
