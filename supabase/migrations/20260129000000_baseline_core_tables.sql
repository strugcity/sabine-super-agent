-- =============================================================================
-- Baseline Core Tables Migration
-- =============================================================================
-- Captures the 8 core tables originally defined in schema.sql so that
-- fresh deploys from migrations alone produce a complete schema.
--
-- All statements use IF NOT EXISTS / CREATE OR REPLACE guards so this
-- migration is a no-op on databases already bootstrapped from schema.sql.
--
-- Depends on: nothing (this is the first migration)
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- 1. users
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin', 'family_member')),
    name TEXT,
    timezone TEXT DEFAULT 'America/New_York',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'Core user accounts for the Personal Super Agent';

-- -----------------------------------------------------------------------------
-- 2. user_identities
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('twilio', 'email', 'slack', 'web')),
    identifier TEXT NOT NULL,
    is_primary BOOLEAN DEFAULT FALSE,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_provider_identifier UNIQUE (provider, identifier)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_provider_identifier
    ON user_identities(provider, identifier);
CREATE INDEX IF NOT EXISTS idx_user_identities_user_id
    ON user_identities(user_id);

-- -----------------------------------------------------------------------------
-- 3. user_config
-- -----------------------------------------------------------------------------
-- Uses config_key/config_value column names (matching backend code).
-- Production was bootstrapped with key/value; Blocker 4 migration renames them.
CREATE TABLE IF NOT EXISTS user_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    config_key TEXT NOT NULL,
    config_value TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_user_config_key UNIQUE (user_id, config_key)
);

CREATE INDEX IF NOT EXISTS idx_user_config_user_id
    ON user_config(user_id);

-- -----------------------------------------------------------------------------
-- 4. memories
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    source TEXT,
    importance_score FLOAT DEFAULT 0.5 CHECK (importance_score >= 0 AND importance_score <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_memories_user_id
    ON memories(user_id);
CREATE INDEX IF NOT EXISTS idx_memories_metadata
    ON memories USING gin(metadata);
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories(created_at DESC);

-- -----------------------------------------------------------------------------
-- 5. rules
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    trigger_condition JSONB NOT NULL,
    action_logic JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0,
    execution_count INTEGER DEFAULT 0,
    last_executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rules_active
    ON rules(is_active, priority DESC);
CREATE INDEX IF NOT EXISTS idx_rules_user_id
    ON rules(user_id);

-- -----------------------------------------------------------------------------
-- 6. conversation_state
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    state JSONB NOT NULL DEFAULT '{}',
    context JSONB DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'error', 'abandoned')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,
    CONSTRAINT unique_active_session UNIQUE (user_id, channel, session_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_state_active
    ON conversation_state(user_id, status, last_activity_at DESC)
    WHERE status = 'active';
CREATE INDEX IF NOT EXISTS idx_conversation_state_session
    ON conversation_state(session_id);

-- -----------------------------------------------------------------------------
-- 7. custody_schedule
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS custody_schedule (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_name TEXT NOT NULL,
    parent_with_custody TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    pickup_time TIME,
    dropoff_time TIME,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT valid_date_range CHECK (end_date >= start_date)
);

CREATE INDEX IF NOT EXISTS idx_custody_schedule_dates
    ON custody_schedule(user_id, start_date, end_date);

-- -----------------------------------------------------------------------------
-- 8. conversation_history
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS conversation_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_state_id UUID REFERENCES conversation_state(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversation_history_state
    ON conversation_history(conversation_state_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_history_user
    ON conversation_history(user_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- Row Level Security
-- -----------------------------------------------------------------------------
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE custody_schedule ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_history ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------------
-- Shared updated_at trigger function
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- -----------------------------------------------------------------------------
-- Triggers (idempotent via DO blocks)
-- -----------------------------------------------------------------------------
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_users_updated_at') THEN
        CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END; $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_user_identities_updated_at') THEN
        CREATE TRIGGER update_user_identities_updated_at BEFORE UPDATE ON user_identities
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END; $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_user_config_updated_at') THEN
        CREATE TRIGGER update_user_config_updated_at BEFORE UPDATE ON user_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END; $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_memories_updated_at') THEN
        CREATE TRIGGER update_memories_updated_at BEFORE UPDATE ON memories
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END; $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_rules_updated_at') THEN
        CREATE TRIGGER update_rules_updated_at BEFORE UPDATE ON rules
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END; $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_custody_schedule_updated_at') THEN
        CREATE TRIGGER update_custody_schedule_updated_at BEFORE UPDATE ON custody_schedule
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END; $$;

-- =============================================================================
-- End of Baseline Core Tables Migration
-- =============================================================================
