-- =============================================================================
-- DEBT-004: User Configuration Table
-- =============================================================================
-- Creates a key-value configuration store for per-user settings.
-- Initial use case: phone_number for SMS reminder delivery.
--
-- Future use cases: notification preferences, timezone overrides,
-- email preferences, etc.
--
-- Backward-compatible: This is a new table; no existing data is affected.
-- =============================================================================

-- Create the user_config table
CREATE TABLE IF NOT EXISTS user_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL,
    config_key TEXT NOT NULL,
    config_value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, config_key)
);

-- Fast lookup by user_id
CREATE INDEX IF NOT EXISTS idx_user_config_user_id
    ON user_config(user_id);

-- Fast lookup by user_id + config_key (covered by UNIQUE constraint,
-- but explicit index for clarity)
CREATE INDEX IF NOT EXISTS idx_user_config_user_key
    ON user_config(user_id, config_key);

-- Auto-update updated_at on modification
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_user_config_updated_at'
    ) THEN
        CREATE TRIGGER update_user_config_updated_at
            BEFORE UPDATE ON user_config
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    END IF;
END;
$$;

-- Enable Row Level Security
ALTER TABLE user_config ENABLE ROW LEVEL SECURITY;

-- Table and column comments
COMMENT ON TABLE user_config IS 'DEBT-004: Per-user key-value configuration store (phone number, preferences, etc.)';
COMMENT ON COLUMN user_config.config_key IS 'Configuration key (e.g., phone_number, timezone, notification_pref)';
COMMENT ON COLUMN user_config.config_value IS 'Configuration value as text (caller is responsible for type conversion)';
