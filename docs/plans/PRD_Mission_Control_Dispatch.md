# PRD: Strug City Mission Control (Dispatch GUI)

**Target System:** Project God View (`dream-team-strug.vercel.app`)
**Backend:** Project Dream Team (`sabine-super-agent-production.up.railway.app`)
**Owner:** Ryan Knollmaier (CTO)
**Status:** DRAFT
**Last Updated:** February 4, 2026

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Objectives](#3-goals--objectives)
4. [Current State Analysis](#4-current-state-analysis)
5. [Functional Requirements](#5-functional-requirements)
6. [Technical Specifications](#6-technical-specifications)
7. [UI/UX Design](#7-uiux-design)
8. [Implementation Roadmap](#8-implementation-roadmap)
9. [Appendices](#9-appendices)

---

## 1. Executive Summary

Currently, injecting tasks into the Dream Team agent ecosystem requires either:
1. Manual CLI execution of Python scripts (`trigger_dispatch.py`)
2. Direct Postman/cURL requests with proper JSON payloads

The **Mission Control** module adds a "New Mission" form to the existing God View dashboard, allowing the CTO to create, validate, and inject mission directives into the task queue through a structured UI—replacing terminal commands with form-based dispatch.

### What Already Exists (No Build Required)
- ✅ Real-time task monitoring dashboard
- ✅ Task dispatch trigger button (dispatches next queued task)
- ✅ Task approval workflow
- ✅ Live event stream
- ✅ Orchestration status metrics
- ✅ `useTaskActions` hook with `createTask()` method

### What Needs to Be Built
- ❌ **Mission Injection Form** (create new tasks with full payload)
- ❌ **Role/Repo Dropdowns** (fetched from `/roles` and `/repos` APIs)
- ❌ **JSON Preview Panel** (validate payload before submission)
- ❌ **Dry Run Validation** (client-side schema validation)

---

## 2. Problem Statement

| Issue | Impact |
|-------|--------|
| **Friction** | Dispatching tasks requires writing JSON and using CLI/Postman |
| **Validation Gap** | No pre-flight validation—typos in role/repo cause 403/400 errors |
| **Context Switching** | Must leave dashboard to inject new work |
| **Payload Complexity** | `target_repo` is mandatory but easy to forget |

---

## 3. Goals & Objectives

| Goal | Success Metric |
|------|----------------|
| **Zero-Code Dispatch** | CTO can create tasks without terminal access |
| **Pre-Submit Validation** | 100% of validation errors caught before API call |
| **Constitutional Compliance** | Role-repo authorization enforced via dropdown constraints |
| **Reduced Errors** | Zero "Invalid role" or "Invalid repo" API errors |

---

## 4. Current State Analysis

### 4.1 Backend API (Project Dream Team)

**Base URL:** `https://sabine-super-agent-production.up.railway.app`

**Authentication:** `X-API-Key` header (env: `AGENT_API_KEY`)

**Relevant Endpoints:**

| Endpoint | Method | Purpose | Auth Required |
|----------|--------|---------|---------------|
| `/tasks` | POST | Create new task | Yes |
| `/tasks/dispatch` | POST | Dispatch next unblocked task | Yes |
| `/tasks/{task_id}` | GET | Get task details | Yes |
| `/roles` | GET | List available agent roles | No |
| `/repos` | GET | List valid repos + authorization matrix | No |
| `/orchestration/status` | GET | Get queue metrics | Yes |

**Create Task Request Schema:**
```typescript
interface CreateTaskRequest {
  role: string;           // Required: Agent role ID (e.g., "backend-architect-sabine")
  target_repo: string;    // Required: Repository identifier (e.g., "sabine-super-agent")
  payload: {
    message?: string;     // Task instructions (can also use "objective" or "instructions")
    objective?: string;   // Alternative field for instructions
    [key: string]: any;   // Additional context
  };
  depends_on?: string[];  // Optional: Array of parent task UUIDs
  priority?: number;      // Optional: Higher = processed first (default: 0)
}
```

**Create Task Response:**
```typescript
interface CreateTaskResponse {
  success: boolean;
  task_id: string;
  role: string;
  target_repo: string;
  status: "queued";
  message: string;
}
```

### 4.2 Role-Repository Authorization Matrix

**From `server.py` line 548-560:**

| Role | Authorized Repos | Domain |
|------|------------------|--------|
| `backend-architect-sabine` | `sabine-super-agent` | Python backend, agent logic |
| `data-ai-engineer-sabine` | `sabine-super-agent` | AI systems, data pipelines |
| `SABINE_ARCHITECT` | `sabine-super-agent` | Senior orchestrator |
| `frontend-ops-sabine` | `dream-team-strug` | Next.js dashboard |
| `product-manager-sabine` | Both repos | Cross-functional PM |
| `qa-security-sabine` | Both repos | Security & QA |

**Valid Repositories:**

| Identifier | GitHub |
|------------|--------|
| `sabine-super-agent` | `strugcity/sabine-super-agent` |
| `dream-team-strug` | `strugcity/dream-team-strug` |

### 4.3 Frontend State (Project God View)

**Existing Hook:** `src/hooks/useTaskActions.ts`

```typescript
// Already implemented:
createTask(task: {
  role: string;
  payload: Record<string, unknown>;
  priority?: number;
  depends_on?: string[];
  created_by?: string;
  session_id?: string;
}): Promise<ApiResponse<{ task_id: string }>>
```

**Missing Field:** The existing `createTask` does NOT include `target_repo` in its type definition. This must be added.

**Environment Variables (already configured):**
```
NEXT_PUBLIC_API_URL=https://sabine-super-agent-production.up.railway.app
NEXT_PUBLIC_API_KEY=<stored in Vercel>
NEXT_PUBLIC_SUPABASE_URL=<supabase project url>
NEXT_PUBLIC_SUPABASE_ANON_KEY=<supabase anon key>
```

---

## 5. Functional Requirements

### 5.1 Mission Injection Form

**Location:** New tab "Mission Control" or modal accessible from dashboard header

**Form Fields:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| Mission Name | Text input | Yes | Min 3 chars |
| Target Repository | Dropdown | Yes | Fetched from `/repos` API |
| Agent Role | Dropdown | Yes | Filtered by selected repo authorization |
| Objective | Textarea (markdown) | Yes | Min 10 chars |
| Priority | Number selector (1-10) | No | Default: 5 |
| Dependencies | Multi-select (task IDs) | No | Must be valid UUIDs |

**Dynamic Filtering:**
When user selects `target_repo`, the Role dropdown filters to show only authorized roles:
- `sabine-super-agent` → backend-architect, data-ai-engineer, SABINE_ARCHITECT, product-manager, qa-security
- `dream-team-strug` → frontend-ops, product-manager, qa-security

### 5.2 JSON Preview Panel

**Purpose:** Show the exact payload that will be sent to the API

**Features:**
- Real-time preview as user fills form
- Syntax highlighting
- Copy-to-clipboard button
- Shows `_repo_context` injection (read-only, system-generated)

### 5.3 Submission Actions

| Action | Behavior |
|--------|----------|
| **Validate** | Client-side schema check + role-repo authorization check |
| **Dispatch** | POST to `/tasks`, show success/failure toast |

### 5.4 Response Feedback

| Status | UI Response |
|--------|-------------|
| 201 Created | Green toast: "Mission {task_id} queued for {role}" + Link to task in Task Board |
| 400 Bad Request | Red alert: Show specific validation error from API |
| 403 Forbidden | Red alert: "Role not authorized for this repository" |
| 424 Failed Dependency | Orange alert: Show failed parent task ID |
| 500 Server Error | Red alert: "System error - check backend logs" |

---

## 6. Technical Specifications

### 6.1 Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  dream-team-strug.vercel.app (Next.js 14)                   │
│                                                              │
│  ┌──────────────────┐     ┌─────────────────────────────┐   │
│  │  Mission Form    │────▶│  useTaskActions Hook        │   │
│  │  (Client)        │     │  (API abstraction)          │   │
│  └──────────────────┘     └─────────────────────────────┘   │
│           │                           │                      │
│           │                           ▼                      │
│  ┌────────▼─────────┐     ┌─────────────────────────────┐   │
│  │  JSON Preview    │     │  fetch() with X-API-Key     │   │
│  │  (Read-only)     │     │  header                     │   │
│  └──────────────────┘     └─────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│  sabine-super-agent-production.up.railway.app (FastAPI)     │
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐   │
│  │ POST /tasks  │──▶│ Validation   │──▶│  Supabase      │   │
│  │              │   │ + Auth Check │   │  task_queue    │   │
│  └──────────────┘   └──────────────┘   └────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────┐
│  Supabase (PostgreSQL)                                       │
│                                                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  task_queue table                                      │  │
│  │  - id (UUID)                                           │  │
│  │  - role (TEXT)                                         │  │
│  │  - status (TEXT): queued → in_progress → completed     │  │
│  │  - payload (JSONB)                                     │  │
│  │  - depends_on (UUID[])                                 │  │
│  │  - priority (INT)                                      │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Required Code Changes

#### 6.2.1 Update `useTaskActions.ts`

**File:** `src/hooks/useTaskActions.ts`

**Change:** Add `target_repo` to `createTask` interface

```typescript
const createTask = useCallback(async (task: {
  role: string;
  target_repo: string;  // ADD THIS
  payload: Record<string, unknown>;
  priority?: number;
  depends_on?: string[];
  created_by?: string;
  session_id?: string;
}): Promise<ApiResponse<{ task_id: string }>> => {
  setError(null);
  return apiRequest<{ task_id: string }>('/tasks', {
    method: 'POST',
    body: JSON.stringify(task),
  });
}, [apiRequest]);
```

#### 6.2.2 Add Role/Repo Fetching Hooks

**New File:** `src/hooks/useRoleRepoConfig.ts`

```typescript
'use client';

import { useState, useEffect } from 'react';

interface Role {
  role_id: string;
  title: string;
  allowed_tools: string | string[];
  model_preference: string | null;
}

interface RepoConfig {
  valid_repos: Record<string, { owner: string; repo: string }>;
  role_authorization: Record<string, string[]>;
}

export function useRoleRepoConfig() {
  const [roles, setRoles] = useState<Role[]>([]);
  const [repoConfig, setRepoConfig] = useState<RepoConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchConfig = async () => {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

      const [rolesRes, reposRes] = await Promise.all([
        fetch(`${API_BASE}/roles`),
        fetch(`${API_BASE}/repos`),
      ]);

      const rolesData = await rolesRes.json();
      const reposData = await reposRes.json();

      setRoles(rolesData.roles || []);
      setRepoConfig({
        valid_repos: reposData.valid_repos,
        role_authorization: reposData.role_authorization,
      });
      setIsLoading(false);
    };

    fetchConfig();
  }, []);

  // Get roles authorized for a specific repo
  const getRolesForRepo = (repoId: string): Role[] => {
    if (!repoConfig) return [];

    return roles.filter((role) => {
      const authorizedRepos = repoConfig.role_authorization[role.role_id];
      return authorizedRepos?.includes(repoId);
    });
  };

  return { roles, repoConfig, isLoading, getRolesForRepo };
}
```

#### 6.2.3 New Component: MissionForm

**New File:** `src/components/MissionForm.tsx`

Key features:
- Controlled form with React Hook Form
- Dynamic role filtering based on repo selection
- Real-time JSON preview
- Validation before submission
- Toast notifications on success/error

### 6.3 Technology Stack Alignment

| Aspect | Current Stack | Recommendation |
|--------|---------------|----------------|
| Framework | Next.js 14.2.21 | No change |
| Styling | Tailwind CSS 3.4 | No change |
| Form State | None (useState) | **Add: React Hook Form** |
| API State | Custom hooks | No change |
| Icons | Lucide React | No change |
| Validation | None | **Add: Zod** |
| Toast Notifications | None | **Add: Sonner or react-hot-toast** |

### 6.4 Environment Variables

**No new environment variables required.** All needed vars already exist:
- `NEXT_PUBLIC_API_URL` - Backend base URL
- `NEXT_PUBLIC_API_KEY` - API authentication key

---

## 7. UI/UX Design

### 7.1 Layout Options

**Option A: New Tab**
Add "Mission Control" as 4th tab alongside Overview, Task Board, Event Stream

**Option B: Modal**
"+ New Mission" button in header opens full-screen modal

**Recommendation:** Option A (New Tab) for dedicated workspace feel

### 7.2 Wireframe Concept

```
┌────────────────────────────────────────────────────────────────────┐
│  ⚡ Mission Control                                    [Dispatch All]│
├────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─ CREATE MISSION ─────────────────┐  ┌─ PAYLOAD PREVIEW ────────┐│
│  │                                   │  │                          ││
│  │  Mission Name                     │  │  {                       ││
│  │  ┌─────────────────────────────┐  │  │    "role": "backend-...",││
│  │  │ Operation Dark Mode         │  │  │    "target_repo": "sab.."││
│  │  └─────────────────────────────┘  │  │    "payload": {          ││
│  │                                   │  │      "message": "..."    ││
│  │  Target Repository                │  │    },                    ││
│  │  ┌─────────────────────────────┐  │  │    "priority": 5         ││
│  │  │ sabine-super-agent        ▼ │  │  │  }                       ││
│  │  └─────────────────────────────┘  │  │                          ││
│  │                                   │  └──────────────────────────┘│
│  │  Agent Role                       │                              │
│  │  ┌─────────────────────────────┐  │  ┌─ RECENT MISSIONS ────────┐│
│  │  │ backend-architect-sabine  ▼ │  │  │                          ││
│  │  └─────────────────────────────┘  │  │  ✓ Task abc123 - queued  ││
│  │                                   │  │  ✓ Task def456 - queued  ││
│  │  Objective                        │  │  ✗ Task ghi789 - failed  ││
│  │  ┌─────────────────────────────┐  │  │                          ││
│  │  │ Implement the dark mode    │  │  └──────────────────────────┘│
│  │  │ toggle using the existing  │  │                              │
│  │  │ Tailwind config...         │  │                              │
│  │  └─────────────────────────────┘  │                              │
│  │                                   │                              │
│  │  Priority: [5] ───────○──────    │                              │
│  │                                   │                              │
│  │  [Validate]          [🚀 Dispatch]│                              │
│  └───────────────────────────────────┘                              │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

### 7.3 Color & Style Alignment

Use existing God View theme:
- Background: `gantry-dark` (#0a0a0f)
- Cards: `gantry-card` (#111118)
- Borders: `gantry-border` (#1e1e2e)
- Accent: Role-based colors (purple for architect, blue for backend, etc.)
- Font: JetBrains Mono for code/preview areas

---

## 8. Implementation Roadmap

### Phase 1: MVP (1-2 days)

**Goal:** Basic form that creates tasks

| Task | Complexity | Dependencies |
|------|------------|--------------|
| Update `useTaskActions.ts` to include `target_repo` | Low | None |
| Create `useRoleRepoConfig.ts` hook | Low | None |
| Create basic `MissionForm.tsx` component | Medium | Above hooks |
| Add "Mission Control" tab to main page | Low | MissionForm |
| Add success/error toast notifications | Low | Sonner package |

**Exit Criteria:**
- [ ] Can create task via form
- [ ] Role dropdown filters by repo
- [ ] Success toast shows task ID

### Phase 2: Polish (1 day)

**Goal:** Better UX and validation

| Task | Complexity | Dependencies |
|------|------------|--------------|
| Add Zod schema validation | Low | zod package |
| Add JSON preview panel | Medium | None |
| Add "Recent Missions" history (session-only) | Low | useState |
| Validate button (dry run without submit) | Low | Zod schema |

**Exit Criteria:**
- [ ] JSON preview updates in real-time
- [ ] Validation errors shown inline
- [ ] Last 5 dispatched tasks shown in sidebar

### Phase 3: Advanced Features (Future)

**Goal:** Power user features

| Task | Complexity | Dependencies |
|------|------------|--------------|
| Dependency picker (select from existing tasks) | High | Task list API |
| Mission templates (save/load common patterns) | Medium | localStorage |
| Bulk import from JSON file | Medium | File upload |

---

## 9. Appendices

### 9.1 Example API Requests

**Create a backend task:**
```bash
curl -X POST "https://sabine-super-agent-production.up.railway.app/tasks" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "backend-architect-sabine",
    "target_repo": "sabine-super-agent",
    "payload": {
      "message": "Implement the new caching layer for memory retrieval"
    },
    "priority": 7
  }'
```

**Create a frontend task:**
```bash
curl -X POST "https://sabine-super-agent-production.up.railway.app/tasks" \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "role": "frontend-ops-sabine",
    "target_repo": "dream-team-strug",
    "payload": {
      "objective": "Add Mission Control tab with task creation form"
    },
    "priority": 8
  }'
```

**Fetch roles:**
```bash
curl "https://sabine-super-agent-production.up.railway.app/roles"
```

**Fetch repo authorization:**
```bash
curl "https://sabine-super-agent-production.up.railway.app/repos"
```

### 9.2 Error Codes Reference

| HTTP Code | Meaning | User-Friendly Message |
|-----------|---------|----------------------|
| 201 | Created | "Mission queued successfully" |
| 400 | Bad Request | Show `detail` from response |
| 401 | Unauthorized | "API key invalid - contact admin" |
| 403 | Forbidden | "Role not authorized for this repository" |
| 424 | Failed Dependency | "Parent task {id} has failed" |
| 500 | Server Error | "System error - check backend logs" |

### 9.3 Differences from Original PRD

| Original PRD | Actual Implementation | Resolution |
|--------------|----------------------|------------|
| Endpoint: `/tasks` | ✅ Correct | No change |
| Auth: `STRUG_CITY_API_KEY` | ❌ Actual: `AGENT_API_KEY` (header: `X-API-Key`) | Use correct env var name |
| Payload field: `"name"` | ❌ Not used | Remove from form |
| Payload field: `"project"` | ❌ Actual: `"target_repo"` | Use correct field |
| Payload field: `"status": "queued"` | ❌ Auto-set by backend | Remove from payload |
| Dropdown fetched from DB | ❌ Fetched from `/roles` and `/repos` APIs | Use API endpoints |
| `"agent_id"` field | ❌ Not in schema | Remove |
| `"Objective"` field | ✅ Goes in `payload.message` or `payload.objective` | Correct |
| Form at `/dispatch` route | ⚠️ Recommendation: Add as tab in existing dashboard | Use tab approach |

### 9.4 File Locations Summary

**Backend (sabine-super-agent):**
- API Server: `lib/agent/server.py`
- Task Queue Service: `backend/services/task_queue.py`
- Role Manifests: `docs/roles/*.md`

**Frontend (dream-team-strug):**
- Main Dashboard: `src/app/page.tsx`
- Task Actions Hook: `src/hooks/useTaskActions.ts`
- Supabase Client: `src/lib/supabase.ts`
- Components: `src/components/`

---

*End of Document*
