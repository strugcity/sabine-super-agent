-- Phase 3: Autonomous Skill Acquisition Tables
-- PRD Requirements: SKILL-001 through SKILL-011

-- ============================================================
-- skill_gaps: detected capability gaps from tool audit logs
-- ============================================================
CREATE TABLE IF NOT EXISTS skill_gaps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    gap_type TEXT NOT NULL CHECK (gap_type IN ('repeated_failure', 'edit_heavy', 'missing_tool')),
    tool_name TEXT,
    pattern_description TEXT NOT NULL,
    occurrence_count INT NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'researching', 'proposed', 'resolved', 'dismissed')),
    resolved_by_skill UUID,  -- FK added after skill_versions exists
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_skill_gaps_user_status ON skill_gaps(user_id, status);
CREATE INDEX IF NOT EXISTS idx_skill_gaps_tool_name ON skill_gaps(tool_name);

-- ============================================================
-- skill_proposals: generated skill proposals awaiting approval
-- ============================================================
CREATE TABLE IF NOT EXISTS skill_proposals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    gap_id UUID REFERENCES skill_gaps(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    description TEXT NOT NULL,
    manifest_json JSONB NOT NULL,
    handler_code TEXT NOT NULL,
    test_results JSONB,
    sandbox_passed BOOLEAN NOT NULL DEFAULT false,
    roi_estimate TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'promoted')),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_skill_proposals_user_status ON skill_proposals(user_id, status);

-- ============================================================
-- skill_versions: promoted skills with version tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS skill_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id UUID REFERENCES skill_proposals(id) ON DELETE SET NULL,
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    skill_name TEXT NOT NULL,
    version TEXT NOT NULL DEFAULT '1.0.0',
    manifest_json JSONB NOT NULL,
    handler_code TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT true,
    promoted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, skill_name, version)
);

CREATE INDEX IF NOT EXISTS idx_skill_versions_user_active ON skill_versions(user_id, skill_name, is_active);

-- Add FK from skill_gaps.resolved_by_skill -> skill_versions.id
ALTER TABLE skill_gaps ADD CONSTRAINT fk_skill_gaps_resolved_by
    FOREIGN KEY (resolved_by_skill) REFERENCES skill_versions(id) ON DELETE SET NULL;
