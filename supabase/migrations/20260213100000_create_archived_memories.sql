-- =============================================================================
-- Migration: Create archived_memories table for cold storage (MEM-003)
-- Date: 2026-02-13
-- =============================================================================
-- This migration creates the cold storage table for archived memories:
--
-- 1. archived_memories table with summary + original content
-- 2. Performance indexes for retrieval
-- 3. RLS policies matching existing patterns
--
-- Depends on:
--   - 20260129170000_init_context_engine.sql  (memories table)
--   - 20260213_phase1_schema.sql              (salience columns on memories)
--
-- Owner: @backend-architect-sabine
-- PRD Reference: MEM-003 (Cold Storage Table)
-- ADR Reference: ADR-004 (Cold Storage Format)
-- =============================================================================


-- -----------------------------------------------------------------------------
-- 1. CREATE TABLE archived_memories
-- -----------------------------------------------------------------------------
-- Stores the full content and a Haiku-generated summary (stub for now)
-- of memories that have been archived due to low salience.
--
-- The summary_embedding allows semantic search over archived memories
-- without loading the full original_content.

CREATE TABLE IF NOT EXISTS archived_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Reference to the original memory (may still exist in memories table
    -- with is_archived=true, or may have been hard-deleted in future phases)
    original_memory_id UUID NOT NULL,

    -- User scoping
    user_id UUID NOT NULL,

    -- Haiku-generated summary (stub text for now)
    summary TEXT NOT NULL DEFAULT 'Archived memory - summary pending generation',

    -- Vector embedding of the summary for semantic search (1536 dims for ada-002)
    summary_embedding vector(1536),

    -- Original memory content preserved verbatim
    original_content TEXT NOT NULL,

    -- Original memory metadata preserved as JSONB
    metadata JSONB DEFAULT '{}',

    -- Archival metadata
    archived_at TIMESTAMPTZ DEFAULT now() NOT NULL,
    archived_reason TEXT DEFAULT 'low_salience',

    -- Salience score at time of archival (for reference)
    salience_at_archival FLOAT DEFAULT 0.0
        CHECK (salience_at_archival >= 0.0 AND salience_at_archival <= 1.0)
);


-- -----------------------------------------------------------------------------
-- 2. INDEXES for archived_memories
-- -----------------------------------------------------------------------------

-- Primary retrieval: most recently archived first
CREATE INDEX IF NOT EXISTS idx_archived_memories_archived_at
    ON archived_memories (archived_at DESC);

-- User-scoped queries: "show me my archived memories"
CREATE INDEX IF NOT EXISTS idx_archived_memories_user_id
    ON archived_memories (user_id);

-- Lookup by original memory ID (for promote/restore operations)
CREATE INDEX IF NOT EXISTS idx_archived_memories_original_memory_id
    ON archived_memories (original_memory_id);

-- User + time composite for paginated user queries
CREATE INDEX IF NOT EXISTS idx_archived_memories_user_archived
    ON archived_memories (user_id, archived_at DESC);


-- -----------------------------------------------------------------------------
-- 3. COMMENTS
-- -----------------------------------------------------------------------------

COMMENT ON TABLE archived_memories IS 'Cold storage for low-salience memories with summaries and preserved original content';
COMMENT ON COLUMN archived_memories.original_memory_id IS 'UUID of the original memory in the memories table';
COMMENT ON COLUMN archived_memories.summary IS 'Haiku-generated summary of the archived memory (stub for Phase 1)';
COMMENT ON COLUMN archived_memories.summary_embedding IS 'Vector embedding of the summary for semantic search (1536 dims)';
COMMENT ON COLUMN archived_memories.original_content IS 'Original memory content preserved verbatim for potential restoration';
COMMENT ON COLUMN archived_memories.archived_reason IS 'Reason for archival: low_salience, manual, expired, etc.';
COMMENT ON COLUMN archived_memories.salience_at_archival IS 'Salience score at the time the memory was archived';


-- -----------------------------------------------------------------------------
-- 4. RLS POLICIES
-- -----------------------------------------------------------------------------
-- Following existing patterns: service_role has full access,
-- authenticated users can read their own archived memories.

ALTER TABLE archived_memories ENABLE ROW LEVEL SECURITY;

-- Service role: full access (used by backend worker jobs)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'archived_memories'
          AND policyname = 'archived_memories_service_role_all'
    ) THEN
        CREATE POLICY archived_memories_service_role_all
            ON archived_memories
            FOR ALL
            TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END;
$$;

-- Authenticated users: read own archived memories
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'archived_memories'
          AND policyname = 'archived_memories_auth_select_own'
    ) THEN
        CREATE POLICY archived_memories_auth_select_own
            ON archived_memories
            FOR SELECT
            TO authenticated
            USING (user_id = auth.uid());
    END IF;
END;
$$;


-- -----------------------------------------------------------------------------
-- 5. updated_at trigger (for future updates to archived records)
-- -----------------------------------------------------------------------------

-- Reuse the existing update_memories_timestamp function if available,
-- otherwise create a generic one for this table.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_archived_memories_updated'
    ) THEN
        CREATE TRIGGER trg_archived_memories_updated
            BEFORE UPDATE ON archived_memories
            FOR EACH ROW
            EXECUTE FUNCTION update_memories_timestamp();
    END IF;
END;
$$;


-- =============================================================================
-- End of archived_memories migration
-- =============================================================================
