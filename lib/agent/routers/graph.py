"""
Graph Router - MAGMA entity relationship endpoints.

Provides endpoints for managing and querying the entity relationship graph.

Endpoints:
- POST /api/graph/backfill  - Trigger relationship backfill from existing memories
- GET  /api/graph/traverse/{entity_id}  - Multi-hop graph traversal via RPC
- GET  /api/graph/causal-trace/{entity_id} - Trace causal chains
- GET  /api/graph/network/{entity_id} - Entity network for visualization
- GET  /api/graph/relationships/{entity_id} - Direct 1-hop relationships
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from lib.agent.shared import verify_api_key


class Direction(str, Enum):
    """Valid directions for relationship queries."""
    OUTGOING = "outgoing"
    INCOMING = "incoming"
    BOTH = "both"

logger = logging.getLogger(__name__)


# =============================================================================
# Pydantic v2 Request / Response Models
# =============================================================================

class BackfillRequest(BaseModel):
    """Request body for POST /api/graph/backfill."""

    batch_size: int = Field(
        default=500,
        ge=1,
        le=5000,
        description="Maximum memories to process in this backfill run",
    )
    dry_run: bool = Field(
        default=False,
        description="If true, log actions without storing relationships",
    )


class BackfillResponse(BaseModel):
    """Response model for POST /api/graph/backfill."""

    job_id: Optional[str] = Field(
        default=None,
        description="rq job ID (None if enqueue failed)",
    )
    status: str = Field(
        ...,
        description="Result status: enqueued or failed",
    )
    error: Optional[str] = Field(
        default=None,
        description="Error message if enqueue failed",
    )


class RelationshipItem(BaseModel):
    """A single entity relationship."""

    source_entity_id: Optional[str] = Field(default=None)
    target_entity_id: Optional[str] = Field(default=None)
    source_name: str = Field(default="unknown")
    target_name: str = Field(default="unknown")
    relationship_type: Optional[str] = Field(default=None)
    confidence: float = Field(default=0.0)
    graph_layer: Optional[str] = Field(default=None)
    direction: Optional[str] = Field(default=None)


class EntityRelationshipsResponse(BaseModel):
    """Response model for GET /api/graph/relationships/{entity_id}."""

    entity_id: str = Field(..., description="The queried entity ID")
    relationships: List[RelationshipItem] = Field(
        default_factory=list,
        description="List of relationships for this entity",
    )
    count: int = Field(default=0, description="Number of relationships returned")
    error: Optional[str] = Field(default=None)


# -- Traverse models ---------------------------------------------------------

class TraversalEdge(BaseModel):
    """A single edge in a traversal result."""

    source_id: str = Field(..., description="Source entity UUID")
    target_id: str = Field(..., description="Target entity UUID")
    source_name: str = Field(default="unknown")
    target_name: str = Field(default="unknown")
    relationship_type: str = Field(default="")
    graph_layer: str = Field(default="entity")
    confidence: float = Field(default=0.0)
    hop: int = Field(default=1)


class TraverseResponse(BaseModel):
    """Response model for GET /api/graph/traverse/{entity_id}."""

    entity_id: str = Field(..., description="Starting entity UUID")
    edges: List[TraversalEdge] = Field(default_factory=list)
    total_edges: int = Field(default=0)
    max_hop: int = Field(default=0)
    error: Optional[str] = Field(default=None)


# -- Causal trace models -----------------------------------------------------

class CausalLink(BaseModel):
    """A single link in a causal chain."""

    from_name: str = Field(..., alias="from", description="Source entity name")
    from_id: str = Field(default="")
    to: str = Field(..., description="Target entity name")
    to_id: str = Field(default="")
    type: str = Field(default="")
    confidence: float = Field(default=0.0)
    hop: int = Field(default=1)

    model_config = {"populate_by_name": True}


class RootEntity(BaseModel):
    """Minimal root entity info."""

    id: str = Field(...)
    name: str = Field(default="unknown")


class CausalTraceResponse(BaseModel):
    """Response model for GET /api/graph/causal-trace/{entity_id}."""

    root_entity: RootEntity = Field(...)
    chain: List[CausalLink] = Field(default_factory=list)
    total_hops: int = Field(default=0)
    max_confidence: float = Field(default=0.0)
    min_confidence: float = Field(default=0.0)
    error: Optional[str] = Field(default=None)


# -- Network models ----------------------------------------------------------

class NetworkNode(BaseModel):
    """A node in the entity network graph."""

    id: str = Field(...)
    name: str = Field(default="unknown")
    type: str = Field(default="")
    domain: str = Field(default="")


class NetworkEdge(BaseModel):
    """An edge in the entity network graph."""

    source: str = Field(...)
    target: str = Field(...)
    type: str = Field(default="")
    layer: str = Field(default="entity")
    confidence: float = Field(default=0.0)
    hop: int = Field(default=1)


class NetworkStatistics(BaseModel):
    """Statistics for a network response."""

    total_nodes: int = Field(default=0)
    total_edges: int = Field(default=0)
    max_hop: int = Field(default=0)
    layers_found: List[str] = Field(default_factory=list)


class RootEntityFull(BaseModel):
    """Root entity with full details."""

    id: str = Field(...)
    name: str = Field(default="unknown")
    type: str = Field(default="")
    domain: str = Field(default="")


class NetworkResponse(BaseModel):
    """Response model for GET /api/graph/network/{entity_id}."""

    root_entity: RootEntityFull = Field(...)
    nodes: List[NetworkNode] = Field(default_factory=list)
    edges: List[NetworkEdge] = Field(default_factory=list)
    statistics: NetworkStatistics = Field(default_factory=NetworkStatistics)
    error: Optional[str] = Field(default=None)


# =============================================================================
# Router
# =============================================================================

router = APIRouter(prefix="/api/graph", tags=["graph"])


# =============================================================================
# Endpoints
# =============================================================================

@router.post("/backfill", response_model=BackfillResponse, status_code=202)
async def trigger_backfill(
    request: BackfillRequest,
    _: bool = Depends(verify_api_key),
) -> BackfillResponse:
    """
    Trigger relationship backfill job.

    Enqueues a background job that scans existing memories with 2+
    entity_links, extracts relationships via Claude Haiku, and stores
    them in the entity_relationships table.

    The job is idempotent (UNIQUE constraint handles dedup on re-runs).
    """
    try:
        # Lazy import to avoid circular deps
        from backend.services.queue import _enqueue_job

        result = _enqueue_job(
            func_path="backend.worker.jobs.run_backfill_job",
            kwargs={
                "batch_size": request.batch_size,
                "dry_run": request.dry_run,
            },
            priority="low",
        )

        if result.success:
            logger.info(
                "Backfill job enqueued as %s (batch_size=%d, dry_run=%s)",
                result.job_id,
                request.batch_size,
                request.dry_run,
            )
            return BackfillResponse(
                job_id=result.job_id,
                status="enqueued",
            )

        return BackfillResponse(
            status="failed",
            error="Enqueue returned no job ID (queue may be unavailable)",
        )

    except ImportError as exc:
        logger.error("rq package not installed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="rq package not installed. Install with: pip install rq",
        )
    except Exception as exc:
        logger.error(
            "Failed to enqueue backfill job: %s",
            exc,
            exc_info=True,
        )
        raise HTTPException(
            status_code=503,
            detail=f"Failed to enqueue backfill job: {exc}",
        )


# =============================================================================
# Graph Traversal Endpoints (MAGMA-005)
# =============================================================================

@router.get("/traverse/{entity_id}", response_model=TraverseResponse)
async def traverse_endpoint(
    entity_id: str,
    max_depth: int = Query(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of hops",
    ),
    relationship_type: Optional[str] = Query(
        default=None,
        description="Filter by relationship type",
    ),
    layer: Optional[str] = Query(
        default=None,
        description="Filter by graph layer (entity, semantic, temporal, causal)",
    ),
    min_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    ),
    _: bool = Depends(verify_api_key),
) -> TraverseResponse:
    """
    Traverse the entity relationship graph from a starting entity.

    Uses the ``traverse_graph()`` Postgres RPC for efficient multi-hop
    bidirectional traversal with cycle prevention.
    """
    try:
        from uuid import UUID as _UUID

        try:
            _UUID(entity_id)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid entity_id: {entity_id}")

        # Lazy import for Supabase client
        from backend.services.wal import get_supabase_client

        client = get_supabase_client()

        rpc_resp = client.rpc(
            "traverse_graph",
            {
                "start_entity_id": entity_id,
                "max_depth": max_depth,
                "relationship_type_filter": relationship_type,
                "layer_filter": layer,
                "min_confidence": min_confidence,
            },
        ).execute()

        rows: List[Dict[str, Any]] = rpc_resp.data or []

        edges = [
            TraversalEdge(
                source_id=str(row.get("source_id", "")),
                target_id=str(row.get("target_id", "")),
                source_name=row.get("source_name", "unknown"),
                target_name=row.get("target_name", "unknown"),
                relationship_type=row.get("relationship_type", ""),
                graph_layer=row.get("graph_layer", "entity"),
                confidence=float(row.get("confidence", 0.0)),
                hop=int(row.get("hop", 0)),
            )
            for row in rows
        ]

        max_hop = max((e.hop for e in edges), default=0)

        return TraverseResponse(
            entity_id=entity_id,
            edges=edges,
            total_edges=len(edges),
            max_hop=max_hop,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "traverse failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        return TraverseResponse(
            entity_id=entity_id,
            error=str(exc),
        )


@router.get("/causal-trace/{entity_id}", response_model=CausalTraceResponse)
async def causal_trace_endpoint(
    entity_id: str,
    max_depth: int = Query(
        default=3,
        ge=1,
        le=5,
        description="Maximum number of hops in the causal chain",
    ),
    min_confidence: float = Query(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    ),
    _: bool = Depends(verify_api_key),
) -> CausalTraceResponse:
    """
    Trace causal chains from an entity.

    Returns a chain of cause-effect relationships using
    ``traverse_graph()`` RPC with ``layer_filter='causal'``.
    """
    try:
        from uuid import UUID as _UUID

        try:
            _UUID(entity_id)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid entity_id: {entity_id}")

        # Lazy import to avoid circular deps
        from backend.magma.query import causal_trace

        result = await causal_trace(
            entity_id=entity_id,
            max_depth=max_depth,
            min_confidence=min_confidence,
        )

        root = result.get("root_entity", {})
        chain_data = result.get("chain", [])

        chain = [
            CausalLink(
                **{
                    "from": link.get("from", "unknown"),
                    "from_id": link.get("from_id", ""),
                    "to": link.get("to", "unknown"),
                    "to_id": link.get("to_id", ""),
                    "type": link.get("type", ""),
                    "confidence": float(link.get("confidence", 0.0)),
                    "hop": int(link.get("hop", 0)),
                }
            )
            for link in chain_data
        ]

        return CausalTraceResponse(
            root_entity=RootEntity(
                id=root.get("id", entity_id),
                name=root.get("name", "unknown"),
            ),
            chain=chain,
            total_hops=int(result.get("total_hops", 0)),
            max_confidence=float(result.get("max_confidence", 0.0)),
            min_confidence=float(result.get("min_confidence", 0.0)),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "causal_trace failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        return CausalTraceResponse(
            root_entity=RootEntity(id=entity_id, name="unknown"),
            error=str(exc),
        )


@router.get("/network/{entity_id}", response_model=NetworkResponse)
async def entity_network_endpoint(
    entity_id: str,
    layers: Optional[str] = Query(
        default=None,
        description="Comma-separated graph layers to include (e.g. entity,causal). Omit for all.",
    ),
    max_depth: int = Query(
        default=2,
        ge=1,
        le=5,
        description="Maximum number of hops",
    ),
    min_confidence: float = Query(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    ),
    _: bool = Depends(verify_api_key),
) -> NetworkResponse:
    """
    Get entity network graph for visualization.

    Returns nodes and edges connected to the starting entity across
    specified graph layers.
    """
    try:
        from uuid import UUID as _UUID

        try:
            _UUID(entity_id)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid entity_id: {entity_id}")

        # Parse comma-separated layers
        layer_list: Optional[List[str]] = None
        if layers:
            layer_list = [l.strip() for l in layers.split(",") if l.strip()]

        # Lazy import to avoid circular deps
        from backend.magma.query import entity_network

        result = await entity_network(
            entity_id=entity_id,
            layers=layer_list,
            max_depth=max_depth,
            min_confidence=min_confidence,
        )

        root_data = result.get("root_entity", {})
        nodes_data = result.get("nodes", [])
        edges_data = result.get("edges", [])
        stats_data = result.get("statistics", {})

        nodes = [
            NetworkNode(
                id=n.get("id", ""),
                name=n.get("name", "unknown"),
                type=n.get("type", ""),
                domain=n.get("domain", ""),
            )
            for n in nodes_data
        ]

        edges = [
            NetworkEdge(
                source=e.get("source", ""),
                target=e.get("target", ""),
                type=e.get("type", ""),
                layer=e.get("layer", "entity"),
                confidence=float(e.get("confidence", 0.0)),
                hop=int(e.get("hop", 0)),
            )
            for e in edges_data
        ]

        return NetworkResponse(
            root_entity=RootEntityFull(
                id=root_data.get("id", entity_id),
                name=root_data.get("name", "unknown"),
                type=root_data.get("type", ""),
                domain=root_data.get("domain", ""),
            ),
            nodes=nodes,
            edges=edges,
            statistics=NetworkStatistics(
                total_nodes=int(stats_data.get("total_nodes", 0)),
                total_edges=int(stats_data.get("total_edges", 0)),
                max_hop=int(stats_data.get("max_hop", 0)),
                layers_found=stats_data.get("layers_found", []),
            ),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "entity_network failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        return NetworkResponse(
            root_entity=RootEntityFull(id=entity_id, name="unknown"),
            error=str(exc),
        )


@router.get(
    "/relationships/{entity_id}",
    response_model=EntityRelationshipsResponse,
)
async def get_relationships_endpoint(
    entity_id: str,
    direction: Direction = Query(
        default=Direction.BOTH,
        description="Relationship direction: outgoing, incoming, or both",
    ),
    relationship_type: Optional[str] = Query(
        default=None,
        description="Filter by relationship type",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum relationships to return",
    ),
    min_confidence: float = Query(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold",
    ),
    _: bool = Depends(verify_api_key),
) -> EntityRelationshipsResponse:
    """
    Get direct relationships for an entity (1-hop only).

    Simpler than full traversal -- useful for UI display.
    Queries the entity_relationships table directly.
    """
    try:
        from uuid import UUID as _UUID

        try:
            _UUID(entity_id)
        except ValueError:
            raise HTTPException(status_code=422, detail=f"Invalid entity_id: {entity_id}")

        # Lazy import to avoid circular deps
        from backend.magma.query import get_entity_relationships

        relationships = await get_entity_relationships(
            entity_id=entity_id,
            direction=direction,
            relationship_type=relationship_type,
            limit=limit,
            min_confidence=min_confidence,
        )

        items = [RelationshipItem(**rel) for rel in relationships]

        return EntityRelationshipsResponse(
            entity_id=entity_id,
            relationships=items,
            count=len(items),
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "get_relationships failed for entity %s: %s",
            entity_id,
            exc,
            exc_info=True,
        )
        return EntityRelationshipsResponse(
            entity_id=entity_id,
            error=str(exc),
        )
