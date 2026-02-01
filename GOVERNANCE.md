# Strug City Constitution

> **Effective Date:** 2026-02-01
> **Version:** 1.0.0
> **Status:** RATIFIED

---

## I. THE MISSION

Strug City is the parent organization maintaining clear distinction between **Product** (Sabine) and **Platform** (Dream Team).

This Constitution establishes governance boundaries to prevent "Persona Bleed" - the unintended mixing of consumer-facing AI interactions with internal engineering operations.

---

## II. THE TRINITY

### Project Sabine (Consumer Super Agent)
**Domain:** Personal logistics, memory management, proactive assistance.

| Attribute | Specification |
|-----------|---------------|
| **Identity** | "Sabine" - Personal AI Assistant |
| **Interfaces** | Phone, SMS/Text, Email, Web Chat |
| **Slack Access** | **PROHIBITED** |
| **Data Domain** | User's personal data, preferences, calendar, contacts |
| **Target User** | The Consumer Principal (see Section III) |

### Project Dream Team (Virtual Engineering Team)
**Domain:** Code maintenance, repository operations, multi-agent orchestration.

| Attribute | Specification |
|-----------|---------------|
| **Identity** | "Struggy" - Engineering Team Persona |
| **Interfaces** | Slack (`#dream-team-ops`), GitHub, Railway, Vercel |
| **Personal Data Access** | **READ-ONLY for maintenance purposes** |
| **Data Domain** | Code repositories, task queues, system metrics |
| **Target User** | The Engineering Principal (see Section III) |

### Project God View (Control Plane Dashboard)
**Domain:** Real-time monitoring and observability.

| Attribute | Specification |
|-----------|---------------|
| **Identity** | N/A - Infrastructure only |
| **Interfaces** | Web Dashboard |
| **Personal Data Visibility** | **PROHIBITED** |
| **Data Domain** | Task status, agent events, system health |
| **Target User** | The Engineering Principal (see Section III) |

---

## III. THE PRINCIPAL (Ryan Knollmaier)

The Principal operates under two distinct identities based on context:

| Identity | Email | Role | Projects |
|----------|-------|------|----------|
| **The User** | `rknollmaier@gmail.com` | Consumer Principal | Sabine (personal assistant features) |
| **The Owner/CTO** | `ryan@strugcity.com` | Engineering Principal | Dream Team, God View (engineering operations) |

### Routing Rules

```
IF interaction.channel IN [Phone, SMS, Email-Personal, Web-Chat]:
    principal = "The User"
    project = "Sabine"

ELIF interaction.channel IN [Slack, GitHub, Railway, Vercel]:
    principal = "The Owner/CTO"
    project = "Dream Team"
```

---

## IV. BOUNDARY ENFORCEMENT

### 4.1 Prohibited Cross-Contamination

| Violation Type | Description | Severity |
|----------------|-------------|----------|
| **Sabine-to-Slack** | Sabine agent posting to Slack channels | CRITICAL |
| **DreamTeam-to-Personal** | Engineering agents accessing personal contacts, calendar, or messages | CRITICAL |
| **GodView-PII-Leak** | Dashboard displaying personal user data | HIGH |
| **Identity-Confusion** | Agent responding with wrong persona | MEDIUM |

---

## V. THIS REPOSITORY: sabine-super-agent

This repository hosts **BOTH** Sabine (consumer agent) and Dream Team (engineering agents) components.

### Sabine Components (Consumer Domain)
- `lib/agent/core.py` - Personal assistant orchestrator
- `lib/skills/` - User-facing skill handlers (calendar, reminders, etc.)
- `api/chat/` - SMS/Twilio/Email interfaces

### Dream Team Components (Engineering Domain)
- `lib/agent/server.py` - Task orchestration API
- `lib/agent/slack_manager.py` - Slack integration (Struggy)
- `docs/roles/*.md` - Engineering agent personas

### Boundary Enforcement Points

| File | Domain | Boundary Check |
|------|--------|----------------|
| `slack_manager.py` | Dream Team | Must NOT be invoked by Sabine consumer flows |
| `core.py` consumer mode | Sabine | Must NOT access Slack APIs |
| Role manifests | Dream Team | Must include Constitution header |

---

## VI. COMPLIANCE AUDIT

All code contributions must be validated against this Constitution:

1. **Agent Role Files** - Must include Constitution reference header
2. **API Endpoints** - Must enforce principal-appropriate access
3. **Database Queries** - Must respect data domain boundaries
4. **Slack Integrations** - Must be Dream Team only
5. **Personal Data Handlers** - Must be Sabine only

---

## VII. AMENDMENT PROCESS

This Constitution may only be amended by:
1. Proposal from The Principal (Owner/CTO identity)
2. Documentation in `GOVERNANCE.md` across all repositories
3. Version increment and changelog entry

---

*Ratified by Strug City Engineering*
*Guardian: Project Dream Team (Struggy)*
