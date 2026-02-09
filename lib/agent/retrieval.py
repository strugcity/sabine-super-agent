"""
Context Retrieval Engine - Phase 3: Memory Recall
=================================================

This module implements "The Blender" - the retrieval system that combines
vector search with relational graph queries to provide rich context to the LLM.

Core Capabilities:
1. Vector similarity search for fuzzy memories
2. Entity graph traversal for structured facts
3. Intelligent blending of results
4. Optimized formatting for LLM consumption

Architecture:
- Uses match_memories() SQL function for vector search
- Uses fuzzy text matching for entity retrieval
- Combines results into a clean, hierarchical format
- Caches frequently accessed entities (future optimization)

Owner: @backend-architect-sabine
"""

from lib.agent.memory import get_supabase_client, get_embeddings
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from langchain_openai import OpenAIEmbeddings
from supabase import Client

from lib.db.models import Entity, Memory

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Retrieval parameters
DEFAULT_MEMORY_THRESHOLD = 0.6  # Cosine similarity threshold
DEFAULT_MEMORY_COUNT = 5        # Max memories to retrieve
DEFAULT_ENTITY_LIMIT = 10       # Max entities to retrieve

# Import singleton clients from memory module


# =============================================================================
# Vector Memory Retrieval
# =============================================================================

async def search_similar_memories(
    query_embedding: List[float],
    user_id: Optional[UUID] = None,
    threshold: float = DEFAULT_MEMORY_THRESHOLD,
    limit: int = DEFAULT_MEMORY_COUNT,
    role_filter: Optional[str] = None,
    domain_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Search for memories similar to the query embedding using pgvector.

    Uses the match_memories() PostgreSQL function for efficient vector search.

    Args:
        query_embedding: 1536-dimension query vector
        user_id: Optional user UUID for filtering (multi-tenancy)
        threshold: Similarity threshold (0-1, higher = more similar)
        limit: Maximum number of results
        role_filter: Optional role filter (e.g., "assistant", "backend-architect-sabine").
                     If provided, only returns memories from this role (or legacy memories with no role).
                     If None, returns all memories.
        domain_filter: Optional domain filter (e.g., "work", "personal", "family", "logistics").
                       If provided, only returns memories from this domain.
                       If None, returns all domains.

    Returns:
        List of memory dictionaries with similarity scores

    Example:
        >>> memories = await search_similar_memories(
        ...     query_embedding=[0.1, 0.2, ...],
        ...     threshold=0.7,
        ...     limit=5,
        ...     role_filter="assistant"
        ... )
        >>> memories[0]['similarity']
        0.85
    """
    try:
        supabase = get_supabase_client()

        # Format embedding as pgvector-compatible string: "[0.1, 0.2, ...]"
        pgvector_embedding = f"[{','.join(str(x) for x in query_embedding)}]"

        # Call the match_memories RPC function
        response = supabase.rpc(
            "match_memories",
            {
                "query_embedding": pgvector_embedding,
                "match_threshold": threshold,
                "match_count": limit,
                "user_id_filter": str(user_id) if user_id else None,
                "role_filter": role_filter,
                "domain_filter": domain_filter
            }
        ).execute()

        if not response.data:
            logger.info("No similar memories found")
            return []

        logger.info(f"✓ Found {len(response.data)} similar memories")
        return response.data

    except Exception as e:
        logger.error(f"Vector memory search failed: {e}", exc_info=True)
        return []


# =============================================================================
# Entity Graph Retrieval
# =============================================================================

def extract_keywords(query: str) -> List[str]:
    """
    Extract potential entity names from a query string.

    Uses simple heuristics:
    - Capitalized words (proper nouns)
    - Words longer than 3 characters
    - Removes common stop words

    Args:
        query: Natural language query

    Returns:
        List of potential entity keywords

    Example:
        >>> extract_keywords("What's happening with Jenny and PriceSpider?")
        ['Jenny', 'PriceSpider']
    """
    # Common stop words to ignore
    stop_words = {
        'what', 'when', 'where', 'who', 'why', 'how', 'the', 'a', 'an',
        'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'with', 'about',
        'is', 'are', 'was', 'were', 'been', 'being', 'have', 'has', 'had',
        'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might'
    }

    # Extract words
    words = re.findall(r'\b[A-Za-z]+\b', query)

    # Filter: capitalized OR longer than 3 chars, not stop words
    keywords = [
        word for word in words
        if (word[0].isupper() or len(word) > 3) and word.lower() not in stop_words
    ]

    # Deduplicate while preserving order
    seen = set()
    unique_keywords = []
    for kw in keywords:
        if kw.lower() not in seen:
            seen.add(kw.lower())
            unique_keywords.append(kw)

    logger.info(f"Extracted keywords: {unique_keywords}")
    return unique_keywords


async def search_entities_by_keywords(
    keywords: List[str],
    limit: int = DEFAULT_ENTITY_LIMIT,
    domain_filter: Optional[str] = None
) -> List[Entity]:
    """
    Search for entities that match any of the provided keywords.

    Uses PostgreSQL ILIKE for fuzzy case-insensitive matching.

    Args:
        keywords: List of keywords to search for
        limit: Maximum total entities to return
        domain_filter: Optional domain filter (e.g., "work", "personal", "family", "logistics").
                       If provided, only returns entities from this domain.
                       If None, returns all domains.

    Returns:
        List of matching Entity objects

    Example:
        >>> entities = await search_entities_by_keywords(["Jenny", "PriceSpider"])
        >>> entities[0].name
        'Jenny'
    """
    if not keywords:
        return []

    try:
        supabase = get_supabase_client()

        # Build OR query for all keywords
        # Note: Supabase doesn't support OR in a single query easily,
        # so we'll do multiple queries and deduplicate
        all_entities = []
        seen_ids = set()

        for keyword in keywords:
            query = supabase.table("entities").select("*").ilike(
                "name", f"%{keyword}%"
            ).eq("status", "active")
            
            if domain_filter:
                query = query.eq("domain", domain_filter)
            
            response = query.limit(limit).execute()

            for entity_data in response.data:
                entity_id = entity_data['id']
                if entity_id not in seen_ids:
                    seen_ids.add(entity_id)
                    all_entities.append(Entity(**entity_data))

        logger.info(f"✓ Found {len(all_entities)} matching entities")
        return all_entities[:limit]  # Respect overall limit

    except Exception as e:
        logger.error(f"Entity search failed: {e}", exc_info=True)
        return []


# =============================================================================
# Context Formatting (The Blender)
# =============================================================================

def format_memory_for_context(memory: Dict[str, Any]) -> str:
    """
    Format a single memory for LLM context.

    Args:
        memory: Memory dictionary with content, similarity, created_at

    Returns:
        Formatted string line

    Example:
        >>> format_memory_for_context({
        ...     'content': 'Meeting with Jenny',
        ...     'similarity': 0.85,
        ...     'created_at': '2026-01-29T12:00:00Z'
        ... })
        '- Meeting with Jenny (Jan 29, similarity: 85%)'
    """
    content = memory.get('content', 'Unknown')
    similarity = memory.get('similarity', 0.0)
    created_at = memory.get('created_at', '')

    # Format date
    date_str = ''
    if created_at:
        try:
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            date_str = dt.strftime('%b %d')
        except:
            pass

    # Format similarity as percentage
    sim_pct = int(similarity * 100)

    # Build formatted line
    parts = [f"- {content}"]
    if date_str:
        parts.append(f"({date_str}")
        if sim_pct >= 70:  # Only show similarity if high confidence
            parts[-1] += f", {sim_pct}% match)"
        else:
            parts[-1] += ")"

    return ' '.join(parts)


def format_entity_for_context(entity: Entity) -> str:
    """
    Format a single entity for LLM context.

    Args:
        entity: Entity object

    Returns:
        Formatted string line

    Example:
        >>> format_entity_for_context(Entity(
        ...     name='Jenny',
        ...     type='person',
        ...     domain='work',
        ...     attributes={'role': 'Partner'}
        ... ))
        '- Jenny (Person, Work): Partner at company'
    """
    name = entity.name
    entity_type = entity.type.capitalize()
    domain = entity.domain.value.capitalize()

    # Format attributes
    attrs = []
    if entity.attributes:
        # Common attribute keys to highlight
        priority_keys = ['role', 'title',
                         'deadline', 'status', 'location', 'time']
        for key in priority_keys:
            if key in entity.attributes:
                value = entity.attributes[key]
                if isinstance(value, (str, int, float)):
                    attrs.append(f"{value}")

    # Build formatted line
    parts = [f"- {name} ({entity_type}, {domain})"]
    if attrs:
        parts.append(": " + ", ".join(attrs))

    return ''.join(parts)


def blend_context(
    memories: List[Dict[str, Any]],
    entities: List[Entity],
    query: str,
    domain_filter: Optional[str] = None
) -> str:
    """
    Blend memories and entities into a clean, hierarchical context string.

    This is "The Blender" - it combines fuzzy vector memories with structured
    entity data into a format optimized for LLM consumption.

    Args:
        memories: List of similar memory dictionaries
        entities: List of relevant Entity objects
        query: Original user query (for context)
        domain_filter: Optional domain filter for labeling
                       If provided, adds domain labels to section headers.

    Returns:
        Formatted context string ready for LLM system prompt

    Example:
        >>> context = blend_context(memories, entities, "What's up with Jenny?")
        >>> print(context)
        [CONTEXT FOR: "What's up with Jenny?"]

        [RELEVANT MEMORIES]
        - Meeting with Jenny about PriceSpider (Jan 29, 85% match)
        - Discussed contract terms (Jan 28)

        [RELATED ENTITIES]
        - Jenny (Person, Work): Partner at PriceSpider
        - PriceSpider Contract (Document, Work): Due Feb 15
    """
    lines = []

    # Generate domain labels if filtering is active
    domain_label = f" ({domain_filter.upper()} DOMAIN)" if domain_filter else ""
    domain_prefix = f" {domain_filter.upper()}" if domain_filter else ""

    # Header
    lines.append(f'[CONTEXT FOR: "{query}"{domain_label}]')
    lines.append("")

    # Memories section
    memory_header = f"[RELEVANT{domain_prefix} MEMORIES]"
    if memories:
        lines.append(memory_header)
        for memory in memories:
            lines.append(format_memory_for_context(memory))
        lines.append("")
    else:
        lines.append(memory_header)
        lines.append("- No relevant memories found")
        lines.append("")

    # Entities section
    entity_header = f"[RELATED{domain_prefix} ENTITIES]"
    if entities:
        lines.append(entity_header)
        for entity in entities:
            lines.append(format_entity_for_context(entity))
    else:
        lines.append(entity_header)
        lines.append("- No related entities found")

    return '\n'.join(lines)


# =============================================================================
# Main Retrieval Function
# =============================================================================

async def retrieve_context(
    user_id: UUID,
    query: str,
    memory_threshold: float = DEFAULT_MEMORY_THRESHOLD,
    memory_limit: int = DEFAULT_MEMORY_COUNT,
    entity_limit: int = DEFAULT_ENTITY_LIMIT,
    role_filter: str = "assistant",
    domain_filter: Optional[str] = None
) -> str:
    """
    Retrieve relevant context for a user query by blending vector memories
    and entity graph data.

    This is the main entry point for Phase 3 retrieval. It orchestrates:
    1. Query embedding generation
    2. Vector similarity search for memories
    3. Entity keyword extraction and search
    4. Context blending and formatting

    Args:
        user_id: UUID of the user making the query
        query: Natural language query string
        memory_threshold: Similarity threshold for memory search (0-1)
        memory_limit: Max memories to retrieve
        entity_limit: Max entities to retrieve
        role_filter: Filter memories by agent role (e.g., "assistant", "backend-architect-sabine").
                     Defaults to "assistant". Memories without a role field (legacy) are included
                     for backward compatibility.
        domain_filter: Optional domain filter (e.g., "work", "personal", "family", "logistics").
                       If provided, only returns memories and entities from this domain.
                       If None, returns all domains (backward compatible).

    Returns:
        Formatted context string ready for LLM system prompt

    Example:
        >>> context = await retrieve_context(
        ...     user_id=UUID("..."),
        ...     query="What's happening with the PriceSpider contract?",
        ...     role_filter="assistant"
        ... )
        >>> print(context)
        [CONTEXT FOR: "What's happening with the PriceSpider contract?"]

        [RELEVANT MEMORIES]
        - Meeting with Jenny about PriceSpider (Jan 29)

        [RELATED ENTITIES]
        - PriceSpider Contract (Document, Work): Due Feb 15
        - Jenny (Person, Work): Partner at company
    """
    logger.info(f"🔍 Retrieving context for query: {query}")
    start_time = datetime.utcnow()

    try:
        # STEP 1: Generate query embedding
        logger.info("Step 1: Generating query embedding...")
        embeddings_client = get_embeddings()
        query_embedding = await embeddings_client.aembed_query(query)

        if len(query_embedding) != 1536:
            raise ValueError(
                f"Expected 1536-dim embedding, got {len(query_embedding)}")

        # STEP 2: Vector search for similar memories
        logger.info("Step 2: Searching similar memories...")
        memories = await search_similar_memories(
            query_embedding=query_embedding,
            user_id=user_id,
            threshold=memory_threshold,
            limit=memory_limit,
            role_filter=role_filter,
            domain_filter=domain_filter
        )

        # STEP 3: Extract keywords and search entities
        logger.info("Step 3: Extracting keywords and searching entities...")
        keywords = extract_keywords(query)
        entities = await search_entities_by_keywords(
            keywords=keywords,
            limit=entity_limit,
            domain_filter=domain_filter
        )

        # STEP 4: Blend into formatted context
        logger.info("Step 4: Blending context...")
        context = blend_context(
            memories=memories,
            entities=entities,
            query=query,
            domain_filter=domain_filter
        )

        # Calculate timing
        end_time = datetime.utcnow()
        elapsed_ms = int((end_time - start_time).total_seconds() * 1000)

        logger.info(
            f"✓ Context retrieval complete in {elapsed_ms}ms - "
            f"{len(memories)} memories, {len(entities)} entities"
        )

        return context

    except Exception as e:
        logger.error(f"Context retrieval failed: {e}", exc_info=True)
        # Return graceful fallback
        return f'[CONTEXT FOR: "{query}"]\n\n[ERROR]\n- Unable to retrieve context: {str(e)}'


# =============================================================================
# Utility Functions
# =============================================================================

async def get_entity_by_id(entity_id: UUID) -> Optional[Entity]:
    """
    Retrieve a specific entity by ID.

    Args:
        entity_id: UUID of the entity

    Returns:
        Entity object or None if not found
    """
    try:
        supabase = get_supabase_client()
        response = supabase.table("entities").select(
            "*").eq("id", str(entity_id)).execute()

        if response.data and len(response.data) > 0:
            return Entity(**response.data[0])

        return None

    except Exception as e:
        logger.error(f"Failed to get entity {entity_id}: {e}")
        return None


async def get_memory_by_id(memory_id: UUID) -> Optional[Dict[str, Any]]:
    """
    Retrieve a specific memory by ID.

    Args:
        memory_id: UUID of the memory

    Returns:
        Memory dictionary or None if not found
    """
    try:
        supabase = get_supabase_client()
        response = supabase.table("memories").select(
            "*").eq("id", str(memory_id)).execute()

        if response.data and len(response.data) > 0:
            return response.data[0]

        return None

    except Exception as e:
        logger.error(f"Failed to get memory {memory_id}: {e}")
        return None


# =============================================================================
# Cross-Context Intelligence
# =============================================================================

def find_overlapping_entities(
    primary: List[Entity], cross: List[Entity]
) -> List[tuple]:
    """
    Find entities with similar names across both domain lists.
    
    Uses exact case-insensitive string matching. This approach may miss
    variations like "Mike Smith" vs "Michael Smith" but avoids false positives.
    
    TODO: Consider implementing fuzzy string matching (e.g., Levenshtein distance)
    for more robust entity matching across domains.
    """
    overlaps = []
    for p_entity in primary:
        for c_entity in cross:
            if p_entity.name.lower() == c_entity.name.lower():
                overlaps.append((p_entity, c_entity))
    return overlaps


def format_cross_context_advisory(
    cross_memories: List[Dict[str, Any]],
    cross_entities: List[Entity],
    shared_entities: List[tuple],
    other_domain: str,
) -> str:
    """Format cross-context findings into a compact advisory."""
    lines = ["[CROSS-CONTEXT ADVISORY]"]
    if shared_entities:
        lines.append("")
        lines.append("Shared Contacts/Entities (appear in both domains):")
        for primary_e, cross_e in shared_entities:
            lines.append(
                f"- {primary_e.name}: {primary_e.domain.value}/{primary_e.type} "
                f"AND {cross_e.domain.value}/{cross_e.type}"
            )
    if cross_memories:
        lines.append("")
        lines.append(f"Related {other_domain.upper()} memories:")
        for mem in cross_memories[:3]:
            content = mem.get("content", "Unknown")
            lines.append(f"- {content}")
    if cross_entities and not shared_entities:
        lines.append("")
        lines.append(f"Related {other_domain.upper()} entities:")
        for entity in cross_entities[:3]:
            lines.append(format_entity_for_context(entity))
    return "\n".join(lines)


async def cross_context_scan(
    user_id: UUID,
    query: str,
    primary_domain: str,
    memory_limit: int = 3,
    entity_limit: int = 5,
) -> str:
    """
    Scan the opposite domain for potential conflicts or overlaps.
    Returns a compact advisory string for the LLM.

    Use cases:
    - Work meeting at 2 PM conflicts with personal dentist at 2:30 PM
    - Coworker Jenny also appears as a personal friend
    - Work travel overlapping with custody weekend
    
    Args:
        user_id: User UUID
        query: The query string to search for
        primary_domain: The primary domain ("work" or "personal")
        memory_limit: Max memories to retrieve from other domain
        entity_limit: Max entities to retrieve per domain
        
    Returns:
        Formatted cross-context advisory string (empty if no overlaps found)
    """
    other_domain = "personal" if primary_domain == "work" else "work"

    try:
        embeddings_client = get_embeddings()
        query_embedding = await embeddings_client.aembed_query(query)

        cross_memories = await search_similar_memories(
            query_embedding=query_embedding,
            user_id=user_id,
            threshold=0.65,
            limit=memory_limit,
            role_filter="assistant",
            domain_filter=other_domain,
        )

        keywords = extract_keywords(query)
        # TODO: Consider adding user_id parameter to search_entities_by_keywords
        # for multi-tenant support (currently entities are shared across user context)
        cross_entities = await search_entities_by_keywords(
            keywords=keywords, limit=entity_limit, domain_filter=other_domain,
        )
        primary_entities = await search_entities_by_keywords(
            keywords=keywords, limit=entity_limit, domain_filter=primary_domain,
        )
        shared_entities = find_overlapping_entities(primary_entities, cross_entities)

        if not cross_memories and not cross_entities and not shared_entities:
            return ""

        return format_cross_context_advisory(
            cross_memories, cross_entities, shared_entities, other_domain
        )
    except Exception as e:
        logger.warning(f"Cross-context scan failed: {e}")
        return ""


# =============================================================================
# Testing / Example Usage
# =============================================================================

async def _test_retrieval():
    """Test the retrieval pipeline with sample queries."""
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    test_queries = [
        "What's happening with Jenny?",
        "Tell me about the PriceSpider contract",
        "What meetings do I have coming up?",
        "What do I need to do this week?"
    ]

    for query in test_queries:
        print(f"\n{'=' * 70}")
        print(f"Query: {query}")
        print('=' * 70)

        context = await retrieve_context(
            user_id=test_user_id,
            query=query
        )

        print(context)
        print()


if __name__ == "__main__":
    import asyncio

    # Enable logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    # Run test
    asyncio.run(_test_retrieval())
