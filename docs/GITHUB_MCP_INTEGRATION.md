# GitHub MCP Integration for Sabine 2.0

**Purpose:** Integrate GitHub MCP connector into Sabine 2.0 development workflow
**Status:** Integration strategy (ready for implementation)
**Last Updated:** February 13, 2026

---

## Overview

The GitHub MCP connector provides direct access to GitHub resources (repos, PRs, issues, workflows) without context switching. This complements your existing Gemini-powered GitHub Actions workflows.

**When to use GitHub MCP:**
- Local development (pre-commit PR review, branch validation)
- Interactive PR creation from Claude Code
- Issue/branch management during development
- Cross-repo dependency tracking

**When to use existing GitHub Actions:**
- Post-commit automation (tests, builds, deployments)
- Cross-org orchestration (Gemini dispatch workflows)
- Scheduled tasks (content generation, cleanup)

---

## Integration Points for Sabine 2.0

### Phase 0: ADR Commits

**When ADRs complete (tonight/tomorrow):**
```bash
# GitHub MCP: Create feature branch for ADR commits
git checkout -b phase-0/adr-decisions

# Stage + commit ADRs
git add docs/architecture/ADR-*.md
git commit -m "docs(adr): architecture decisions Phase 0 complete"

# GitHub MCP: Create PR from Claude Code
# gh pr create --title "Phase 0 ADRs: Architecture Decisions" \
#   --body "$(cat <<EOF
# ## ADR Decisions Complete
#
# - ADR-001: Graph Storage → pg_graphql
# - ADR-002: Job Queue → Redis + rq
# - ADR-003: Sandbox → E2B
# - ADR-004: Cold Storage → Compressed Summary
#
# All decisions benchmarked and documented.
# EOF)"
```

### Phase 1: Parallel Stream Execution

**For each of 4 parallel streams (A, B, C, D):**
```bash
# GitHub MCP: Create isolation branches per stream
git checkout -b phase-1/stream-a-database
git checkout -b phase-1/stream-b-redis
git checkout -b phase-1/stream-c-fast-path
git checkout -b phase-1/stream-d-slow-path

# Each stream: frequent commits per task
git add backend/models/memory.py tests/test_schema.py
git commit -m "feat(phase-1-a): add salience_score column to memories table"

# GitHub MCP: Create draft PR per stream (open for review)
# gh pr create --draft --title "Phase 1 Stream A: Database Schema" \
#   --head phase-1/stream-a-database --body "..."
```

### Phase 1-3: Continuous Integration

**GitHub Actions (existing):**
- Pre-commit: ESLint + TypeScript + tests
- Tests: Jest + pytest (on PR)
- Deployment: Vercel (on merge to main)

**GitHub MCP (new - from Claude Code):**
- Interactive PR review: `gh pr review --request-changes` (catch issues early)
- Branch management: Switch between streams without terminal
- Status checks: Verify workflow runs before committing
- Issue linking: Reference ADRs + implementation tasks

---

## Recommended Workflow

### During Development (Claude Code)

**Use GitHub MCP for:**
```bash
# 1. Check PR status before commit
gh pr status

# 2. Create PR early (draft) for async review
gh pr create --draft \
  --title "Phase 1 Stream B: Redis Queue Setup" \
  --body "Initial implementation, WIP on tests"

# 3. Manage branches interactively
gh repo view  # Check repo structure
gh repo clone  # Setup if needed

# 4. Link issues to PRs
gh pr edit <PR#> --add-label "phase-1" --add-label "redis"

# 5. Monitor workflow runs
gh run list  # Check CI/CD status
gh run view <RUN_ID>  # Details
```

**Use GitHub Actions for:**
```yaml
# Existing: .github/workflows/test-sanity.yml
# - Runs on PR + push
# - Tests pass/fail gate for merge

# New (suggested): .github/workflows/sabine-phase-1.yml
# - Runs Sabine 1.0 regression tests
# - Validates backward-compatibility
# - Blocks merge if 1.0 tests fail
```

---

## Integration Strategy

### Before Phase 1 Kickoff

**Create GitHub workflow for backward-compatibility:**
```yaml
# .github/workflows/sabine-v1-regression.yml
name: Sabine 1.0 Regression Tests

on: [pull_request, push]

jobs:
  sabine-v1-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: pytest tests/sabine_v1/ -v
      - name: Fail if 1.0 broken
        if: failure()
        run: echo "Sabine 1.0 regression detected!" && exit 1
```

**Create GitHub MCP shortcuts in CLAUDE.md:**
```markdown
### GitHub MCP Quick Commands

From Claude Code during Sabine 2.0 work:

\`\`\`bash
# Create PR for current branch
gh pr create --draft --title "Phase 1: <stream>" --body "..."

# Check Sabine 1.0 tests passed
gh run list --workflow sabine-v1-regression.yml | head -5

# Link issue to PR
gh pr edit <PR#> --add-label "phase-1"

# Request review (optional, since PR is draft)
gh pr review --request-changes "Needs approval before merge"
\`\`\`
```

---

## GitOps Integration

### For RUBE Automation (Later)

When you deploy RUBE recipe (Phase 1 Week 2), GitHub MCP enables:

```python
# After nightly consolidation completes successfully:
# 1. Create summary issue
gh issue create \
  --title "Sabine 2.0 Consolidation #$(date +%Y%m%d)" \
  --body "✓ WAL: 50 entries processed\n✓ Relationships: 230 extracted\n..."
  --label "sabine-2.0,nightly-run"

# 2. Comment on relevant PRs
gh pr comment <PR#> \
  --body "Phase 1 infrastructure updated: WAL schema validated ✓"

# 3. Update project boards (if using GitHub Projects)
gh project item-list <PROJECT_ID>
```

---

## Phase-by-Phase Usage

### Phase 0 (This Week)
- ✅ Commit ADR decisions (manual, once agents complete)
- ⏳ Create Phase 0 summary PR (optional, for team review)

### Phase 1 (Weeks 1-4)
- ✅ Create 4 draft PRs (one per stream) from Claude Code
- ✅ Frequent commits within each stream
- ✅ Use `gh pr view` to check regression tests pass
- ⏳ Block merge if `sabine-v1-regression` workflow fails

### Phase 2 (Weeks 5-10)
- ✅ Same PR workflow, 4 new streams
- ✅ Cross-reference MAGMA graph PRs in comments
- ✅ Link ADRs to implementation PRs

### Phase 3 (Weeks 11-14)
- ✅ Track skill acquisition PRs
- ⏳ Optional: Create GitHub Projects board for gap tracking

### Phase 4 (Weeks 15-16)
- ✅ Final consolidation PR
- ✅ Release notes (generated from merged PRs)

---

## Security Considerations

**GitHub MCP Permissions:**
- Read-only by default (viewing repos, PRs, issues)
- Write operations: create branches, PRs, comments (within scope)
- Never exposes secrets (GitHub Actions handles credentials)

**For Sabine 2.0:**
- ✓ Safe: Creating PRs, adding labels, viewing workflows
- ✓ Safe: Checking test status, branch management
- ⚠️ Careful: Only merge Phase 1 if `sabine-v1-regression` passes
- ✗ Never: Force push, delete branches, dismiss required reviews

---

## Conflict with Existing Workflows

**Current Gemini workflows (keep):**
- `gemini-dispatch.yml` - Issue triage
- `gemini-review.yml` - Automated code review
- `gemini-content-generator.yml` - Blog content sync
- `strug-blog-sync.yml` - Sanity sync

**GitHub MCP additions (complementary):**
- Interactive branch/PR management from Claude Code
- Early feedback during development (draft PRs)
- Backward-compatibility validation (regression tests)

**No conflicts:** GitHub MCP is local/interactive, Gemini workflows are post-commit/automation.

---

## Quick Start (When Phase 1 Begins)

### Step 1: Create Regression Test Workflow
```bash
# Copy template to .github/workflows/
cp docs/templates/sabine-v1-regression.yml .github/workflows/

# Commit + push
git add .github/workflows/sabine-v1-regression.yml
git commit -m "ci: add Sabine 1.0 regression tests on PR"
git push
```

### Step 2: Create Branch + PR (From Claude Code)
```bash
# When starting Phase 1 Stream A
git checkout -b phase-1/stream-a-database

# Make changes, commit
git add ...
git commit -m "feat(phase-1-a): ..."

# Create draft PR
gh pr create --draft \
  --title "Phase 1 Stream A: Database Schema" \
  --body "Implements salience tracking + archival schema..."
```

### Step 3: Monitor Regression Tests
```bash
# Before pushing/merging, verify Sabine 1.0 tests pass
gh run list --workflow sabine-v1-regression.yml

# If status is "failure", investigate before merge
gh run view <RUN_ID>
```

---

## Recommended Updates to CLAUDE.md

Add to "Development Workflow" section:

```markdown
### GitHub MCP Connector (Local)

**Use during Phase 1+ implementation:**
- Create draft PRs per stream from Claude Code
- Check regression tests pass before merge
- Link issues/labels interactively
- View PR status without terminal

**Key commands:**
\`\`\`bash
gh pr create --draft --title "Phase 1: <stream>"
gh pr status
gh pr view <PR#>
gh run list --workflow sabine-v1-regression.yml
\`\`\`

**Complements existing GitHub Actions:**
- GitHub Actions: post-commit automation (tests, deploys)
- GitHub MCP: interactive management during dev
- No conflicts, both enabled simultaneously
```

---

## Summary

**GitHub MCP for Sabine 2.0:**
- ✅ Enables interactive PR management from Claude Code
- ✅ Supports parallel stream execution (4 branches active simultaneously)
- ✅ Integrates with existing GitHub Actions (regression tests)
- ✅ Helps enforce backward-compatibility (blocks merge on 1.0 failures)
- ✅ No conflicts with Gemini automation workflows

**Integration timing:**
- Phase 0 (now): Manual commits + optional PR creation
- Phase 1+ (weeks 1-14): Heavy use (4 active PRs, frequent commits)
- Phase 4 (weeks 15-16): Final consolidation + release

**Recommendation:** Enable GitHub Actions regression test workflow (Phase 1 Week 0), then use GitHub MCP from Claude Code starting Phase 1 Week 1.

---

**Last Updated:** 2026-02-13 | **Status:** Ready for Phase 1 Integration
