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

5.  **React/JSX (CRITICAL):**
    - **NEVER use raw `"` or `'` or `{` or `}` or `>` characters inside JSX text content.** These violate the `react/no-unescaped-entities` ESLint rule and will break the production build.
    - Use HTML entities instead: `&quot;` for `"`, `&apos;` for `'`, `&lbrace;` / `&rbrace;` for `{`/`}`, `&gt;` for `>`.
    - Alternatively, wrap the text in a JavaScript expression: `{"some text with \"quotes\""}`.
    - **Always run `npm run lint` after modifying any `.tsx` or `.jsx` file** to catch these errors before committing.
