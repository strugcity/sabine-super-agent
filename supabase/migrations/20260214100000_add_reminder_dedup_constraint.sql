-- =============================================================================
-- DEBT-002: Reminder Deduplication - Unique Constraint Migration
-- =============================================================================
-- Prevents duplicate active reminders with the same title and recurrence
-- pattern for a given user. This addresses the bug where 9 copies of
-- "Send weekly baseball YouTube video" were all firing at once.
--
-- Strategy: Partial unique index on (user_id, title, repeat_pattern)
-- filtered to only active, non-completed reminders.
--
-- Backward-compatible: This is an additive index; no existing data is modified.
-- If duplicates exist, run the cleanup migration first.
-- =============================================================================

-- Step 1: Clean up existing duplicates before adding constraint.
-- For each group of duplicate active reminders (same user_id, title,
-- repeat_pattern), keep the newest one and deactivate the rest.
WITH ranked_reminders AS (
    SELECT
        id,
        user_id,
        title,
        repeat_pattern,
        ROW_NUMBER() OVER (
            PARTITION BY user_id, title, repeat_pattern
            ORDER BY created_at DESC
        ) AS rn
    FROM reminders
    WHERE is_active = true AND is_completed = false
)
UPDATE reminders
SET is_active = false,
    metadata = jsonb_set(
        COALESCE(metadata, '{}'),
        '{dedup_deactivated_at}',
        to_jsonb(NOW()::text)
    )
WHERE id IN (
    SELECT id FROM ranked_reminders WHERE rn > 1
);

-- Step 2: Create the partial unique index for deduplication.
-- Only one active reminder per (user_id, title, repeat_pattern) is allowed.
-- NULL repeat_pattern values are treated as equal by this index because
-- we COALESCE them to a sentinel value.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reminders_dedup
ON reminders (user_id, title, COALESCE(repeat_pattern, '__one_time__'))
WHERE is_active = true AND is_completed = false;

-- Add a comment explaining the index
COMMENT ON INDEX idx_reminders_dedup IS
    'DEBT-002: Prevents duplicate active reminders with same title and recurrence pattern per user';
