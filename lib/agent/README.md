# Agent Core (Python + LangGraph)

This directory contains the core agent logic powered by LangGraph.

## Structure

- `__init__.py` - Package initialization
- `agent.py` - Main agent state machine (to be implemented)
- `state.py` - Agent state definitions (to be implemented)
- `context.py` - Deep context injection system (to be implemented)

## Key Concepts

### Deep Context Injection
Before processing any user query, the agent loads:
- Rules from the database
- Current custody schedule state
- User preferences and history

### Dual-Brain Memory
- **Vector Store**: Fuzzy notes and semantic search (Supabase pgvector)
- **Knowledge Graph**: Strict logic and relationships (SQL tables)
