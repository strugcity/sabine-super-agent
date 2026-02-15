"""
MAGMA Graph Relationship Type Taxonomy (PRD 11.2)
==================================================

Defines the canonical relationship types for each of the four graph layers
in the MAGMA (Multi-layered Adaptive Graph Memory Architecture):

  - **entity**   (18 predicates): Direct entity-to-entity structural relations
  - **semantic**  (5 predicates): Meaning/topic relationships
  - **temporal**  (5 predicates): Time-based sequential relations
  - **causal**    (4 predicates): Cause-effect reasoning chains

Total canonical predicates: 32

Usage:
    from backend.magma.taxonomy import GraphLayer, infer_layer, is_valid_predicate

    layer = infer_layer("works_at")    # -> GraphLayer.ENTITY
    valid = is_valid_predicate("knows") # -> True
"""

import logging
from enum import Enum
from typing import Dict, FrozenSet

logger = logging.getLogger(__name__)


class GraphLayer(str, Enum):
    """The four graph layers in MAGMA (PRD 11.2)."""
    ENTITY = "entity"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    CAUSAL = "causal"


# ---------------------------------------------------------------------------
# Canonical relationship types per layer
# ---------------------------------------------------------------------------

ENTITY_PREDICATES: FrozenSet[str] = frozenset({
    "works_at",
    "lives_in",
    "married_to",
    "manages",
    "part_of",
    "knows",
    "reports_to",
    "collaborates_with",
    "founded",
    "attended",
    "located_in",
    "member_of",
    "owns",
    "parent_of",
    "child_of",
    "sibling_of",
    "prefers",
    "assigned_to",
})

SEMANTIC_PREDICATES: FrozenSet[str] = frozenset({
    "related_to",
    "similar_to",
    "contradicts",
    "supports",
    "instance_of",
})

TEMPORAL_PREDICATES: FrozenSet[str] = frozenset({
    "preceded_by",
    "happened_during",
    "scheduled_for",
    "started_at",
    "deadline_for",
})

CAUSAL_PREDICATES: FrozenSet[str] = frozenset({
    "caused_by",
    "led_to",
    "depends_on",
    "blocked_by",
})

ALL_PREDICATES: FrozenSet[str] = (
    ENTITY_PREDICATES | SEMANTIC_PREDICATES | TEMPORAL_PREDICATES | CAUSAL_PREDICATES
)

LAYER_PREDICATES: Dict[GraphLayer, FrozenSet[str]] = {
    GraphLayer.ENTITY: ENTITY_PREDICATES,
    GraphLayer.SEMANTIC: SEMANTIC_PREDICATES,
    GraphLayer.TEMPORAL: TEMPORAL_PREDICATES,
    GraphLayer.CAUSAL: CAUSAL_PREDICATES,
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def infer_layer(predicate: str) -> GraphLayer:
    """
    Infer the graph layer from a relationship predicate type.

    Searches each layer's predicate set and returns the matching
    :class:`GraphLayer`.  Falls back to ``GraphLayer.ENTITY`` if the
    predicate is not in any canonical set.

    Parameters
    ----------
    predicate : str
        A snake_case relationship type (e.g. ``"works_at"``).

    Returns
    -------
    GraphLayer
        The graph layer this predicate belongs to.
    """
    for layer, predicates in LAYER_PREDICATES.items():
        if predicate in predicates:
            return layer
    logger.warning(
        "Predicate %r not in canonical taxonomy; defaulting to GraphLayer.ENTITY",
        predicate,
    )
    return GraphLayer.ENTITY  # Default fallback


def is_valid_predicate(predicate: str) -> bool:
    """
    Check if a predicate is in the canonical MAGMA taxonomy.

    Parameters
    ----------
    predicate : str
        A snake_case relationship type to validate.

    Returns
    -------
    bool
        ``True`` if the predicate belongs to any graph layer.
    """
    return predicate in ALL_PREDICATES
