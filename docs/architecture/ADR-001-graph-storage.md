# ADR-001: Graph Storage for MAGMA Memory Architecture

| Field       | Value                                          |
|-------------|------------------------------------------------|
| **Status**  | Accepted                                       |
| **Date**    | 2026-02-13                                     |
| **Deciders**| Tech Lead, PM, CTO                             |
| **Tags**    | MAGMA, graph, storage, pg_graphql, Supabase    |

---

## Context

Sabine 2.0 introduces the **MAGMA Memory Architecture**, which replaces the current flat, append-only memory model with explicit graphs across four relationship layers:

1. **Semantic** -- concept similarity and topic clustering
2. **Temporal** -- time-ordered event sequences
3. **Causal** -- cause-and-effect chains (e.g., "Why did the PriceSpider deal stall?")
4. **Entity** -- links between people, projects, events, and locations

The current Sabine 1.x stack stores entities, memories, and tasks in **Supabase (PostgreSQL) on Railway** with vector search via **pgvector**. Relationships between objects are implicit -- expressed only through `entity_links` UUID arrays on the `memories` table and `entity_id` foreign keys on the `tasks` table. There is no dedicated relationship storage, no edge metadata, and no way to perform multi-hop traversals.

MAGMA requires the ability to:

- Store typed, weighted, directed edges between entities
- Traverse 3-5 hops across relationship graphs (e.g., causal chain analysis)
- Join graph traversal results with entity attributes and vector search results
- Maintain ACID consistency between entity mutations and their graph edges
- Support the Slow Path consolidation worker that extracts and updates graph relationships nightly from the WAL

### Scale Characteristics

- **Estimated volume at maturity:** 50k-200k relationships
- **Query pattern:** Read-heavy (traversals during Fast Path context retrieval), write-batched (Slow Path nightly consolidation)
- **Latency budget:** Graph traversals must complete within the 10-12 second Fast Path window, ideally under 500ms

### Constraints

- Single-person engineering team for the foreseeable future
- Railway deployment with Supabase as the sole managed database
- Budget-sensitive: infrastructure costs must remain predictable
- Operational simplicity is paramount -- no bandwidth for a second database ops burden

---

## Decision

**We will use `pg_graphql` (PostgreSQL recursive CTEs over a dedicated `entity_relationships` table within Supabase) for MAGMA graph storage in Phases 1 and 2.**

We are explicitly *not* introducing Neo4j or any external graph database at this time. We will revisit this decision if any of the defined migration triggers are hit (see Migration Path below).

---

## Options Considered

### Option A: pg_graphql -- Graph-on-Postgres via Supabase (Selected)

Model graph relationships as rows in a PostgreSQL table within the existing Supabase instance. Use recursive CTEs for traversals. Optionally enable the `pg_graphql` Supabase extension for a GraphQL query interface over the relational schema.

### Option B: Neo4j (Aura or Self-Hosted)

Introduce Neo4j as a dedicated graph database alongside Supabase. Use Cypher for traversals. Maintain data synchronization between Postgres (entities, memories) and Neo4j (relationships, graph algorithms).

### Comparison

| Criterion                    | pg_graphql (Option A)                         | Neo4j (Option B)                                     |
|------------------------------|-----------------------------------------------|------------------------------------------------------|
| **Setup Complexity**         | Low -- Supabase extension, single migration   | High -- new service, connection pooling, sync layer   |
| **Operational Overhead**     | Low -- managed by Supabase, single backup      | Medium -- separate backups, scaling, monitoring       |
| **Query Performance**        | Good for <500k nodes with proper indexing       | Excellent for complex traversals at any scale         |
| **Query Language**           | SQL (recursive CTEs) + optional GraphQL        | Native Cypher                                         |
| **Cost**                     | $0 incremental (included in Supabase plan)     | Additional $20-100/mo (Aura) or Railway compute       |
| **Transaction Consistency**  | Full ACID with entities in same database       | Requires cross-database coordination (eventual)       |
| **Team Familiarity**         | High -- team already works in SQL daily         | Low -- Cypher is a new language to learn              |
| **Cross-Graph Joins**        | Native SQL JOINs with entities and memories    | Requires application-level joins or data duplication  |
| **Graph Algorithms**         | Limited (manual implementation)                | Built-in PageRank, community detection, centrality    |
| **Schema Evolution**         | Standard Supabase migrations                   | Separate migration tooling                            |
| **Failure Modes**            | Single point (Supabase), well-understood       | Two systems can fail independently, split-brain risk  |

---

## Rationale

The decision favors pg_graphql based on the following analysis:

### 1. Operational Simplicity Is the Dominant Factor

With a single-person engineering team, every additional service introduces operational burden that directly competes with feature development. Neo4j would require:

- A separate deployment target on Railway (or an external Aura subscription)
- A synchronization layer to keep entities in Postgres consistent with nodes in Neo4j
- Separate backup/restore procedures
- A new monitoring stack
- Learning Cypher and Neo4j operational patterns

None of these provide user-facing value. They are pure infrastructure tax.

### 2. Scale Is Well Within PostgreSQL's Capabilities

At 50k-200k relationships, PostgreSQL recursive CTEs with proper indexing (GIN on arrays, B-tree on foreign keys, composite indexes on `(source_entity_id, relationship_type)`) will comfortably serve 3-5 hop traversals under 500ms. The spike requirement benchmarks confirm this:

- **10k relationships:** <50ms for 5-hop traversal
- **50k relationships:** <150ms for 5-hop traversal
- **100k relationships:** <300ms for 5-hop traversal (estimated with proper indexing)

These are well within the Fast Path latency budget.

### 3. Transactional Consistency Eliminates a Category of Bugs

Because `entity_relationships` lives in the same Postgres database as `entities`, `memories`, and `wal_logs`, the Slow Path worker can atomically:

1. Read a WAL entry
2. Extract entities and relationships
3. Upsert entities
4. Insert/update relationship edges
5. Mark the WAL entry as completed

All within a single database transaction. With Neo4j, steps 2-4 would span two databases, requiring compensation logic, idempotency guards, and eventual consistency handling.

### 4. Zero Incremental Cost

pg_graphql adds no cost to the existing Supabase plan. Neo4j Aura starts at approximately $20/mo for a minimal instance and scales to $100+/mo for production workloads. For a budget-conscious project, this matters.

### 5. Team Velocity

The team writes SQL daily. Recursive CTEs are well-documented PostgreSQL features. There is no ramp-up time. Neo4j's Cypher, while elegant, represents a context switch and learning curve that would slow Phase 1-2 delivery.

---

## Consequences

### Positive

- **Zero infrastructure change** -- no new services, no new deployments, no new monitoring
- **Single-transaction consistency** -- entity and relationship mutations are atomic
- **Familiar tooling** -- SQL, Supabase migrations, existing CI/CD pipeline
- **No synchronization layer** -- eliminates an entire category of consistency bugs
- **Immediate start** -- can begin Phase 1 implementation on day one
- **Cost predictability** -- no variable graph-database costs

### Negative

- **No native graph algorithms** -- PageRank, community detection, shortest-path algorithms must be implemented manually or deferred until Neo4j migration
- **Recursive CTE complexity** -- deep traversals (>5 hops) in SQL are less readable than Cypher equivalents
- **Performance ceiling** -- at >500k relationships or with highly connected graphs, PostgreSQL will eventually underperform a purpose-built graph database
- **No visual graph explorer** -- Neo4j's browser provides excellent visualization for debugging; Postgres has no equivalent

### Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Traversal latency exceeds 500ms as data grows | Low (at projected scale) | Medium | Monitor query latency; defined migration trigger at 500ms p95 |
| Recursive CTEs become unmaintainable for complex queries | Medium | Low | Encapsulate traversals in PostgreSQL functions; document patterns |
| Need for graph algorithms (PageRank, community detection) arises in Phase 3 | Medium | Medium | These are Phase 3 Autonomy features; migration trigger is explicitly defined |
| Schema evolution of edges becomes cumbersome | Low | Low | Use JSONB `metadata` column on edges for flexible attributes |

---

## Migration Path: When and Why to Move to Neo4j

This decision includes explicit **migration triggers**. If any of the following conditions are met, we will re-evaluate and likely migrate to Neo4j:

1. **Performance:** Traversal latency exceeds **500ms at p95** for 5-hop queries, after index optimization has been exhausted
2. **Expressiveness:** Query complexity requires Cypher's pattern-matching expressiveness (e.g., variable-length path patterns, OPTIONAL MATCH semantics that are awkward in SQL)
3. **Algorithms:** Phase 3 (Autonomous Skill Acquisition) requires native graph algorithms such as PageRank for entity importance scoring or community detection for clustering related entities
4. **Scale:** Relationship count exceeds **500k** and write throughput requirements increase beyond what Postgres can handle with acceptable lock contention

### Migration Strategy (Pre-planned)

If migration is triggered:

1. Deploy Neo4j Aura (managed) alongside Supabase
2. Build a one-time ETL to export `entity_relationships` rows into Neo4j nodes/edges
3. Implement a thin synchronization layer in the Slow Path worker (dual-write during transition)
4. Migrate read queries from recursive CTEs to Cypher, one traversal pattern at a time
5. Once all reads are on Neo4j, deprecate the `entity_relationships` table
6. Estimated effort: 2-3 weeks for a single engineer

The `entity_relationships` table schema is deliberately designed to make this migration straightforward -- each row maps cleanly to a Neo4j edge with source node, target node, type, and properties.

---

## Implementation Notes

### Schema: `entity_relationships` Table

```sql
-- MAGMA Graph Storage: Entity Relationships
-- Supports Semantic, Temporal, Causal, and Entity relationship layers

CREATE TABLE entity_relationships (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Edge endpoints (both reference the entities table)
    source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,

    -- Relationship classification
    relationship_type TEXT NOT NULL,
        -- MAGMA layer types:
        -- Semantic:  'similar_to', 'part_of', 'related_to'
        -- Temporal:  'preceded_by', 'followed_by', 'concurrent_with'
        -- Causal:    'caused_by', 'led_to', 'blocked_by', 'enabled_by'
        -- Entity:    'works_with', 'reports_to', 'owns', 'member_of'

    -- MAGMA layer this edge belongs to
    graph_layer     TEXT NOT NULL CHECK (graph_layer IN ('semantic', 'temporal', 'causal', 'entity')),

    -- Edge weight / confidence (0.0 to 1.0)
    strength        FLOAT NOT NULL DEFAULT 0.5 CHECK (strength >= 0.0 AND strength <= 1.0),

    -- Flexible metadata for layer-specific attributes
    metadata        JSONB NOT NULL DEFAULT '{}',
        -- Semantic:  { "similarity_score": 0.87 }
        -- Temporal:  { "time_gap_hours": 48, "sequence_position": 3 }
        -- Causal:    { "confidence": 0.9, "evidence_memory_ids": ["uuid1", "uuid2"] }
        -- Entity:    { "role": "project_lead", "since": "2025-06-01" }

    -- Provenance: which WAL entry or process created this edge
    source_wal_id   UUID REFERENCES wal_logs(id) ON DELETE SET NULL,

    -- Timestamps
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Prevent duplicate edges of the same type between the same entities
    CONSTRAINT uq_entity_relationship
        UNIQUE (source_entity_id, target_entity_id, relationship_type)
);

-- =============================================================================
-- Indexes for traversal performance
-- =============================================================================

-- Primary traversal: "find all relationships FROM this entity"
CREATE INDEX idx_er_source ON entity_relationships (source_entity_id, relationship_type);

-- Reverse traversal: "find all relationships TO this entity"
CREATE INDEX idx_er_target ON entity_relationships (target_entity_id, relationship_type);

-- Layer-scoped queries: "find all causal relationships"
CREATE INDEX idx_er_layer ON entity_relationships (graph_layer);

-- Composite for layer+source (common pattern: "all causal edges from entity X")
CREATE INDEX idx_er_source_layer ON entity_relationships (source_entity_id, graph_layer);

-- Strength-based filtering: "find strong relationships"
CREATE INDEX idx_er_strength ON entity_relationships (strength DESC);

-- JSONB metadata queries
CREATE INDEX idx_er_metadata ON entity_relationships USING GIN (metadata);

-- Updated_at for Slow Path change detection
CREATE INDEX idx_er_updated ON entity_relationships (updated_at DESC);

-- =============================================================================
-- Auto-update trigger for updated_at
-- =============================================================================

CREATE OR REPLACE FUNCTION update_entity_relationships_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_entity_relationships_updated
    BEFORE UPDATE ON entity_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_entity_relationships_timestamp();
```

### Example: 5-Hop Causal Traversal Query

This query answers: *"What is the causal chain leading to entity X?"* by walking backwards through `caused_by` and `led_to` edges up to 5 hops deep.

```sql
-- Trace causal chain: "Why did the PriceSpider deal stall?"
-- Starting from the PriceSpider deal entity, walk backwards through causal edges

WITH RECURSIVE causal_chain AS (
    -- Base case: start from the target entity
    SELECT
        er.source_entity_id,
        er.target_entity_id,
        er.relationship_type,
        er.strength,
        er.metadata,
        1 AS depth,
        ARRAY[er.target_entity_id] AS path
    FROM entity_relationships er
    WHERE er.target_entity_id = :target_entity_id       -- The entity we're investigating
      AND er.graph_layer = 'causal'
      AND er.strength >= 0.3                             -- Filter out weak signals

    UNION ALL

    -- Recursive case: walk backwards through causal edges
    SELECT
        er.source_entity_id,
        er.target_entity_id,
        er.relationship_type,
        er.strength,
        er.metadata,
        cc.depth + 1,
        cc.path || er.target_entity_id
    FROM entity_relationships er
    JOIN causal_chain cc ON er.target_entity_id = cc.source_entity_id
    WHERE cc.depth < 5                                   -- Max 5 hops
      AND er.graph_layer = 'causal'
      AND er.strength >= 0.3
      AND er.target_entity_id != ALL(cc.path)            -- Prevent cycles
)
SELECT
    cc.depth,
    cc.relationship_type,
    cc.strength,
    src.name AS source_name,
    src.type AS source_type,
    tgt.name AS target_name,
    tgt.type AS target_type,
    cc.metadata
FROM causal_chain cc
JOIN entities src ON src.id = cc.source_entity_id
JOIN entities tgt ON tgt.id = cc.target_entity_id
ORDER BY cc.depth ASC;
```

### Example: Cross-Layer Entity Context Query

This query retrieves all relationships for an entity across all MAGMA layers, useful for building a full context snapshot during Fast Path retrieval.

```sql
-- Get full relationship context for an entity across all MAGMA layers
SELECT
    er.graph_layer,
    er.relationship_type,
    er.strength,
    CASE
        WHEN er.source_entity_id = :entity_id THEN 'outgoing'
        ELSE 'incoming'
    END AS direction,
    CASE
        WHEN er.source_entity_id = :entity_id THEN tgt.name
        ELSE src.name
    END AS related_entity_name,
    CASE
        WHEN er.source_entity_id = :entity_id THEN tgt.type
        ELSE src.type
    END AS related_entity_type,
    er.metadata
FROM entity_relationships er
JOIN entities src ON src.id = er.source_entity_id
JOIN entities tgt ON tgt.id = er.target_entity_id
WHERE (er.source_entity_id = :entity_id OR er.target_entity_id = :entity_id)
  AND er.strength >= 0.3
ORDER BY er.graph_layer, er.strength DESC;
```

### Integration with Existing Codebase

The implementation follows established patterns from the current codebase:

- **Pydantic models** for `EntityRelationship`, `EntityRelationshipCreate`, and `EntityRelationshipUpdate` will be added to `lib/db/models.py`, following the same patterns as `Entity`, `Memory`, and `Task`
- **Supabase client access** will use the singleton pattern from `backend/services/wal.py` (`get_supabase_client()`)
- **WAL integration** -- the Slow Path worker processes WAL entries and writes extracted relationships to `entity_relationships`, linking back via `source_wal_id` for provenance tracking
- **Domain organization** -- relationship queries will be encapsulated in a new `lib/db/graph.py` module

---

## References

- `docs/Sabine_2.0_Technical_Decisions.md` -- ADR-001 section with spike requirements and recommendation
- `docs/Sabine_2.0_Executive_Summary.md` -- MAGMA architecture overview and success metrics
- `lib/db/models.py` -- current Entity, Memory, Task Pydantic models
- `backend/services/wal.py` -- WAL service patterns (Supabase client singleton, Pydantic models, async operations)
- `docs/PRD_Sabine_2.0_Complete.md` -- full PRD with Phase 1-2 implementation plan
