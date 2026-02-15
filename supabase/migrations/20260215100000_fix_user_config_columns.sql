-- =============================================================================
-- Fix user_config column name mismatch (DEBT-004 reconciliation)
-- =============================================================================
-- Production was bootstrapped from schema.sql which used key/value columns.
-- All backend code (lib/db/user_config.py) uses config_key/config_value.
-- This migration renames the columns to match what the code expects.
--
-- PostgreSQL RENAME COLUMN automatically updates constraints and indexes
-- that reference the old column name.
-- =============================================================================

ALTER TABLE user_config RENAME COLUMN key TO config_key;
ALTER TABLE user_config RENAME COLUMN value TO config_value;

-- Ensure composite index exists for (user_id, config_key) lookups
CREATE INDEX IF NOT EXISTS idx_user_config_user_key
    ON user_config(user_id, config_key);
