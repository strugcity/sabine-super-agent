"""
MAGMA Graph Relationship Type Taxonomy (PRD 11.2)
==================================================

Defines the canonical relationship types for each of the four graph layers
in the MAGMA (Multi-layered Adaptive Graph Memory Architecture):

  - **entity**:   Direct entity-to-entity structural relations
  - **semantic**: Meaning/topic relationships
  - **temporal**: Time-based sequential relations
  - **causal**:   Cause-effect reasoning chains

Usage:
    from backend.magma.taxonomy import GraphLayer, infer_layer, is_valid_predicate

    layer = infer_layer("works_at")    # -> GraphLayer.ENTITY
    valid = is_valid_predicate("knows") # -> True
"""

from enum import Enum
from typing import Dict, FrozenSet


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
})

SEMANTIC_PREDICATES: FrozenSet[str] = frozenset({
    "related_to",
    "similar_to",
})

TEMPORAL_PREDICATES: FrozenSet[str] = frozenset({
    "preceded_by",
    "happened_during",
})

CAUSAL_PREDICATES: FrozenSet[str] = frozenset({
    "caused_by",
    "led_to",
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
