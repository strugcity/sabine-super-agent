-- =============================================================================
-- Phase 1 Schema Migrations: Salience, WAL Indexes, and Memory Lifecycle
-- =============================================================================
-- This migration extends the existing schema for Sabine 2.0 Phase 1:
--
-- 1. Adds memory lifecycle columns (salience, access tracking, archival)
-- 2. Adds performance indexes for memory retrieval and archival queries
-- 3. Adds a user-scoped index on the existing wal_logs table
-- 4. Creates an updated_at trigger for the memories table (was missing)
--
-- Depends on:
--   - 20260129170000_init_context_engine.sql  (memories table)
--   - 20260130050000_create_wal_table.sql     (wal_logs table)
--
-- Owner: @backend-architect-sabine
-- PRD Reference: Phase 1 - Context Engine Foundation
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. ALTER memories TABLE - Add lifecycle and salience columns
-- -----------------------------------------------------------------------------
-- These columns support:
--   - salience_score:    weighted importance for retrieval ranking (0.0 - 1.0)
--   - last_accessed_at:  recency tracking for memory decay/boosting
--   - access_count:      frequency counter for popularity-based ranking
--   - is_archived:       cold storage flag to exclude from active retrieval

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS salience_score FLOAT DEFAULT 0.5
        CHECK (salience_score >= 0.0 AND salience_score <= 1.0);

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ DEFAULT now();

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS access_count INTEGER DEFAULT 0
        CHECK (access_count >= 0);

ALTER TABLE memories
    ADD COLUMN IF NOT EXISTS is_archived BOOLEAN DEFAULT false;

COMMENT ON COLUMN memories.salience_score IS 'Importance weight for retrieval ranking (0.0 = irrelevant, 1.0 = critical)';
COMMENT ON COLUMN memories.last_accessed_at IS 'Last time this memory was retrieved, for recency-based scoring';
COMMENT ON COLUMN memories.access_count IS 'Number of times this memory has been retrieved, for frequency-based ranking';
COMMENT ON COLUMN memories.is_archived IS 'Cold storage flag: archived memories are excluded from active retrieval';


-- -----------------------------------------------------------------------------
-- 2. INDEXES on memories table for Phase 1 queries
-- -----------------------------------------------------------------------------

-- Salience-based retrieval: find high-importance memories for archival/prioritization
CREATE INDEX IF NOT EXISTS idx_memories_salience_score
    ON memories (salience_score);

-- Active memory retrieval: exclude archived, sort by salience
-- This is the primary index for the Fast Path memory retrieval query
CREATE INDEX IF NOT EXISTS idx_memories_active_salience
    ON memories (is_archived, salience_score DESC)
    WHERE is_archived = false;

-- Recency-based scoring: find recently accessed memories for decay calculations
CREATE INDEX IF NOT EXISTS idx_memories_last_accessed_at
    ON memories (last_accessed_at);

-- Archival candidates: find low-salience, infrequently accessed memories
CREATE INDEX IF NOT EXISTS idx_memories_archival_candidates
    ON memories (salience_score ASC, access_count ASC)
    WHERE is_archived = false;


-- -----------------------------------------------------------------------------
-- 3. INDEXES on wal_logs table for user-scoped queries
-- -----------------------------------------------------------------------------
-- The existing wal_logs table (from 20260130050000) has status+created_at indexes
-- but lacks a user-scoped index for querying WAL entries by user.
-- The raw_payload JSONB contains user_id, so we index the extracted field.

-- User-scoped WAL queries: "show me all pending entries for user X"
-- Note: wal_logs stores user_id inside raw_payload JSONB, so we use a
-- functional index on the extracted value
CREATE INDEX IF NOT EXISTS idx_wal_logs_user_status
    ON wal_logs (
        (raw_payload->>'user_id'),
        status
    );


-- -----------------------------------------------------------------------------
-- 4. updated_at TRIGGER for memories table
-- -----------------------------------------------------------------------------
-- The initial migration (20260129170000) created updated_at on the memories
-- table but did NOT create an auto-update trigger. Adding it now following
-- the pattern from ADR-001-graph-storage.md.

CREATE OR REPLACE FUNCTION update_memories_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Use IF NOT EXISTS pattern via DO block (CREATE TRIGGER lacks IF NOT EXISTS)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_memories_updated'
    ) THEN
        CREATE TRIGGER trg_memories_updated
            BEFORE UPDATE ON memories
            FOR EACH ROW
            EXECUTE FUNCTION update_memories_timestamp();
    END IF;
END;
$$;

COMMENT ON FUNCTION update_memories_timestamp() IS 'Auto-updates memories.updated_at on row modification';


-- =============================================================================
-- End of Phase 1 Schema Migration
-- =============================================================================
