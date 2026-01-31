-- Add metadata column to agent_events if it doesn't exist
-- This is needed for the Trinity integration test

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'agent_events'
        AND column_name = 'metadata'
    ) THEN
        ALTER TABLE agent_events ADD COLUMN metadata JSONB DEFAULT '{}';
    END IF;
END $$;
