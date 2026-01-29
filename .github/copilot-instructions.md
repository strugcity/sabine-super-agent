# Sabine Super Agent - Coding Instructions

## Tech Stack
- **Backend:** Python 3.11+, FastAPI, Supabase (Postgres + pgvector).
- **Frontend:** Next.js 14+ (App Router), Tailwind CSS, TypeScript.
- **AI/Agents:** LangChain/LangGraph concepts, Pydantic for data validation.

## Coding Rules
1.  **Architecture:**
    - Follow a modular structure: `lib/agent/` for logic, `lib/db/` for database interactions.
    - Use **Stdio transport** for local MCP server connections.
    - Python functions must be fully typed (Type Hints).

2.  **Error Handling:**
    - Never swallow errors silently. Log them using the standard `logging` library.
    - For API routes, return structured JSON errors.

3.  **Testing & Validation:**
    - Before suggesting large refactors, run a syntax check (`python -m py_compile filename.py`).
    - Use Pydantic v2 `BaseModel` for all data schemas.

4.  **Agent Protocol:**
    - If editing `gmail_handler.py`, ensure imports are lazy (inside functions) to avoid circular dependency loops with `server.py`.
