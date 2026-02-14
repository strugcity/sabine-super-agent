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

### Parallel Work (MUST FOLLOW)
- **Before dispatching ANY parallel agents**, launch the dashboard: `python scripts/parallel_dashboard.py`
  - This opens a live web UI at http://localhost:3847 that auto-polls every 3 seconds — zero token cost
  - Pass `--workspace <name>` to filter to a specific workspace
- **Every parallel Claude Code session MUST use `SessionTracker` from `lib/parallel/`** for status reporting
- **Heartbeats MUST be sent at least every 5 minutes** during parallel work
- **Sessions MUST call `.complete()` or `.fail()`** before exiting
- **Do NOT use the CLI monitor (`parallel_monitor.py`) from within Claude Code** for ongoing polling — it wastes tokens. Use the dashboard UI instead. The CLI is for one-shot checks only.
- **`.parallel/` is gitignored** - it's local transient state, never committed
- **Do NOT confuse with Dream Team task queue** (`backend/services/task_queue.py`) which is for production multi-agent orchestration
- See `docs/plans/parallel-work-best-practices.md` for full guide
