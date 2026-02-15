# CLAUDE.md - Claude Code Instructions

## Project Overview
Sabine Super Agent - a personal AI agent with a Python/FastAPI backend and Next.js frontend.

## Tech Stack
- **Backend:** Python 3.11+, FastAPI, Supabase (Postgres + pgvector)
- **Frontend:** Next.js 15 (App Router), Tailwind CSS, TypeScript
- **AI/Agents:** LangChain/LangGraph, Pydantic v2

## Build & Lint Commands
- `npm run build` - Build the Next.js frontend (must pass before merge)
- `npm run lint` - Run ESLint on frontend code
- `python -m py_compile <file>` - Syntax check Python files

## Critical Rules

### React/JSX (MUST FOLLOW)
- **NEVER use raw `"` `'` `{` `}` `>` characters in JSX text content.** This violates `react/no-unescaped-entities` and breaks production builds.
- Use HTML entities: `&quot;` `&apos;` `&lbrace;` `&rbrace;` `&gt;`
- Or wrap text in JS expressions: `{"text with \"quotes\""}`
- **Always run `npm run lint` after editing any `.tsx` or `.jsx` file.**

### Python Backend
- All functions must have full type hints
- Use Pydantic v2 `BaseModel` for all data schemas
- Never swallow errors silently - use `logging`
- Use lazy imports (inside functions) when importing between modules that reference each other to avoid circular dependencies
- Run `python -m py_compile <file>` to syntax-check after edits

### Architecture
- `lib/agent/` - Backend agent logic
- `lib/agent/routers/` - FastAPI route handlers (domain-organized)
- `lib/db/` - Database interactions
- `lib/parallel/` - Parallel session observability (local dev tooling, NOT production)
- `src/` - Next.js frontend
- Shared models, constants, and auth dependencies should live in `lib/agent/shared.py` (not duplicated across files)

### Multi-Task Work: DEFAULT PROTOCOL (MUST FOLLOW)

**When the user requests work that spans 3+ files or 2+ independent features, the DEFAULT approach is parallel dispatch — NOT direct coding.** Direct coding burns tokens linearly. Parallel dispatch runs N agents concurrently at the same cost as 1, with the user watching progress on a dashboard.

**Only code directly when:**
- The task is a single small fix (< 3 files)
- The user explicitly says "just do it" or "code this directly"
- The task has hard sequential dependencies that prevent parallelism

#### The Parallel Dispatch Protocol (4 steps)

**Step 1: Launch the dashboard**
```bash
python scripts/parallel_dashboard.py --workspace <name>
```
This opens http://localhost:3847 — zero token cost, user watches progress here.

**Step 2: Register sessions on the dashboard BEFORE dispatching agents**
Task tool subagents cannot run `SessionTracker` themselves (they lack a persistent Python runtime). The coordinator MUST register all sessions upfront:
```python
python -c "
import sys; sys.path.insert(0, '.')
from lib.parallel import SessionTracker
for sid, desc in [('session-1', 'Description 1'), ('session-2', 'Description 2')]:
    t = SessionTracker(session_id=sid, workspace='<name>')
    t.start(desc)
    t.heartbeat(progress_pct=5, message='Agent dispatched')
"
```

**Step 3: Dispatch agents via Task tool**
- Use `run_in_background: true` on all Task calls
- Each agent prompt MUST include bash commands to update the dashboard at milestones:
  ```bash
  python -c "
  import sys; sys.path.insert(0, '.')
  from lib.parallel import SessionTracker
  t = SessionTracker(session_id='SESSION_ID', workspace='WORKSPACE')
  t.heartbeat(progress_pct=PERCENT, message='MESSAGE')
  "
  ```
- Each agent prompt MUST include a `.complete()` bash command to run on success and a `.fail()` command on failure
- Write detailed session prompts with full file context — agents start cold with no prior conversation

**Step 4: Wait passively, then audit**
- Do NOT poll agents from within Claude Code — the user watches the dashboard
- When agents finish, audit outputs (py_compile, spot-check key files)
- Commit if clean, report issues if not

#### Key Constraints
- **`.parallel/` is gitignored** — local transient state, never committed
- **Do NOT use `parallel_monitor.py` from within Claude Code** for ongoing polling — it wastes tokens. The dashboard UI is free.
- **Do NOT confuse with Dream Team task queue** (`backend/services/task_queue.py`) — that is production multi-agent orchestration
- **Session prompt files are throwaway** — do not commit them. The reusable knowledge lives in plan docs.
- See `docs/plans/parallel-work-best-practices.md` for full guide
