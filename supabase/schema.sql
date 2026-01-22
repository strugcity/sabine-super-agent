-- =============================================================================
-- Personal Super Agent V1 - Database Schema
-- =============================================================================
-- This schema implements the "Dual-Brain Memory" architecture:
-- - Vector Store: Fuzzy semantic search (memories table with pgvector)
-- - Knowledge Graph: Strict relational logic (users, rules, config, etc.)
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Extensions
-- -----------------------------------------------------------------------------

-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Enable pgvector for embeddings (CRITICAL: Must be enabled first)
CREATE EXTENSION IF NOT EXISTS vector;

-- -----------------------------------------------------------------------------
-- Core Users Table
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin', 'family_member')),
    name TEXT,
    timezone TEXT DEFAULT 'America/New_York',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE users IS 'Core user accounts for the Personal Super Agent';
COMMENT ON COLUMN users.role IS 'User role: user, admin, or family_member';
COMMENT ON COLUMN users.timezone IS 'User timezone for schedule-aware responses';

-- -----------------------------------------------------------------------------
-- User Identities (Multi-Channel)
-- -----------------------------------------------------------------------------
-- Decouples users from single communication channels
-- Supports Twilio, Email, Slack, etc.

CREATE TABLE IF NOT EXISTS user_identities (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('twilio', 'email', 'slack', 'web')),
    identifier TEXT NOT NULL, -- Phone number, email, Slack user ID, etc.
    is_primary BOOLEAN DEFAULT FALSE,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Ensure one identity per provider+identifier combination
    CONSTRAINT unique_provider_identifier UNIQUE (provider, identifier)
);

COMMENT ON TABLE user_identities IS 'Multi-channel identities (phone, email, Slack) linked to users';
COMMENT ON COLUMN user_identities.provider IS 'Identity provider: twilio, email, slack, or web';
COMMENT ON COLUMN user_identities.identifier IS 'The actual identifier (phone number, email, etc.)';
COMMENT ON COLUMN user_identities.is_primary IS 'Primary contact method for this user';

-- Index for fast lookups by provider and identifier
CREATE INDEX IF NOT EXISTS idx_user_identities_provider_identifier
    ON user_identities(provider, identifier);

-- Index for finding all identities for a user
CREATE INDEX IF NOT EXISTS idx_user_identities_user_id
    ON user_identities(user_id);

-- -----------------------------------------------------------------------------
-- User Configuration (Settings)
-- -----------------------------------------------------------------------------
-- Key-value store for user preferences and settings

CREATE TABLE IF NOT EXISTS user_config (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One setting per user per key
    CONSTRAINT unique_user_config_key UNIQUE (user_id, key)
);

COMMENT ON TABLE user_config IS 'User settings and preferences (calendar_id, briefing_time, etc.)';
COMMENT ON COLUMN user_config.key IS 'Setting key (e.g., calendar_id, briefing_time, preferred_voice)';
COMMENT ON COLUMN user_config.value IS 'Setting value (stored as text, parse as needed)';

-- Index for fast config lookups
CREATE INDEX IF NOT EXISTS idx_user_config_user_id
    ON user_config(user_id);

-- -----------------------------------------------------------------------------
-- Memories (Vector Store) - Dual-Brain Memory Part 1
-- -----------------------------------------------------------------------------
-- Stores fuzzy notes, observations, and semantic memories
-- Uses pgvector for similarity search

CREATE TABLE IF NOT EXISTS memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    embedding vector(1536), -- OpenAI text-embedding-3-small dimension
    metadata JSONB DEFAULT '{}',
    source TEXT, -- 'conversation', 'manual', 'system', etc.
    importance_score FLOAT DEFAULT 0.5 CHECK (importance_score >= 0 AND importance_score <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE memories IS 'Vector store for semantic memory (fuzzy notes and observations)';
COMMENT ON COLUMN memories.embedding IS 'Vector embedding for semantic similarity search';
COMMENT ON COLUMN memories.metadata IS 'Additional context (tags, entities, dates, etc.)';
COMMENT ON COLUMN memories.importance_score IS 'Memory importance (0-1) for retrieval ranking';

-- Index for vector similarity search (using cosine distance)
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Index for user-specific memory queries
CREATE INDEX IF NOT EXISTS idx_memories_user_id
    ON memories(user_id);

-- Index for metadata queries
CREATE INDEX IF NOT EXISTS idx_memories_metadata
    ON memories USING gin(metadata);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_memories_created_at
    ON memories(created_at DESC);

-- -----------------------------------------------------------------------------
-- Rules (Logic Engine) - Dual-Brain Memory Part 2
-- -----------------------------------------------------------------------------
-- Stores deterministic rules and triggers
-- Part of the "Knowledge Graph" for strict logic

CREATE TABLE IF NOT EXISTS rules (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    trigger_condition JSONB NOT NULL, -- Condition that activates this rule
    action_logic JSONB NOT NULL, -- Action to take when triggered
    is_active BOOLEAN DEFAULT TRUE,
    priority INTEGER DEFAULT 0, -- Higher priority rules execute first
    execution_count INTEGER DEFAULT 0,
    last_executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE rules IS 'Deterministic rules and triggers for the agent (Knowledge Graph)';
COMMENT ON COLUMN rules.trigger_condition IS 'JSON condition (e.g., {"type": "time", "value": "08:00"})';
COMMENT ON COLUMN rules.action_logic IS 'JSON action (e.g., {"type": "send_briefing", "template": "morning"})';
COMMENT ON COLUMN rules.priority IS 'Execution priority (higher = earlier)';

-- Index for active rules lookup
CREATE INDEX IF NOT EXISTS idx_rules_active
    ON rules(is_active, priority DESC);

-- Index for user-specific rules
CREATE INDEX IF NOT EXISTS idx_rules_user_id
    ON rules(user_id);

-- -----------------------------------------------------------------------------
-- Conversation State
-- -----------------------------------------------------------------------------
-- Tracks ongoing conversations and agent state

CREATE TABLE IF NOT EXISTS conversation_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL, -- 'twilio_voice', 'twilio_sms', 'web', etc.
    state JSONB NOT NULL DEFAULT '{}', -- LangGraph state snapshot
    context JSONB DEFAULT '{}', -- Deep context loaded for this conversation
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'completed', 'error', 'abandoned')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at TIMESTAMPTZ,

    -- Ensure unique active sessions per user+channel
    CONSTRAINT unique_active_session UNIQUE (user_id, channel, session_id)
);

COMMENT ON TABLE conversation_state IS 'Tracks active conversations and LangGraph state';
COMMENT ON COLUMN conversation_state.state IS 'LangGraph state machine snapshot';
COMMENT ON COLUMN conversation_state.context IS 'Deep context (rules, custody state) injected into this session';
COMMENT ON COLUMN conversation_state.session_id IS 'Unique session identifier (e.g., Twilio CallSid)';

-- Index for active conversation lookups
CREATE INDEX IF NOT EXISTS idx_conversation_state_active
    ON conversation_state(user_id, status, last_activity_at DESC)
    WHERE status = 'active';

-- Index for session lookups
CREATE INDEX IF NOT EXISTS idx_conversation_state_session
    ON conversation_state(session_id);

-- -----------------------------------------------------------------------------
-- Custody Schedule (Knowledge Graph) - Family Logistics
-- -----------------------------------------------------------------------------
-- Strict relational data for custody schedules
-- Part of the "Deep Context" system

CREATE TABLE IF NOT EXISTS custody_schedule (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    child_name TEXT NOT NULL,
    parent_with_custody TEXT NOT NULL, -- 'mom', 'dad', 'both', etc.
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    pickup_time TIME,
    dropoff_time TIME,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Ensure end_date is after start_date
    CONSTRAINT valid_date_range CHECK (end_date >= start_date)
);

COMMENT ON TABLE custody_schedule IS 'Custody schedule (Knowledge Graph for family logistics)';
COMMENT ON COLUMN custody_schedule.parent_with_custody IS 'Which parent has custody during this period';

-- Index for date range queries
CREATE INDEX IF NOT EXISTS idx_custody_schedule_dates
    ON custody_schedule(user_id, start_date, end_date);

-- Index for finding current custody (removed CURRENT_DATE predicate - not immutable)
-- The date range index above (idx_custody_schedule_dates) will handle these queries efficiently
-- CREATE INDEX IF NOT EXISTS idx_custody_schedule_active
--     ON custody_schedule(user_id, start_date, end_date)
--     WHERE start_date <= CURRENT_DATE AND end_date >= CURRENT_DATE;

-- -----------------------------------------------------------------------------
-- Conversation History (Audit Trail)
-- -----------------------------------------------------------------------------
-- Stores full conversation history for debugging and analysis

CREATE TABLE IF NOT EXISTS conversation_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_state_id UUID REFERENCES conversation_state(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}', -- Tool calls, function results, etc.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE conversation_history IS 'Full conversation history for audit and analysis';
COMMENT ON COLUMN conversation_history.role IS 'Message role: user, assistant, system, or tool';

-- Index for conversation lookups
CREATE INDEX IF NOT EXISTS idx_conversation_history_state
    ON conversation_history(conversation_state_id, created_at);

-- Index for user history
CREATE INDEX IF NOT EXISTS idx_conversation_history_user
    ON conversation_history(user_id, created_at DESC);

-- -----------------------------------------------------------------------------
-- Row Level Security (RLS) Policies
-- -----------------------------------------------------------------------------
-- Enable RLS for multi-tenant security

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_config ENABLE ROW LEVEL SECURITY;
ALTER TABLE memories ENABLE ROW LEVEL SECURITY;
ALTER TABLE rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE custody_schedule ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_history ENABLE ROW LEVEL SECURITY;

-- Service role has full access (for server-side operations)
-- Note: In production, you'll want more granular policies based on auth.uid()

-- -----------------------------------------------------------------------------
-- Functions and Triggers
-- -----------------------------------------------------------------------------

-- Function to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply updated_at trigger to relevant tables
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_identities_updated_at BEFORE UPDATE ON user_identities
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_user_config_updated_at BEFORE UPDATE ON user_config
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_memories_updated_at BEFORE UPDATE ON memories
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_rules_updated_at BEFORE UPDATE ON rules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_custody_schedule_updated_at BEFORE UPDATE ON custody_schedule
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- -----------------------------------------------------------------------------
-- Seed Data (Optional - for development)
-- -----------------------------------------------------------------------------

-- Example admin user (you can customize or remove this)
-- INSERT INTO users (id, role, name, timezone) VALUES
--     (uuid_generate_v4(), 'admin', 'Admin User', 'America/New_York');

-- =============================================================================
-- Schema Setup Complete!
-- =============================================================================
-- Next Steps:
-- 1. Run this SQL in Supabase SQL Editor or via psql
-- 2. Create a service role API key in Supabase settings
-- 3. Update .env with SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
-- 4. Implement the agent's Deep Context injection system
-- =============================================================================
