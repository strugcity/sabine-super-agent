"""
Test Multi-hop Graph Query Security and Performance
===================================================

Tests for the security, performance, and correctness of multi-hop graph queries
in the Context Retrieval Engine.

Addresses the following concerns:
1. Tenant isolation - ensure no cross-tenant data leaks
2. Performance - verify parallel execution reduces latency
3. Circular graph handling - ensure deduplication works correctly
4. UUID validation - prevent malformed inputs from reaching backend
5. Error handling - ensure failures are logged appropriately
"""

import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from lib.agent.retrieval import _fetch_entity_relationships
from lib.db.models import DomainEnum, Entity, EntityStatus

logger = logging.getLogger(__name__)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_entities():
    """Create mock entities with valid UUIDs."""
    return [
        Entity(
            id=UUID("550e8400-e29b-41d4-a716-446655440000"),
            name="Entity A",
            type="project",
            domain=DomainEnum.WORK,
            status=EntityStatus.ACTIVE,
        ),
        Entity(
            id=UUID("550e8400-e29b-41d4-a716-446655440001"),
            name="Entity B",
            type="person",
            domain=DomainEnum.WORK,
            status=EntityStatus.ACTIVE,
        ),
        Entity(
            id=UUID("550e8400-e29b-41d4-a716-446655440002"),
            name="Entity C",
            type="event",
            domain=DomainEnum.WORK,
            status=EntityStatus.ACTIVE,
        ),
    ]


@pytest.fixture
def mock_entities_invalid():
    """Create mock entities with invalid IDs."""
    entity = Entity(
        name="Invalid Entity",
        type="project",
        domain=DomainEnum.WORK,
        status=EntityStatus.ACTIVE,
    )
    # Manually set an invalid ID
    entity.id = "not-a-uuid"  # type: ignore
    return [entity]


# =============================================================================
# Test 1: UUID Validation (Security)
# =============================================================================

@pytest.mark.asyncio
async def test_uuid_validation_prevents_injection(mock_entities_invalid):
    """
    Test that invalid UUIDs are rejected and logged.
    
    This prevents malformed inputs from reaching backend functions that may
    construct database queries. Proper UUID validation ensures only well-formed
    identifiers are passed downstream.
    """
    with patch("lib.agent.retrieval.get_entity_relationships") as mock_get_rels:
        mock_get_rels.return_value = []
        
        with patch("lib.agent.retrieval.causal_trace") as mock_causal:
            with patch("lib.agent.retrieval.entity_network") as mock_network:
                with patch("lib.agent.retrieval.logger") as mock_logger:
                    result = await _fetch_entity_relationships(
                        entities=mock_entities_invalid,
                        enable_multi_hop=True,
                    )
                    
                    # Multi-hop functions should NOT be called with invalid UUID
                    mock_causal.assert_not_called()
                    mock_network.assert_not_called()
                    
                    # Should log an error about invalid UUID
                    assert mock_logger.error.called
                    error_call = mock_logger.error.call_args[0][0]
                    assert "Invalid entity ID format" in error_call


# =============================================================================
# Test 2: Parallel Execution Performance
# =============================================================================

@pytest.mark.asyncio
async def test_parallel_execution_reduces_latency(mock_entities):
    """
    Test that multi-hop queries execute in parallel, not serially.
    
    With 3 entities and 500ms per query, serial execution would take 3000ms.
    Parallel execution should take ~500ms (the slowest query).
    """
    # Mock slow database calls
    async def slow_causal_trace(*args, **kwargs):
        await asyncio.sleep(0.5)  # 500ms
        return {
            "root_entity": {"id": str(args[0]), "name": "Test"},
            "chain": [],
            "total_hops": 0,
            "max_confidence": 0.0,
            "min_confidence": 0.0,
        }

    async def slow_entity_network(*args, **kwargs):
        await asyncio.sleep(0.5)  # 500ms
        return {
            "root_entity": {"id": str(args[0]), "name": "Test"},
            "nodes": [],
            "edges": [],
            "statistics": {"total_nodes": 0, "total_edges": 0},
        }

    with patch("lib.agent.retrieval.get_entity_relationships") as mock_get_rels:
        mock_get_rels.return_value = []
        
        with patch("lib.agent.retrieval.causal_trace", side_effect=slow_causal_trace):
            with patch("lib.agent.retrieval.entity_network", side_effect=slow_entity_network):
                start_time = datetime.now(timezone.utc)
                
                result = await _fetch_entity_relationships(
                    entities=mock_entities,
                    enable_multi_hop=True,
                )
                
                end_time = datetime.now(timezone.utc)
                elapsed_ms = (end_time - start_time).total_seconds() * 1000
                
                # Should take ~500ms (parallel) not ~3000ms (serial)
                # Allow 1000ms buffer for overhead
                assert elapsed_ms < 1500, (
                    f"Expected parallel execution (~500ms), got {elapsed_ms:.0f}ms. "
                    "Queries may be executing serially."
                )
                
                logger.info(f"✓ Parallel execution completed in {elapsed_ms:.0f}ms")


# =============================================================================
# Test 3: Circular Graph Handling
# =============================================================================

@pytest.mark.asyncio
async def test_circular_graph_deduplication(mock_entities):
    """
    Test that circular relationships (A -> B -> A) are deduplicated correctly.
    
    This prevents infinite loops and duplicate entries in the result set.
    """
    # Create circular graph: A -> B -> A
    entity_a_id = str(mock_entities[0].id)
    entity_b_id = str(mock_entities[1].id)
    
    circular_causal_result = {
        "root_entity": {"id": entity_a_id, "name": "Entity A"},
        "chain": [
            {
                "from_id": entity_a_id,
                "to_id": entity_b_id,
                "from": "Entity A",
                "to": "Entity B",
                "type": "causes",
                "confidence": 0.9,
                "hop": 1,
            },
            {
                "from_id": entity_b_id,
                "to_id": entity_a_id,
                "from": "Entity B",
                "to": "Entity A",
                "type": "causes",
                "confidence": 0.8,
                "hop": 2,
            },
            # Duplicate of first relationship (should be deduplicated)
            {
                "from_id": entity_a_id,
                "to_id": entity_b_id,
                "from": "Entity A",
                "to": "Entity B",
                "type": "causes",
                "confidence": 0.9,
                "hop": 3,
            },
        ],
        "total_hops": 3,
    }

    with patch("lib.agent.retrieval.get_entity_relationships") as mock_get_rels:
        mock_get_rels.return_value = []
        
        with patch("lib.agent.retrieval.causal_trace") as mock_causal:
            mock_causal.return_value = circular_causal_result
            
            with patch("lib.agent.retrieval.entity_network") as mock_network:
                mock_network.return_value = {
                    "root_entity": {"id": entity_a_id, "name": "Entity A"},
                    "nodes": [],
                    "edges": [],
                    "statistics": {},
                }
                
                result = await _fetch_entity_relationships(
                    entities=mock_entities[:1],  # Only use first entity
                    enable_multi_hop=True,
                )
                
                # Should have exactly 2 unique relationships (A->B and B->A)
                # Not 3 (the duplicate should be removed)
                relationship_keys = [
                    (r["source_entity_id"], r["target_entity_id"], r["relationship_type"])
                    for r in result
                ]
                
                assert len(relationship_keys) == 2, (
                    f"Expected 2 unique relationships, got {len(relationship_keys)}. "
                    f"Deduplication may not be working correctly."
                )
                
                # Verify both directions exist
                assert (entity_a_id, entity_b_id, "causes") in relationship_keys
                assert (entity_b_id, entity_a_id, "causes") in relationship_keys
                
                logger.info("✓ Circular graph handled correctly with deduplication")


# =============================================================================
# Test 4: Tenant Isolation (Critical Security Test)
# =============================================================================

@pytest.mark.asyncio
async def test_tenant_isolation_warning():
    """
    Test that documents the CRITICAL security issue: tenant isolation is not enforced.
    
    This test documents that causal_trace and entity_network do NOT receive user_id,
    which means they run with Service Role privileges and could leak data across tenants.
    
    TODO: This test should FAIL once tenant isolation is properly implemented.
    """
    mock_entity = Entity(
        id=UUID("550e8400-e29b-41d4-a716-446655440000"),
        name="Tenant A Entity",
        type="project",
        domain=DomainEnum.WORK,
        status=EntityStatus.ACTIVE,
    )

    with patch("lib.agent.retrieval.get_entity_relationships") as mock_get_rels:
        mock_get_rels.return_value = []
        
        with patch("lib.agent.retrieval.causal_trace") as mock_causal:
            mock_causal.return_value = {
                "root_entity": {"id": str(mock_entity.id), "name": "Test"},
                "chain": [],
                "total_hops": 0,
            }
            
            with patch("lib.agent.retrieval.entity_network") as mock_network:
                mock_network.return_value = {
                    "root_entity": {"id": str(mock_entity.id), "name": "Test"},
                    "nodes": [],
                    "edges": [],
                    "statistics": {},
                }
                
                await _fetch_entity_relationships(
                    entities=[mock_entity],
                    enable_multi_hop=True,
                )
                
                # Verify that causal_trace is called WITHOUT user_id
                mock_causal.assert_called()
                call_kwargs = mock_causal.call_args[1]
                
                # CRITICAL: This assertion documents the security issue
                # It should FAIL once proper tenant isolation is implemented
                assert "user_id" not in call_kwargs, (
                    "EXPECTED BEHAVIOR (security issue): causal_trace is called "
                    "without user_id, running with Service Role privileges. "
                    "If this assertion fails, tenant isolation has been implemented!"
                )
                
                logger.warning(
                    "⚠️  SECURITY ISSUE DOCUMENTED: Multi-hop queries do not enforce "
                    "tenant isolation. They run with Service Role privileges and could "
                    "leak data across tenant boundaries."
                )


# =============================================================================
# Test 5: Error Handling and Logging
# =============================================================================

@pytest.mark.asyncio
async def test_error_logging_at_warning_level(mock_entities):
    """
    Test that multi-hop failures are logged at WARNING level, not DEBUG.
    
    This ensures production visibility when the graph database has issues.
    """
    with patch("lib.agent.retrieval.get_entity_relationships") as mock_get_rels:
        mock_get_rels.return_value = []
        
        with patch("lib.agent.retrieval.causal_trace") as mock_causal:
            mock_causal.side_effect = Exception("Database connection timeout")
            
            with patch("lib.agent.retrieval.entity_network") as mock_network:
                mock_network.side_effect = Exception("Database connection timeout")
                
                with patch("lib.agent.retrieval.logger") as mock_logger:
                    result = await _fetch_entity_relationships(
                        entities=mock_entities,
                        enable_multi_hop=True,
                    )
                    
                    # Should log at WARNING level for visibility
                    assert mock_logger.warning.called
                    
                    # Should still return empty results (graceful degradation)
                    assert result == []
                    
                    logger.info("✓ Errors logged at WARNING level for production visibility")


# =============================================================================
# Test 6: Bounded Set Growth
# =============================================================================

@pytest.mark.asyncio
async def test_bounded_set_growth(mock_entities):
    """
    Test that seen_keys set growth is bounded to prevent memory issues.
    
    In dense graphs, unlimited set growth could cause memory spikes.
    """
    # Create a large graph that would exceed MAX_SEEN_KEYS
    large_chain = []
    for i in range(2000):  # More than MAX_SEEN_KEYS (1000)
        large_chain.append({
            "from_id": f"entity-{i}",
            "to_id": f"entity-{i+1}",
            "from": f"Entity {i}",
            "to": f"Entity {i+1}",
            "type": "related_to",
            "confidence": 0.5,
            "hop": i + 1,
        })

    with patch("lib.agent.retrieval.get_entity_relationships") as mock_get_rels:
        mock_get_rels.return_value = []
        
        with patch("lib.agent.retrieval.causal_trace") as mock_causal:
            mock_causal.return_value = {
                "root_entity": {"id": str(mock_entities[0].id), "name": "Test"},
                "chain": large_chain,
                "total_hops": 2000,
            }
            
            with patch("lib.agent.retrieval.entity_network") as mock_network:
                mock_network.return_value = {
                    "root_entity": {"id": str(mock_entities[0].id), "name": "Test"},
                    "nodes": [],
                    "edges": [],
                    "statistics": {},
                }
                
                with patch("lib.agent.retrieval.logger") as mock_logger:
                    result = await _fetch_entity_relationships(
                        entities=mock_entities[:1],
                        enable_multi_hop=True,
                    )
                    
                    # Should stop at MAX_SEEN_KEYS (1000)
                    assert len(result) <= 1000, (
                        f"Expected max 1000 relationships, got {len(result)}. "
                        "Set growth may not be bounded."
                    )
                    
                    # Should log a warning about hitting the limit
                    assert mock_logger.warning.called
                    warning_msg = str(mock_logger.warning.call_args[0][0])
                    assert "max seen_keys limit" in warning_msg.lower()
                    
                    logger.info("✓ Set growth is properly bounded to prevent memory issues")


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )
    
    # Run tests
    pytest.main([__file__, "-v", "-s"])
