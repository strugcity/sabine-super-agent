# Technical PRD: Sabine Context Engine (V1)
**Status:** Approved for Execution

## 1. Executive Summary
The Context Engine allows Sabine to ingest, structure, and retrieve user info across distinct domains (Work, Family, Logistics). It moves from simple chat history to a persistent Knowledge Graph.

## 2. System Architecture
We implement a **Three-Stage Cognitive Pipeline**:

1. **Ingestion (The Router):** LLM classifier determines Domain and Intent.

2. **Storage (The Hybrid Graph):** Supabase Monolith.
   - **Vector Store:** For fuzzy memories.
   - **Relational Graph:** For hard facts (Entities, Relations).

3. **Retrieval (The Blender):** Unified query service blending Hard Facts with Soft Context.

## 3. Data Schema (Owner: @backend-architect-sabine)
**Core Tables:**

- **domains:** Enum (Work, Family, Personal, Logistics)

- **entities:** The "Nouns" (Projects, People). Columns: `id`, `name`, `type`, `domain_id`, `attributes` (JSONB).

- **memories:** Unstructured context. Columns: `content`, `embedding` (vector), `entity_links` (array).

- **tasks:** Linked to Entities.

## 4. Feature Specifications

### Feature A: The Active Listener (Ingestion)

**Logic:**
1. Extract Entities and Domains via LLM.
2. Fuzzy match existing Entities (Update vs Create).
3. Store vector embedding in `memories`.

### Feature B: The Brain Dashboard (Frontend)

**Owner:** @frontend-ops-sabine

**View:** Wiki-style list of Entities grouped by Domain.

**Actions:** Search, Edit Attributes (JSONB), Prune Memories.

### Feature C: Blended Retrieval

**Logic:** Query `tasks` + Vector Search `memories` -> Combine into single context window.

## 5. User Stories
1. User texts 'Baseball game moved to 5 PM' -> Updates 'Baseball' entity.

2. User views 'Active Work Projects' on Dashboard -> Archives finished project.

3. User asks 'What is on deck?' -> Response includes Work deadlines + Personal goals.
