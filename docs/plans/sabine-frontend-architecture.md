# Sabine 2.0 Frontend Architecture Plan

**Status:** DRAFT
**Date:** 2026-02-17
**Owner:** Frontend Architecture
**Backend Ref:** 85+ FastAPI endpoints across 11 routers
**Existing Frontend:** Next.js 15.1.6 / React 19 / Tailwind / ~1,330 LOC

---

## 0. Napkin Draft Review: What Works, What Doesn't

### What Works

1. **"Glass Box" Philosophy.** Correct instinct. The backend already emits SSE streams (`/invoke/stream`), tool audit logs (`/audit/tools`), WAL entries (`/wal/*`), and detailed metrics (`/metrics/*`). The frontend should expose this machinery, not hide it. This is the right north star.

2. **Dual-Pane Chat Concept.** A response pane + debug substrate is the right pattern for a power-user AI interface. The backend streaming endpoint already separates `ack`, `thinking`, `response`, and `error` event types -- this maps cleanly to a dual-pane renderer.

3. **Memory Management UI.** The backend has full memory lifecycle APIs: ingest, query, upload, archive, promote, salience weight tuning, archive configuration. A management interface is needed and the API surface is ready for it.

4. **Dark Mode Aesthetic.** Already implemented via `next-themes` with CSS custom properties. The foundation is there.

### What Doesn't Work

1. **Tech Stack is Wrong.**
   - The draft says "Next.js 14+". We are on **Next.js 15.1.6 with React 19**. This is not cosmetic -- React 19 gives us `use()`, Server Actions, and improved Suspense that change how we architect data fetching. Do not downgrade.
   - **Zustand is premature.** The existing app uses React 19 Server Components + Server Actions for data mutations with `revalidatePath()`. For the chat interface specifically, `useReducer` + React Context is sufficient. Adding a state management library for its own sake adds dependency surface without solving a real problem. If we hit a wall where prop drilling across 4+ levels becomes painful, we add Zustand surgically -- not upfront.
   - **React Flow is heavy** (~200KB gzipped). For Phase 1, the Dream Team task board needs a status-based card grid, not a full DAG editor. React Flow can be a Phase 3 addition when we build interactive agent graph editing.
   - **shadcn/ui is the right call** but was not justified properly. The real reason: we have 8 components today with zero shared primitives (no Button, no Input, no Dialog). Every component reinvents styling. shadcn/ui gives us copy-pasted, ownable primitives that use Radix + Tailwind. No runtime dependency, no version lock-in.

2. **The Draft Ignores What Already Exists.**
   - There is a production Memory Dashboard with entity CRUD, file upload, and memory management. The plan should extend it, not replace it.
   - There is a separate production frontend (`dream-team-strug` on Vercel) that already has task monitoring, dispatch, and event streaming for Dream Team. We should NOT rebuild that here. The two frontends serve different purposes.
   - The Overview page has mock task data. This needs to be connected to real APIs, not redesigned.

3. **Features Imagined That Do Not Exist in the Backend.**
   - "Intervention Mode / Pause Button" for mid-execution agent control: **No backend support.** There is no endpoint to pause a running agent. The Dream Team task queue supports `cancel` on *queued* tasks, not interrupt on *running* ones.
   - "Vector Space Visualizer" (2D/3D memory map): **No backend support.** The `/memory/query` endpoint returns formatted context, not raw embeddings. Building a t-SNE/UMAP projection requires a new backend endpoint to export raw vectors, plus a WebGL renderer. This is a Phase 4 nice-to-have, not an architecture pillar.
   - "Manual Tool Trigger" sandbox: **Partially exists.** There is `/e2b/test` and the skill prototyping pipeline, but no generic "run any tool with arbitrary input" endpoint. This would require backend work.

4. **Features That Exist in the Backend But Were Missed.**
   - **Salience Weight Configuration** (`GET/PUT /api/settings/salience`): User-configurable memory weights (recency, frequency, emotional, causal). Ready for a settings UI today.
   - **Archive Configuration** (`GET/PUT /api/archive/config`, `POST /api/archive/trigger`, `GET /api/archive/stats`): Archive thresholds, manual trigger, statistics. Ready for UI.
   - **Entity Relationship Graph / MAGMA** (`/api/graph/*`): Multi-hop traversal, causal traces, entity networks. This is the *actual* knowledge graph visualizer the draft was reaching for.
   - **Skills Pipeline** (`/api/skills/*`): Gap detection, proposals with approve/reject workflow, skill inventory with disable/rollback. This is a complete autonomous learning dashboard waiting to be built.
   - **WAL Monitoring** (`/wal/stats`, `/wal/pending`, `/wal/failed`): Fast Path health observability.
   - **Queue Health** (`/api/queue/*`): Redis job queue monitoring.
   - **Scheduler Status** (`/scheduler/status`, `/scheduler/trigger-briefing`): Job scheduling visibility.
   - **Cache Metrics** (`/cache/metrics`): Prompt cache hit rates and token savings.
   - **Tool Diagnostics** (`/tools`, `/tools/diagnostics`): MCP server health.

5. **"Neural Stream" and "Brain Surgeon" Are Marketing Names, Not Architecture.**
   Call things what they are: Chat Interface, Debug Panel, Memory Table, Salience Controls. Jargon in a technical plan creates ambiguity. Save the branding for the UI copy.

6. **No Information Architecture.**
   The draft lists features but does not define: How does the user navigate? What is the URL structure? What is primary vs. secondary? What loads on first visit? Without IA, you get a feature soup that confuses users.

---

## 1. Information Architecture

### Design Principle: Hub-and-Spoke

Sabine is a **personal** AI agent. The primary interaction is conversation. Everything else -- memory, settings, observability -- supports that conversation. The IA reflects this: Chat is the hub, everything else is a spoke.

### URL Structure

```
/                           -> Redirect to /chat
/chat                       -> Primary conversation interface
/chat/[session_id]          -> Specific conversation session
/memory                     -> Memory dashboard (existing, enhanced)
/memory/graph               -> Entity relationship explorer (MAGMA)
/skills                     -> Skill lifecycle management
/settings                   -> User preferences and system configuration
/observability              -> System health and metrics
/observability/tasks        -> Dream Team task monitoring
```

### Navigation: Persistent Sidebar

```
+------+---------------------------------------------+
|      |                                             |
| Chat |           Main Content Area                 |
|      |                                             |
| Mem  |                                             |
|      |                                             |
|Skills|                                             |
|      |                                             |
| Obs  |                                             |
|      |                                             |
| Set  |                                             |
|      |                                             |
+------+---------------------------------------------+
```

- Collapsed by default (icon-only, 64px wide)
- Expands on hover to show labels (200px)
- Bottom-pinned: Settings + System Health indicator (green/yellow/red dot from `/health`)
- Mobile: Bottom tab bar with top 4 items

---

## 2. Tech Stack (Grounded)

### Keep (Already Working)

| Tech | Version | Why |
|------|---------|-----|
| Next.js | 15.1.6 | App Router, Server Components, Server Actions |
| React | 19.0.0 | `use()`, improved Suspense, Server Components |
| Tailwind CSS | 3.4.17 | Utility-first, already configured with dark mode |
| next-themes | 0.4.4 | Dark mode toggle, system preference detection |
| @supabase/ssr | 0.8.0 | Server-side Supabase access for direct DB queries |
| lucide-react | 0.469.0 | Icon library, tree-shakeable |
| TypeScript | 5.0 | Strict mode, full type safety |

### Add (Required)

| Tech | Purpose | Justification |
|------|---------|---------------|
| shadcn/ui | UI primitives (Button, Input, Dialog, Tabs, etc.) | Eliminates ad-hoc styling. Radix-based accessibility. Copy-paste ownership, no runtime dep. |
| class-variance-authority | Component variant management | Required by shadcn/ui. Tiny (~1KB). |
| clsx + tailwind-merge | Conditional class composition | Required by shadcn/ui `cn()` utility. |
| Zod | Schema validation for forms and API responses | Type-safe validation, integrates with Server Actions. |
| nuqs | URL search param state management | Type-safe URL state for filters, tabs, pagination without client state libraries. |

### Add Later (Phase 2+)

| Tech | Purpose | When |
|------|---------|------|
| recharts | Metrics visualization | Phase 2: Observability dashboard |
| @tanstack/react-table | Sortable/filterable data tables | Phase 2: Memory table, audit logs |
| react-flow | Agent graph visualization | Phase 3: MAGMA explorer |
| cmdk | Command palette (Cmd+K) | Phase 2: Power-user navigation |

### Explicitly NOT Adding

| Tech | Why Not |
|------|---------|
| Zustand/Redux | React 19 Server Components + Server Actions + `useReducer` covers our needs. The chat interface is the only complex client state, and a `useReducer` with SSE event dispatch handles it cleanly. |
| Framer Motion | Tailwind CSS `transition-*` utilities + CSS `@keyframes` cover our animation needs. No 30KB library for fade-ins. |
| React Query / SWR | Server Components handle data fetching. Client-side polling (for metrics) uses `useEffect` + `setInterval` with a custom hook. We do not have enough client-side fetching to justify a caching library. |
| Socket.io | Backend uses SSE, not WebSockets. SSE is simpler, works with HTTP/2, and the `EventSource` API is native. |

---

## 3. Data Flow Architecture

### Pattern 1: Server Component Data (Read-heavy pages)

```
Browser Request -> Next.js Server Component
                   -> Direct Supabase query (service role key)
                   -> Render HTML
                   -> Stream to client
```

**Used by:** Memory Dashboard, Entity pages, Skill inventory, Archived memories

### Pattern 2: Server Action Mutations (Forms and CRUD)

```
User Action -> Client Component form submit
               -> Server Action (lib file with 'use server')
               -> Supabase mutation OR FastAPI POST
               -> revalidatePath() to refresh SSR cache
               -> Updated UI
```

**Used by:** Entity CRUD, Memory delete, Settings updates, Skill approve/reject

### Pattern 3: API Route Proxy (External webhooks and secure API calls)

```
External Service -> Next.js API Route (/api/*)
                    -> Validate signature/token
                    -> Forward to FastAPI with X-API-Key
                    -> Return response
```

**Used by:** Twilio SMS, Gmail webhook, File upload, Cron jobs

### Pattern 4: SSE Streaming (Chat interface)

```
User sends message -> Client Component
                      -> POST to Next.js API route /api/chat/stream
                      -> API route opens SSE connection to FastAPI /invoke/stream
                      -> Pipe SSE events back to client
                      -> Client useReducer processes events:
                        - 'ack' -> show thinking indicator
                        - 'thinking' -> update debug panel
                        - 'response' -> render message
                        - 'error' -> show error state
                        - 'done' -> finalize
```

### Pattern 5: Polling (Metrics and Health)

```
Client Component mounts
  -> setInterval(fetchMetrics, 30000)  // 30s polling
  -> Update local state
  -> Render charts/indicators
```

**Used by:** System health indicator, Observability metrics, Queue stats

---

## 4. Feature Modules (Detailed)

### Module A: Chat Interface (`/chat`)

**The primary interaction surface. This is what users spend 80% of their time on.**

#### Layout: Response + Debug Panel

```
+-----------+----------------------------------------------+
|           |                                              |
| Today     |  +----------------------------------------+  |
| --------- |  | You: What happened with the Q4 budget? |  |
| Session 1 |  +----------------------------------------+  |
| Session 2 |                                              |
|           |  +----------------------------------------+  |
| Yesterday |  | Sabine: Based on your notes from Dec...|  |
| --------- |  |                                        |  |
| Session 3 |  | [3 sources cited]                      |  |
|           |  +----------------------------------------+  |
|           |                                              |
|           +----------------------------------------------+
|           |  +--------------------------------------+    |
|           |  | Type a message...          [Send >]  |    |
|           |  +--------------------------------------+    |
|           |  [Upload] [Voice]                            |
+-----------+----------------------------------------------+
```

#### Debug Panel (Toggle with keyboard shortcut or button)

Slides in from the right when activated. Shows the internal machinery for the most recent exchange:

```
+-- Debug Panel --------------------------------+
|                                                |
| > Context Retrieved (3 memories)               |
|   - "Q4 budget meeting notes..."               |
|   - "Finance team Slack thread..."             |
|   - Salience: 0.82, 0.71, 0.65                |
|                                                |
| > Entities Extracted                           |
|   - Q4 Budget (project)                        |
|   - Finance Team (org)                         |
|                                                |
| > Tool Calls (2)                               |
|   OK  memory_search (142ms)                    |
|   OK  entity_lookup (38ms)                     |
|                                                |
| > Token Usage                                  |
|   Input: 4,231 | Output: 892                  |
|   Cache: HIT (62% savings)                    |
|   Latency: 3.2s                               |
|                                                |
| > Raw Response JSON                            |
|   { "success": true, ... }                    |
|                                                |
+------------------------------------------------+
```

#### Key Implementation Details

- **SSE Streaming:** Connect to `/invoke/stream` via a Next.js API route proxy (keeps API key server-side). Parse event types (`ack`, `thinking`, `response`, `error`, `done`) with a `useReducer` state machine.
- **Session Management:** Sessions stored in Supabase (existing `session_id` pattern in `/invoke`). Left sidebar lists recent sessions via SSR query.
- **Source Citations:** When the response includes memory references, render them as expandable footnotes linking to the Memory dashboard.
- **File Attachments:** Reuse existing `FileUploader` component for in-chat file sharing (routes to `/memory/upload`).
- **Keyboard Shortcuts:** `Enter` to send, `Shift+Enter` for newline, `Cmd+D` to toggle debug panel, `Cmd+K` for command palette (Phase 2).

#### State Machine for Chat Messages

```typescript
type ChatState = {
  messages: Message[]
  isStreaming: boolean
  debugData: DebugPayload | null
  error: string | null
}

type ChatAction =
  | { type: 'SEND_MESSAGE'; payload: string }
  | { type: 'SSE_ACK' }
  | { type: 'SSE_THINKING'; payload: string }
  | { type: 'SSE_RESPONSE'; payload: string }
  | { type: 'SSE_ERROR'; payload: string }
  | { type: 'SSE_DONE'; payload: DebugPayload }
  | { type: 'CLEAR_ERROR' }
```

---

### Module B: Memory Dashboard (`/memory`)

**Extends the existing Memory Dashboard. Does not replace it.**

#### Current State (Keep)
- Entity cards grouped by domain (work, family, personal, logistics)
- Entity CRUD via Server Actions
- Memory stream with importance scores
- File upload with drag-drop

#### Enhancements

**B1. Memory Table View (New)**

Add a toggle between the existing "stream" view and a new table view:

| Content (truncated) | Salience | Domain | Entity Links | Created | Accessed | Actions |
|---------------------|----------|--------|--------------|---------|----------|---------|
| "Q4 budget meeting..."| 0.82 | work | Budget, Finance | Jan 15 | Feb 12 | Edit / Archive / Delete |

- Sortable columns (salience, date, access count)
- Filterable by domain, date range, salience threshold
- Bulk actions: archive selected, delete selected
- Pagination via URL params (`?page=2&sort=salience&domain=work`)
- Uses `@tanstack/react-table` (Phase 2)

**B2. Archived Memories Panel (New)**

- Tab or section showing archived memories (from `GET /memory/archived`)
- "Promote" button to restore (calls `POST /memory/{id}/promote`)
- Shows archive stats from `GET /api/archive/stats`

**B3. Salience Controls (New)**

A settings card on the memory page:

```
+-- Salience Weights ---------------------------+
|                                                |
|  Recency      [========o====] 0.40            |
|  Frequency    [=====o=======] 0.20            |
|  Emotional    [=====o=======] 0.20            |
|  Causal       [=====o=======] 0.20            |
|                                                |
|  Sum: 1.00                    [Save Changes]  |
|                                                |
+------------------------------------------------+
```

- Fetches from `GET /api/settings/salience`
- Saves via `PUT /api/settings/salience`
- Client-side validation: weights must sum to 1.0
- Shows distribution preview (mini bar chart)

**B4. Archive Configuration (New)**

```
+-- Archive Rules ------------------------------+
|                                                |
|  Salience Threshold    [0.2]                  |
|  Minimum Age (days)    [90 ]                  |
|  Max Access Count      [2  ]                  |
|                                                |
|  [Save]    [Run Archive Now]                  |
|                                                |
|  Last Run: Feb 15, 2026                       |
|  Total Archived: 142 memories                 |
|  Avg Salience of Archived: 0.12              |
|                                                |
+------------------------------------------------+
```

- Fetches config from `GET /api/archive/config`
- Updates via `PUT /api/archive/config`
- Manual trigger via `POST /api/archive/trigger`
- Stats from `GET /api/archive/stats`

---

### Module C: Entity Graph Explorer (`/memory/graph`)

**Visualizes MAGMA -- the multi-graph entity relationship system.**

#### Phase 1: Table + Detail View

Before building a full graph visualization (React Flow), start with what is immediately useful:

**Entity List** (left panel):
- Searchable list of all entities
- Filter by type (person, project, event, location, tool, document)
- Filter by domain (work, family, personal, logistics)

**Entity Detail** (right panel, on entity click):
- Entity attributes (name, type, domain, status, created_at)
- **Relationships tab:** Direct relationships from `GET /api/graph/relationships/{id}`
  - Shows: source -> relationship_type -> target (with confidence scores)
  - Grouped by graph layer (semantic, temporal, causal, entity)
- **Network tab:** Multi-hop network from `GET /api/graph/network/{id}`
  - Renders as a simple adjacency list (Phase 1)
  - Renders as React Flow graph (Phase 3)
- **Causal Trace tab:** From `GET /api/graph/causal-trace/{id}`
  - Shows cause-effect chain as a vertical timeline
- **Linked Memories:** Memories that reference this entity

#### Phase 3: Interactive Graph (Future)

- React Flow canvas showing entity nodes + relationship edges
- Color-coded by graph layer
- Click node to inspect
- Filter by relationship type, confidence threshold
- Traversal depth slider (1-5 hops)
- Requires `GET /api/graph/network/{id}` data transformed to React Flow node/edge format

---

### Module D: Skills Dashboard (`/skills`)

**The autonomous skill acquisition pipeline has a complete API. It needs a UI.**

#### Layout

```
+-- Skills ------------------------------------------------+
|                                                           |
|  [Gaps (3)]  [Proposals (2)]  [Active Skills (8)]        |
|                                                           |
|  +-- Skill Gaps ------------------------------------+    |
|  |                                                   |    |
|  |  ! Parse MSG Email Files                         |    |
|  |    Detected: 3 failures in last 7 days            |    |
|  |    [Dismiss]  [Generate Prototype]                |    |
|  |                                                   |    |
|  |  ! Calendar Timezone Conversion                  |    |
|  |    Detected: User corrected output 5 times        |    |
|  |    [Dismiss]  [Generate Prototype]                |    |
|  |                                                   |    |
|  +---------------------------------------------------+    |
|                                                           |
|  +-- Proposals -------------------------------------+    |
|  |                                                   |    |
|  |  Parse MSG Email Files  v1.0                     |    |
|  |    Dependencies: extract-msg>=0.28.0              |    |
|  |    Test Results: 3/3 passed                       |    |
|  |    Est. ROI: 5x/week, 3 turns -> 1 turn           |    |
|  |                                                   |    |
|  |    [View Code]  [Approve]  [Reject]              |    |
|  |                                                   |    |
|  +---------------------------------------------------+    |
|                                                           |
|  +-- Active Skills ---------------------------------+    |
|  |                                                   |    |
|  |  OK  Web Search          v2.1    [Disable]       |    |
|  |  OK  GitHub Integration  v1.3    [Disable]       |    |
|  |  OK  Email Drafting      v1.0    [Rollback]      |    |
|  |                                                   |    |
|  +---------------------------------------------------+    |
|                                                           |
+-----------------------------------------------------------+
```

#### API Mapping

| UI Action | Endpoint |
|-----------|----------|
| List gaps | `GET /api/skills/gaps` |
| Dismiss gap | `POST /api/skills/gaps/{id}/dismiss` |
| Generate prototype | `POST /api/skills/prototype` |
| List proposals | `GET /api/skills/proposals` |
| Approve proposal | `POST /api/skills/proposals/{id}/approve` |
| Reject proposal | `POST /api/skills/proposals/{id}/reject` |
| List active skills | `GET /api/skills/inventory` |
| Disable skill | `POST /api/skills/{id}/disable` |
| Rollback skill | `POST /api/skills/{name}/rollback` |

---

### Module E: Settings (`/settings`)

**Consolidates all user-configurable parameters.**

#### Sections

1. **Memory Settings**
   - Salience weights (also accessible from Memory dashboard)
   - Archive configuration
   - Open-mindedness parameter (lambda_alpha) -- future, when backend adds endpoint

2. **Notification Preferences**
   - Phone number for SMS (`GET/PUT/DELETE /api/settings/user-config`)
   - Reminder delivery channels
   - Morning briefing toggle

3. **Communication Channels**
   - Gmail status (`GET /gmail/diagnostic`, `GET /gmail/token-health`)
   - SMS status (phone number configured?)
   - Slack status (connection health)

4. **System Information**
   - API version (from `GET /health`)
   - Tools loaded count
   - Database connection status
   - Current model indicator

---

### Module F: Observability (`/observability`)

**System health and operational visibility.**

#### F1. Health Overview

```
+-- System Health ------------------------------------------+
|                                                           |
|  API: OK  Healthy    DB: OK  Connected    Redis: OK  Up  |
|  Tools: 24 loaded   Cache Hit Rate: 62%                  |
|                                                           |
|  +-- Metrics Trend (24h) ---------------------------+    |
|  |  [Line chart: latency, token usage, error rate]   |    |
|  +---------------------------------------------------+    |
|                                                           |
|  +-- Queue Health -+  +-- WAL Status ---------------+    |
|  | Pending: 3      |  | Pending: 12                 |    |
|  | Started: 1      |  | Failed: 0                   |    |
|  | Failed: 0       |  | Consolidated: 1,247         |    |
|  | Workers: 2      |  +-----------------------------+    |
|  +-----------------+                                      |
|                                                           |
|  +-- Scheduler ----------------------------------+       |
|  | Morning Briefing: Next run 6:00 AM CST        |       |
|  | Email Poller: Active                           |       |
|  | Reminder Scheduler: Active                     |       |
|  | [Trigger Briefing Now]                         |       |
|  +------------------------------------------------+       |
|                                                           |
|  +-- Tool Audit Log (Recent 20) -----------------+       |
|  | 14:32 memory_search    OK  142ms              |       |
|  | 14:32 entity_lookup    OK  38ms               |       |
|  | 14:31 web_search       OK  1.2s               |       |
|  | 14:28 gmail_send       ERR auth_error         |       |
|  +------------------------------------------------+       |
|                                                           |
+-----------------------------------------------------------+
```

#### API Mapping

| Widget | Endpoint | Refresh |
|--------|----------|---------|
| System health | `GET /health` | 30s poll |
| Cache metrics | `GET /cache/metrics` | 60s poll |
| Metrics trend | `GET /metrics/trend?hours=24` | 60s poll |
| Latest metrics | `GET /metrics/latest` | 30s poll |
| Queue health | `GET /api/queue/health` | 30s poll |
| Queue stats | `GET /api/queue/stats` | 30s poll |
| WAL stats | `GET /wal/stats` | 30s poll |
| WAL failed | `GET /wal/failed` | Manual |
| Scheduler | `GET /scheduler/status` | 60s poll |
| Trigger briefing | `POST /scheduler/trigger-briefing` | On click |
| Tool audit | `GET /audit/tools?limit=20` | 30s poll |
| Tool stats | `GET /audit/stats` | 60s poll |
| Errors | `GET /metrics/errors` | 60s poll |
| Role metrics | `GET /metrics/roles` | 60s poll |
| MCP diagnostics | `GET /tools/diagnostics` | Manual |

#### F2. Dream Team Tasks (`/observability/tasks`)

**Note:** The full-featured Dream Team dashboard already lives in the `dream-team-strug` repo deployed at `dream-team-strug.vercel.app`. This page provides a lightweight read-only view for quick status checks without switching apps.

- Task list with status filters (queued, in_progress, completed, failed)
- Task detail modal showing payload, dependencies, result
- Links to full Dream Team dashboard for management actions
- Uses `GET /tasks` with query params for filtering

---

## 5. Component Architecture

### Shared Primitives (via shadcn/ui)

Install these first -- they are used everywhere:

```
Button, Input, Textarea, Label, Select,
Dialog, Sheet, Tabs, Card,
Badge, Separator, Skeleton,
DropdownMenu, Tooltip,
Slider, Switch, Toggle
```

### Component Hierarchy

```
src/
  app/
    layout.tsx              (Root: sidebar + theme + health indicator)
    chat/
      layout.tsx            (Chat layout: session sidebar + main area)
      page.tsx              (New chat / redirect to latest session)
      [session_id]/
        page.tsx            (Chat session view)
    memory/
      page.tsx              (Enhanced memory dashboard)
      actions.ts            (Server actions - extended from existing)
      graph/
        page.tsx            (Entity graph explorer)
    skills/
      page.tsx              (Skill lifecycle dashboard)
    settings/
      page.tsx              (User settings)
    observability/
      page.tsx              (System health dashboard)
      tasks/
        page.tsx            (Dream Team task overview)
    api/
      chat/
        route.ts            (Existing: Twilio SMS webhook)
        stream/
          route.ts          (New: SSE proxy to /invoke/stream)
      memory/upload/
        route.ts            (Existing: file upload proxy)
      gmail/webhook/
        route.ts            (Existing: Gmail push notifications)
      cron/gmail-watch/
        route.ts            (Existing: Gmail watch renewal)
  components/
    ui/                     (shadcn/ui primitives)
      button.tsx
      input.tsx
      dialog.tsx
      ... etc
      ModeToggle.tsx        (Existing: dark/light toggle)
      ThemeProvider.tsx      (Existing: next-themes wrapper)
    layout/
      Sidebar.tsx           (New: persistent nav sidebar)
      HealthIndicator.tsx   (New: green/yellow/red system dot)
      CommandPalette.tsx    (Phase 2: Cmd+K search)
    chat/
      ChatMessages.tsx      (Message list with streaming)
      ChatInput.tsx         (Message input with file attach)
      ChatMessage.tsx       (Single message bubble)
      DebugPanel.tsx        (Collapsible right panel)
      SessionList.tsx       (Left sidebar session history)
      SourceCitation.tsx    (Expandable memory reference)
    memory/
      EntityCard.tsx        (Existing: enhanced)
      MemoryStream.tsx      (Existing: enhanced)
      MemoryTable.tsx       (New: table view with sort/filter)
      FileUploader.tsx      (Existing: no changes)
      SalienceControls.tsx  (New: weight sliders)
      ArchiveConfig.tsx     (New: archive settings)
      ArchivedMemories.tsx  (New: archived list with promote)
      NewEntityModal.tsx    (Existing: no changes)
    graph/
      EntityList.tsx        (New: searchable entity list)
      EntityDetail.tsx      (New: attributes + relationships)
      RelationshipTable.tsx (New: relationship list)
      CausalTrace.tsx       (New: cause-effect timeline)
    skills/
      GapList.tsx           (New: detected skill gaps)
      ProposalCard.tsx      (New: skill proposal with approve/reject)
      SkillInventory.tsx    (New: active skills table)
      CodeViewer.tsx        (New: syntax-highlighted code display)
    observability/
      HealthOverview.tsx    (New: system health cards)
      MetricsChart.tsx      (New: time-series chart)
      QueueStatus.tsx       (New: Redis queue stats)
      WalStatus.tsx         (New: WAL health)
      ToolAuditLog.tsx      (New: recent tool executions)
      SchedulerStatus.tsx   (New: job scheduler info)
    settings/
      MemorySettings.tsx    (New: salience + archive config)
      NotificationPrefs.tsx (New: SMS/email/Slack toggles)
      ChannelStatus.tsx     (New: Gmail/SMS/Slack health)
      SystemInfo.tsx        (New: version, tools, DB status)
  lib/
    supabase/
      client.ts             (Existing)
      server.ts             (Existing)
    api/
      client.ts             (New: typed API client for FastAPI backend)
    types/
      database.ts           (Existing: extended with new types)
      chat.ts               (New: message, session, debug types)
      skills.ts             (New: gap, proposal, skill types)
      graph.ts              (New: entity, relationship types)
      observability.ts      (New: metrics, health, audit types)
    hooks/
      use-chat.ts           (New: SSE streaming + state machine)
      use-polling.ts        (New: generic polling hook)
      use-api.ts            (New: typed FastAPI data fetching)
    gmail/
      parser.ts             (Existing)
    utils.ts                (New: cn() helper, formatters)
```

---

## 6. API Client Design

### The Problem

Currently, backend API calls are scattered across individual API routes and components with different patterns. We need a single typed client.

### Solution: Typed API Client

```typescript
// src/lib/api/client.ts
// Server-side only -- uses AGENT_API_KEY from env

class SabineAPI {
  private baseUrl: string
  private apiKey: string

  // Memory
  async queryMemory(query, options?): Promise<MemoryQueryResult>
  async ingestMemory(content, source): Promise<void>
  async getArchivedMemories(limit?, offset?): Promise<Memory[]>
  async promoteMemory(memoryId): Promise<void>

  // Settings
  async getSalienceWeights(): Promise<SalienceWeights>
  async updateSalienceWeights(weights): Promise<void>
  async getArchiveConfig(): Promise<ArchiveConfig>
  async updateArchiveConfig(config): Promise<void>
  async triggerArchive(): Promise<void>
  async getArchiveStats(): Promise<ArchiveStats>

  // Graph
  async getEntityNetwork(entityId, maxDepth?): Promise<EntityNetwork>
  async getEntityRelationships(entityId, direction?): Promise<Relationship[]>
  async getCausalTrace(entityId): Promise<CausalChain>
  async traverseGraph(entityId, options?): Promise<TraversalResult>

  // Skills
  async getSkillGaps(): Promise<SkillGap[]>
  async dismissGap(gapId): Promise<void>
  async getProposals(status?): Promise<SkillProposal[]>
  async approveProposal(proposalId): Promise<void>
  async rejectProposal(proposalId): Promise<void>
  async getSkillInventory(): Promise<Skill[]>
  async disableSkill(skillVersionId): Promise<void>
  async rollbackSkill(skillName): Promise<void>
  async prototypeSkill(description): Promise<void>

  // Observability
  async getHealth(): Promise<HealthStatus>
  async getMetricsTrend(hours?): Promise<MetricsTrend>
  async getLatestMetrics(): Promise<MetricsSnapshot>
  async getQueueHealth(): Promise<QueueHealth>
  async getQueueStats(): Promise<QueueStats>
  async getWalStats(): Promise<WalStats>
  async getWalFailed(): Promise<WalEntry[]>
  async getCacheMetrics(): Promise<CacheMetrics>
  async getToolAudit(limit?): Promise<ToolAuditEntry[]>
  async getSchedulerStatus(): Promise<SchedulerStatus>
  async triggerBriefing(): Promise<void>
  async getToolDiagnostics(): Promise<ToolDiagnostics>

  // Tasks (read-only view for observability)
  async getTasks(filters?): Promise<Task[]>
  async getTaskDetail(taskId): Promise<TaskDetail>
  async getOrchestrationStatus(): Promise<OrchestrationStatus>

  // Chat (streaming)
  async invokeStream(message, sessionId, userId): ReadableStream<SSEEvent>

  // Gmail
  async getGmailDiagnostic(): Promise<GmailDiagnostic>
  async getGmailTokenHealth(): Promise<TokenHealth>
}
```

This client is used by:
- Server Components (direct import)
- Server Actions (direct import)
- API Routes (for streaming proxy)

Never imported from client components -- they go through Server Actions or API routes.

---

## 7. Implementation Phases

### Phase 1: Foundation + Chat (Weeks 1-3)

**Goal:** Functional chat interface + navigation shell + foundational UI system.

**Week 1: Scaffold**
- Install shadcn/ui (`npx shadcn@latest init` + core primitives)
- Create `cn()` utility (`src/lib/utils.ts`)
- Build Sidebar component with nav links
- Build root layout with sidebar integration
- Create HealthIndicator component (polls `GET /health`)
- Restructure routes: move existing memory dashboard from `/dashboard/memory` to `/memory`
- Create `/chat` route with placeholder page
- Create API client (`src/lib/api/client.ts`) with health + metrics methods
- Add TypeScript types for chat, skills, graph, observability

**Week 2: Chat Core**
- Build SSE proxy route (`/api/chat/stream/route.ts`)
- Build `use-chat` hook with `useReducer` state machine
- Build ChatMessages component (message list + auto-scroll)
- Build ChatInput component (textarea + send button + file attach)
- Build ChatMessage component (user vs. assistant styling)
- Wire up end-to-end: type message -> stream response -> render
- Add session persistence (Supabase `sessions` concept using existing session_id)

**Week 3: Chat Polish + Debug**
- Build SessionList component (left sidebar with session history)
- Build DebugPanel component (collapsible right panel)
- Parse SSE `thinking` events into debug panel
- Add token usage display from response metadata
- Add source citations (memory references in responses)
- Add keyboard shortcuts (Cmd+D toggle debug, Enter send)
- Loading states, error states, empty states

**Exit Criteria:**
- Can hold a multi-turn conversation with Sabine via the web UI
- Debug panel shows context retrieval, tool calls, and token usage
- Sessions persist and are browsable
- Sidebar navigation works across all routes
- `npm run build` passes, `npm run lint` passes

### Phase 2: Memory + Settings + Observability (Weeks 4-6)

**Week 4: Memory Enhancements**
- Add ArchivedMemories section to memory page
- Build SalienceControls component (weight sliders)
- Build ArchiveConfig component (threshold settings)
- Wire salience and archive settings to FastAPI endpoints
- Add archive stats display
- Add "Promote" action for archived memories

**Week 5: Settings + Observability**
- Build Settings page with tabbed sections
- Build MemorySettings, NotificationPrefs, ChannelStatus, SystemInfo components
- Build Observability health dashboard
- Build QueueStatus, WalStatus, SchedulerStatus components
- Build ToolAuditLog component (recent tool executions)
- Add `use-polling` hook for auto-refreshing metrics
- Install recharts, build MetricsChart for trend visualization

**Week 6: Skills Dashboard**
- Build Skills page with tabbed layout (Gaps / Proposals / Active)
- Build GapList component with dismiss + generate actions
- Build ProposalCard with code viewer + approve/reject
- Build SkillInventory with disable/rollback actions
- Wire all skills endpoints
- Add CodeViewer component for syntax-highlighted skill code

**Exit Criteria:**
- Full memory lifecycle manageable from UI (view, archive, promote, configure)
- Salience weights and archive rules configurable
- System health visible at a glance
- Skill gaps, proposals, and inventory viewable and actionable
- All settings persisted correctly

### Phase 3: Graph + Polish (Weeks 7-9)

**Week 7: Entity Graph Explorer**
- Build EntityList component (searchable, filterable)
- Build EntityDetail component (attributes, relationships, linked memories)
- Build RelationshipTable component (grouped by graph layer)
- Build CausalTrace component (vertical timeline)
- Wire all graph API endpoints

**Week 8: Task Overview + Command Palette**
- Replace mock data in Overview/Tasks with real `GET /tasks` data
- Build task detail modal with payload, dependencies, result
- Install cmdk, build CommandPalette (Cmd+K)
- Add command palette actions: navigate, search memories, search entities
- Add Gmail status to Settings (diagnostic + token health)

**Week 9: Polish**
- Responsive design audit (mobile sidebar -> bottom tabs)
- Loading skeletons for all data-fetching components
- Error boundaries for each module
- Accessibility audit (keyboard navigation, screen reader labels, focus management)
- Performance audit (bundle size, unnecessary re-renders)
- End-to-end testing of critical flows

**Exit Criteria:**
- Entity relationships browsable and inspectable
- Causal chains visualized
- All mock data replaced with real API data
- Cmd+K navigation works
- Mobile-responsive
- Accessible

### Phase 4: Future (Not Scheduled)

These are real features that require either backend work or significant frontend investment. They are documented here for roadmap clarity, not for immediate planning.

- **React Flow graph visualization** for MAGMA (interactive node/edge canvas)
- **Voice input** via Web Speech API or Whisper integration
- **Real-time collaboration** if multi-user support is added
- **Vector space visualization** (requires backend endpoint for raw embedding export + t-SNE/UMAP projection)
- **Agent intervention controls** (requires backend support for pausing running agents)
- **Prompt engineering sandbox** (test prompts against Sabine without full agent loop)
- **Mobile PWA** (service worker + offline support)

---

## 8. Migration Strategy

### Moving Existing Code

The existing frontend has working code that we do not want to break. Here is how the migration works:

1. **Keep existing API routes unchanged.** `/api/chat/route.ts`, `/api/memory/upload/route.ts`, `/api/gmail/webhook/route.ts`, `/api/cron/gmail-watch/route.ts` -- all stay exactly where they are.

2. **Move Memory Dashboard route.** `/dashboard/memory/page.tsx` -> `/memory/page.tsx`. Add a redirect from the old path. Move `actions.ts` alongside.

3. **Existing components stay.** `EntityCard`, `MemoryStream`, `FileUploader`, `NewEntityModal` -- these are enhanced, not replaced. Add shadcn/ui primitives alongside them and gradually migrate individual elements (e.g., replace hand-rolled buttons with `<Button>` from shadcn).

4. **Home page becomes redirect.** `/page.tsx` becomes a redirect to `/chat` instead of the current landing page with navigation links. Navigation moves to the sidebar.

5. **Overview page moves.** `/overview/page.tsx` -> `/observability/tasks/page.tsx` with real data replacing mock data.

---

## 9. Key Design Decisions

### D1: Why No WebSocket for Chat?

The backend uses SSE (`text/event-stream`), not WebSockets. SSE is:
- Simpler (HTTP-based, no upgrade handshake)
- Sufficient for server-to-client streaming (chat is one-directional during response)
- Compatible with HTTP/2 multiplexing
- Natively supported by browsers via `EventSource` API
- Already implemented in the backend (`/invoke/stream`)

The frontend sends messages via regular POST requests, then opens an SSE connection for the response stream. This is the correct pattern for LLM streaming.

### D2: Why Server Components for Data Pages?

Pages that primarily display data (Memory, Skills, Settings, Observability) use Server Components because:
- Direct Supabase access without exposing keys
- No client-side JavaScript for initial render
- Automatic streaming with Suspense boundaries
- `revalidatePath()` after mutations keeps data fresh

Client Components are used only where interactivity is required: chat input, form controls, real-time polling, drag-drop.

### D3: Why Not Build Dream Team Management Here?

The `dream-team-strug` repo already has:
- Real-time task monitoring dashboard
- Task dispatch and approval workflows
- Live event stream
- Orchestration status metrics

Duplicating this in `sabine-super-agent` would mean maintaining two implementations of the same feature across two repos. Instead, we provide a read-only task overview here and link out to the full Dream Team dashboard for management actions.

### D4: Why shadcn/ui Over Building Custom?

The existing 8 components have:
- No shared button styles (each component styles its own buttons)
- No shared input styles
- No shared modal patterns (NewEntityModal and TaskViewModal have different approaches)
- No accessibility primitives (Radix handles focus trapping, keyboard navigation, ARIA)

shadcn/ui gives us ~30 accessible, Tailwind-styled primitives that are copy-pasted into our codebase (not a dependency). We own the code, can modify anything, and get accessibility for free via Radix.

---

## 10. Success Criteria

### Functional
- User can chat with Sabine via web UI with streaming responses
- User can view and manage memories (view, archive, promote, configure salience/archive rules)
- User can browse entity relationships and causal chains
- User can manage skill lifecycle (view gaps, approve/reject proposals, disable/rollback skills)
- User can monitor system health, queue status, and tool audit logs
- User can configure settings (notification preferences, communication channels)

### Technical
- `npm run build` passes with zero errors
- `npm run lint` passes with zero warnings
- All pages load in < 2 seconds (P95)
- Chat SSE streaming works reliably with proper error recovery
- Dark mode works consistently across all pages
- Mobile-responsive layout (sidebar collapses to bottom tabs)

### UX
- New user can start chatting within 5 seconds of landing
- Debug panel provides actionable insight (not just raw JSON dumps)
- Memory management is understandable without documentation
- System health is visible at a glance (sidebar health dot)
- Navigation between modules is < 2 clicks from anywhere

---

*End of Document*
