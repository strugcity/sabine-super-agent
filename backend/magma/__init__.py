"""
MAGMA (Multi-layered Adaptive Graph Memory Architecture)
=========================================================

Implements the four-layer graph architecture (PRD 11.2) for
relationship storage and retrieval:

  - entity:   Direct entity-to-entity structural relations
  - semantic: Meaning/topic relationships
  - temporal: Time-based sequential relations
  - causal:   Cause-effect reasoning chains

Submodules:
  - taxonomy: Canonical relationship type constants per graph layer
  - store:    Persist extracted relationships to entity_relationships table
"""

from backend.magma.taxonomy import (
    ALL_PREDICATES,
    CAUSAL_PREDICATES,
    ENTITY_PREDICATES,
    GraphLayer,
    LAYER_PREDICATES,
    SEMANTIC_PREDICATES,
    TEMPORAL_PREDICATES,
    infer_layer,
    is_valid_predicate,
)

__all__ = [
    "GraphLayer",
    "ENTITY_PREDICATES",
    "SEMANTIC_PREDICATES",
    "TEMPORAL_PREDICATES",
    "CAUSAL_PREDICATES",
    "ALL_PREDICATES",
    "LAYER_PREDICATES",
    "infer_layer",
    "is_valid_predicate",
]
