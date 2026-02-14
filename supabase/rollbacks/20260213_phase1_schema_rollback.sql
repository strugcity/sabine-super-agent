-- =============================================================================
-- Phase 1 Schema Rollback - Reverts 20260213_phase1_schema.sql
-- =============================================================================
-- Run this migration to revert all Phase 1 schema changes.
--
-- WARNING: This will drop columns and indexes. Any data stored in the
-- dropped columns (salience_score, last_accessed_at, access_count,
-- is_archived) will be permanently lost.
--
-- Order: reverse of the forward migration
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. Remove updated_at trigger on memories
-- -----------------------------------------------------------------------------

DROP TRIGGER IF EXISTS trg_memories_updated ON memories;
DROP FUNCTION IF EXISTS update_memories_timestamp();

-- -----------------------------------------------------------------------------
-- 2. Remove wal_logs user-scoped index
-- -----------------------------------------------------------------------------

DROP INDEX IF EXISTS idx_wal_logs_user_status;

-- -----------------------------------------------------------------------------
-- 3. Remove memory lifecycle indexes
-- -----------------------------------------------------------------------------

DROP INDEX IF EXISTS idx_memories_archival_candidates;
DROP INDEX IF EXISTS idx_memories_last_accessed_at;
DROP INDEX IF EXISTS idx_memories_active_salience;
DROP INDEX IF EXISTS idx_memories_salience_score;

-- -----------------------------------------------------------------------------
-- 4. Remove memory lifecycle columns
-- -----------------------------------------------------------------------------

ALTER TABLE memories DROP COLUMN IF EXISTS is_archived;
ALTER TABLE memories DROP COLUMN IF EXISTS access_count;
ALTER TABLE memories DROP COLUMN IF EXISTS last_accessed_at;
ALTER TABLE memories DROP COLUMN IF EXISTS salience_score;

-- =============================================================================
-- End of Phase 1 Schema Rollback
-- =============================================================================
