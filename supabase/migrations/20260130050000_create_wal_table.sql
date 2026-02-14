-- =============================================================================
-- Write-Ahead Log (WAL) Table for Sabine 2.0 Fast/Slow Path Decoupling
-- =============================================================================
-- This migration creates the WAL infrastructure required to decouple the
-- Fast Path (real-time response) from the Slow Path (async consolidation).
--
-- Purpose:
--   - Capture all incoming interactions BEFORE processing
--   - Enable retry logic for failed consolidation jobs
--   - Provide idempotency guarantees (prevent duplicate entries from Twilio retries)
--   - Support checkpointing for the Slow Path worker
--
-- Performance Target: Write operations < 100ms (Fast Path budget constraint)
--
-- Owner: @backend-architect-sabine
-- PRD Reference: PRD_Sabine_2.0_Complete.md - Section 4.3 (Dual-Stream Ingestion)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- WAL Status Enum
-- -----------------------------------------------------------------------------
-- Tracks the lifecycle of each WAL entry through the processing pipeline

CREATE TYPE wal_status AS ENUM (
    'pending',      -- Awaiting Slow Path processing
    'processing',   -- Currently being processed by worker
    'completed',    -- Successfully processed and consolidated
    'failed'        -- Processing failed (will be retried)
);

COMMENT ON TYPE wal_status IS 'WAL entry lifecycle: pending -> processing -> completed/failed';

-- -----------------------------------------------------------------------------
-- WAL Logs Table
-- -----------------------------------------------------------------------------
-- The core Write-Ahead Log table for capturing raw interactions

CREATE TABLE wal_logs (
    -- Primary identifier
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ,  -- When processing completed (success or failure)

    -- Payload
    raw_payload JSONB NOT NULL,  -- The complete raw interaction data

    -- Processing state
    status wal_status NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,

    -- Error tracking (for failed entries)
    last_error TEXT,

    -- Idempotency key for deduplication (prevents Twilio retry duplicates)
    -- Composite of message content hash + timestamp (truncated to second)
    idempotency_key TEXT UNIQUE,

    -- Worker tracking (for distributed processing if needed later)
    worker_id TEXT,

    -- Checkpointing support
    checkpoint_id UUID,  -- Links to checkpoint if processing was interrupted

    -- Metadata for debugging/analytics
    metadata JSONB DEFAULT '{}'
);

COMMENT ON TABLE wal_logs IS 'Write-Ahead Log for Fast/Slow Path decoupling - captures all interactions before processing';
COMMENT ON COLUMN wal_logs.raw_payload IS 'Complete raw interaction data (user_id, message, source, timestamp, etc.)';
COMMENT ON COLUMN wal_logs.status IS 'Processing status: pending, processing, completed, failed';
COMMENT ON COLUMN wal_logs.retry_count IS 'Number of processing attempts (for retry logic)';
COMMENT ON COLUMN wal_logs.idempotency_key IS 'Unique key to prevent duplicate entries from retries';
COMMENT ON COLUMN wal_logs.worker_id IS 'ID of the worker processing this entry (for distributed processing)';
COMMENT ON COLUMN wal_logs.checkpoint_id IS 'Links to checkpoint record if processing was interrupted';

-- -----------------------------------------------------------------------------
-- Indexes for Performance
-- -----------------------------------------------------------------------------
-- Optimized for the primary query patterns:
-- 1. Fetch pending entries for processing (Slow Path worker)
-- 2. Check for duplicates via idempotency key (Fast Path write)
-- 3. Query by status for monitoring/debugging

-- Primary query: Get pending entries ordered by creation time
CREATE INDEX idx_wal_logs_status_created
    ON wal_logs(status, created_at ASC)
    WHERE status = 'pending';

-- Idempotency check: Fast lookup for duplicate detection
-- (UNIQUE constraint already creates an index, but explicit for clarity)
CREATE INDEX idx_wal_logs_idempotency
    ON wal_logs(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

-- Status monitoring: Count by status for dashboards
CREATE INDEX idx_wal_logs_status
    ON wal_logs(status);

-- Time-based queries: For cleanup jobs and analytics
CREATE INDEX idx_wal_logs_created_at
    ON wal_logs(created_at DESC);

-- Failed entries: For retry queue
CREATE INDEX idx_wal_logs_failed_retry
    ON wal_logs(status, retry_count, created_at)
    WHERE status = 'failed';

-- -----------------------------------------------------------------------------
-- Row Level Security (RLS) Policies
-- -----------------------------------------------------------------------------
-- WAL is system-internal; service role only

ALTER TABLE wal_logs ENABLE ROW LEVEL SECURITY;

-- Service role has full access
CREATE POLICY "Service role full access on wal_logs"
    ON wal_logs
    FOR ALL
    USING (true)
    WITH CHECK (true);

-- -----------------------------------------------------------------------------
-- Trigger for updated_at
-- -----------------------------------------------------------------------------
-- Automatically update the updated_at timestamp on any modification

CREATE OR REPLACE FUNCTION update_wal_logs_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trigger_wal_logs_updated_at'
    ) THEN
        CREATE TRIGGER trigger_wal_logs_updated_at
            BEFORE UPDATE ON wal_logs
            FOR EACH ROW
            EXECUTE FUNCTION update_wal_logs_updated_at();
    END IF;
END;
$$;

-- -----------------------------------------------------------------------------
-- Helper Functions
-- -----------------------------------------------------------------------------

-- Function to generate idempotency key from payload
-- Uses MD5 hash of (user_id + message_content + timestamp_truncated_to_second)
CREATE OR REPLACE FUNCTION generate_wal_idempotency_key(
    p_user_id TEXT,
    p_message TEXT,
    p_timestamp TIMESTAMPTZ
) RETURNS TEXT AS $$
BEGIN
    RETURN MD5(
        COALESCE(p_user_id, '') ||
        '::' ||
        COALESCE(p_message, '') ||
        '::' ||
        TO_CHAR(DATE_TRUNC('second', COALESCE(p_timestamp, NOW())), 'YYYY-MM-DD HH24:MI:SS')
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION generate_wal_idempotency_key IS 'Generates idempotency key for WAL deduplication';

-- Function to claim entries for processing (atomic batch claim)
-- Returns entries and marks them as 'processing' in a single transaction
CREATE OR REPLACE FUNCTION claim_wal_entries(
    p_batch_size INTEGER DEFAULT 100,
    p_worker_id TEXT DEFAULT NULL
) RETURNS SETOF wal_logs AS $$
DECLARE
    claimed_ids UUID[];
BEGIN
    -- Atomically select and update entries
    WITH claimed AS (
        SELECT id
        FROM wal_logs
        WHERE status = 'pending'
        ORDER BY created_at ASC
        LIMIT p_batch_size
        FOR UPDATE SKIP LOCKED  -- Skip locked rows for parallel workers
    )
    UPDATE wal_logs
    SET
        status = 'processing',
        worker_id = p_worker_id,
        updated_at = NOW()
    WHERE id IN (SELECT id FROM claimed)
    RETURNING id INTO claimed_ids;

    -- Return the claimed entries
    RETURN QUERY
    SELECT *
    FROM wal_logs
    WHERE id = ANY(claimed_ids);
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION claim_wal_entries IS 'Atomically claim a batch of pending WAL entries for processing';

-- Function to mark entry as completed
CREATE OR REPLACE FUNCTION complete_wal_entry(
    p_entry_id UUID
) RETURNS BOOLEAN AS $$
BEGIN
    UPDATE wal_logs
    SET
        status = 'completed',
        processed_at = NOW()
    WHERE id = p_entry_id AND status = 'processing';

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION complete_wal_entry IS 'Mark a WAL entry as successfully processed';

-- Function to mark entry as failed (with retry logic)
CREATE OR REPLACE FUNCTION fail_wal_entry(
    p_entry_id UUID,
    p_error TEXT,
    p_max_retries INTEGER DEFAULT 3
) RETURNS BOOLEAN AS $$
DECLARE
    current_retry_count INTEGER;
BEGIN
    SELECT retry_count INTO current_retry_count
    FROM wal_logs
    WHERE id = p_entry_id;

    IF current_retry_count < p_max_retries THEN
        -- Return to pending for retry
        UPDATE wal_logs
        SET
            status = 'pending',
            retry_count = retry_count + 1,
            last_error = p_error,
            worker_id = NULL
        WHERE id = p_entry_id;
    ELSE
        -- Max retries exceeded, mark as permanently failed
        UPDATE wal_logs
        SET
            status = 'failed',
            retry_count = retry_count + 1,
            last_error = p_error,
            processed_at = NOW()
        WHERE id = p_entry_id;
    END IF;

    RETURN FOUND;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION fail_wal_entry IS 'Mark a WAL entry as failed with retry logic';

-- =============================================================================
-- End of Migration
-- =============================================================================
