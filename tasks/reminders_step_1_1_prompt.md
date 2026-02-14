# Dream Team Task: Create Reminders Database Migration

## Task Overview
Create the Supabase database migration for the `reminders` table. This is Step 1.1 of the Reminder System Development Plan.

## Context
We are building a hybrid reminder system for the Sabine Super Agent that supports:
- **SMS reminders** (standalone, via Twilio)
- **Calendar event reminders** (via Google Calendar API)

This migration creates the foundational database table to persist reminders.

---

## Requirements

### Functional Requirements
1. Store reminder records with unique UUID primary keys
2. Support one-time and recurring reminders (daily, weekly, monthly, yearly)
3. Track active vs completed reminders
4. Support multiple notification channels (SMS, email, Slack)
5. Store flexible metadata for custom context
6. Integrate with existing user system (foreign key to users table)

### Technical Requirements
1. Follow existing schema patterns from `supabase/schema.sql`
2. Use TIMESTAMPTZ for all datetime fields (timezone-aware)
3. Include auto-update trigger for `updated_at`
4. Add appropriate indexes for common query patterns
5. Enable Row Level Security (RLS)
6. Use proper CHECK constraints for enums

---

## Deliverables

### File to Create
`supabase/migrations/20260202100000_create_reminders_table.sql`

### Table Schema

```sql
-- Table: reminders
CREATE TABLE IF NOT EXISTS reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Core reminder data
    title TEXT NOT NULL,
    description TEXT,

    -- Type and scheduling
    reminder_type TEXT NOT NULL DEFAULT 'sms'
        CHECK (reminder_type IN ('sms', 'email', 'slack', 'calendar_event')),
    scheduled_time TIMESTAMPTZ NOT NULL,

    -- Recurrence (null = one-time)
    repeat_pattern TEXT
        CHECK (repeat_pattern IS NULL OR repeat_pattern IN ('daily', 'weekly', 'monthly', 'yearly')),

    -- Status tracking
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_completed BOOLEAN NOT NULL DEFAULT FALSE,
    last_triggered_at TIMESTAMPTZ,

    -- Multi-channel notification config
    notification_channels JSONB NOT NULL DEFAULT '{"sms": true}',

    -- Flexible metadata (tags, context, scheduler job ID, etc.)
    metadata JSONB NOT NULL DEFAULT '{}',

    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### Required Indexes

```sql
-- Fast lookup of active reminders for a user, ordered by scheduled time
CREATE INDEX idx_reminders_user_active_scheduled
    ON reminders(user_id, scheduled_time)
    WHERE is_active = TRUE;

-- Fast lookup of reminders due to fire (for scheduler polling)
CREATE INDEX idx_reminders_scheduled_active
    ON reminders(scheduled_time)
    WHERE is_active = TRUE AND is_completed = FALSE;

-- Metadata queries (JSONB GIN index)
CREATE INDEX idx_reminders_metadata
    ON reminders USING gin(metadata);
```

### Required Triggers

```sql
-- Auto-update updated_at on modification
CREATE TRIGGER update_reminders_updated_at
    BEFORE UPDATE ON reminders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

### Required RLS

```sql
-- Enable Row Level Security
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;

-- Service role has full access (matches existing pattern)
-- Note: Additional policies can be added for user-level access if needed
```

### Required Comments

```sql
COMMENT ON TABLE reminders IS 'Scheduled reminders with support for SMS, email, Slack, and calendar notifications';
COMMENT ON COLUMN reminders.reminder_type IS 'Notification type: sms, email, slack, or calendar_event';
COMMENT ON COLUMN reminders.repeat_pattern IS 'Recurrence pattern: null (one-time), daily, weekly, monthly, yearly';
COMMENT ON COLUMN reminders.notification_channels IS 'JSON config for which channels to notify (e.g., {"sms": true, "slack": true})';
COMMENT ON COLUMN reminders.metadata IS 'Flexible metadata (scheduler job ID, tags, custom context)';
COMMENT ON COLUMN reminders.last_triggered_at IS 'When this reminder was last fired (for recurring reminders)';
```

---

## Acceptance Criteria

### Must Pass
- [ ] Migration file is syntactically valid SQL
- [ ] Table name is `reminders`
- [ ] All columns match the schema above
- [ ] Foreign key constraint exists to `users(id)` with ON DELETE CASCADE
- [ ] CHECK constraints enforce valid values for `reminder_type` and `repeat_pattern`
- [ ] TIMESTAMPTZ is used for all datetime columns
- [ ] Default values are set appropriately
- [ ] Indexes are created for efficient queries
- [ ] `update_updated_at_column()` trigger is attached
- [ ] RLS is enabled
- [ ] Comments are added

### Code Quality
- [ ] Follows existing migration file naming convention: `YYYYMMDDHHMMSS_description.sql`
- [ ] Includes header comment explaining the migration purpose
- [ ] Uses `IF NOT EXISTS` for idempotent creation
- [ ] Consistent formatting with existing migrations

---

## Reference Files

Study these files to understand existing patterns:

1. **Schema patterns**: `supabase/schema.sql` (lines 1-331)
   - Table structure, constraints, triggers, RLS

2. **Migration example**: `supabase/migrations/20260201000000_create_task_queue.sql`
   - File naming, header comments, trigger creation

3. **Development plan**: `docs/plans/reminder-system-plan.md`
   - Full BDD specification for Step 1.1

---

## Verification Steps

After creating the migration, verify:

1. **Syntax check**: Run `psql -f migration.sql` (or use Supabase SQL editor)
2. **Insert test**: Can insert a reminder record
3. **Query test**: Can query by user_id and scheduled_time
4. **Update test**: `updated_at` auto-updates on modification
5. **Constraint test**: Invalid `reminder_type` values are rejected

---

## Notes

- Do NOT modify existing tables or migrations
- Do NOT add seed data (separate concern)
- Do NOT create functions beyond what's specified (trigger uses existing `update_updated_at_column()`)
- The migration should be runnable multiple times without error (idempotent via `IF NOT EXISTS`)
