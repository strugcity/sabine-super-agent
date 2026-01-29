"""
Memory Ingestion Pipeline - Phase 2: Context Engine
====================================================

This module implements "The Active Listener" - Feature A from the Context Engine PRD.

Core Capabilities:
1. LLM-powered entity extraction from natural language
2. Automatic embedding generation (text-embedding-3-small)
3. Fuzzy entity matching and intelligent merge logic
4. Memory storage with entity linking

Architecture:
- Uses Claude 3.5 Sonnet for structured extraction
- Uses text-embedding-3-small for vector embeddings (1536d)
- Supabase for persistence (entities + memories tables)
- Full async/await patterns for performance

Owner: @backend-architect-sabine
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_anthropic import ChatAnthropic
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import OpenAIEmbeddings
from pydantic import BaseModel, Field
from supabase import Client, create_client

from lib.db.models import (
    DomainEnum,
    Entity,
    EntityCreate,
    Memory,
    MemoryCreate,
)

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # Still needed for embeddings
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Initialize clients
_supabase_client: Optional[Client] = None
_llm: Optional[ChatAnthropic] = None
_embeddings: Optional[OpenAIEmbeddings] = None


def get_supabase_client() -> Client:
    """Get or create Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        logger.info("✓ Supabase client initialized for memory ingestion")
    return _supabase_client


def get_llm() -> ChatAnthropic:
    """Get or create LLM client singleton (Claude 3.5 Sonnet for extraction)."""
    global _llm
    if _llm is None:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY must be set")
        _llm = ChatAnthropic(
            model="claude-3-5-sonnet-latest",
            temperature=0.0,  # Deterministic extraction
            anthropic_api_key=ANTHROPIC_API_KEY,
        )
        logger.info("✓ Claude 3.5 Sonnet initialized for entity extraction")
    return _llm


def get_embeddings() -> OpenAIEmbeddings:
    """Get or create embeddings client singleton (text-embedding-3-small)."""
    global _embeddings
    if _embeddings is None:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY must be set")
        _embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small",  # 1536 dimensions
            openai_api_key=OPENAI_API_KEY,
        )
        logger.info("✓ text-embedding-3-small initialized")
    return _embeddings


# =============================================================================
# Extraction Schema
# =============================================================================

class ExtractedEntity(BaseModel):
    """Schema for a single extracted entity."""
    name: str = Field(
        description="Entity name (e.g., 'Baseball Game', 'Q1 Launch')")
    type: str = Field(
        description="Entity type: project, person, event, location, document, etc.")
    domain: DomainEnum = Field(
        description="Domain classification: work, family, personal, or logistics")
    attributes: Dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value pairs of entity attributes (deadline, time, team, etc.)"
    )


class ExtractedContext(BaseModel):
    """Output schema for LLM entity extraction."""
    extracted_entities: List[ExtractedEntity] = Field(
        default_factory=list,
        description="List of entities mentioned in the text"
    )
    core_memory: str = Field(
        description="A concise summary of the context for vector search"
    )
    domain: DomainEnum = Field(
        description="Primary domain of the message"
    )


# =============================================================================
# The Extraction Chain
# =============================================================================

async def extract_context(text: str) -> ExtractedContext:
    """
    Use Claude 3.5 Sonnet to extract structured entities and context from raw text.

    This is the "Active Listener" - it understands natural language and converts
    it into structured knowledge graph components.

    Args:
        text: Raw user message or content

    Returns:
        ExtractedContext with entities, core memory, and domain classification

    Example:
        >>> result = await extract_context("Baseball game moved to 5 PM Saturday")
        >>> result.extracted_entities[0].name
        'Baseball Game'
        >>> result.extracted_entities[0].type
        'event'
        >>> result.domain
        'family'
    """
    llm = get_llm()

    # Setup output parser
    parser = PydanticOutputParser(pydantic_object=ExtractedContext)

    # Prompt template
    prompt = ChatPromptTemplate.from_messages([
        ("system", """You are a context extraction AI for a personal assistant.

Your job is to analyze user messages and extract:
1. **Entities**: Concrete "nouns" (Projects, People, Events, Locations, Documents)
2. **Core Memory**: A concise summary suitable for vector search
3. **Domain**: The primary context domain

**Domain Guidelines:**
- work: Professional projects, meetings, deadlines, colleagues
- family: Kids, relatives, family events, household matters
- personal: Hobbies, health, personal goals, friends
- logistics: Travel, schedules, appointments, errands

**Entity Guidelines:**
- Extract ONLY concrete, trackable entities (not abstract concepts)
- Include relevant attributes (dates, times, people involved, status)
- Be specific with names (e.g., "Q1 Product Launch" not "a project")

**Examples:**

Input: "Baseball game moved to 5 PM Saturday"
Output:
- Entity: name="Baseball Game", type="event", domain="family", attributes={{"time": "5 PM", "day": "Saturday", "status": "rescheduled"}}
- Core Memory: "Baseball game rescheduled to 5 PM on Saturday"
- Domain: "family"

Input: "Told Alice to review the Q1 budget deck by Friday"
Output:
- Entity 1: name="Q1 Budget Deck", type="document", domain="work", attributes={{"deadline": "Friday", "reviewer": "Alice"}}
- Entity 2: name="Alice", type="person", domain="work", attributes={{"role": "reviewer"}}
- Core Memory: "Q1 budget deck needs review by Alice before Friday"
- Domain: "work"

{format_instructions}
"""),
        ("human", "{text}")
    ])

    # Format the prompt
    formatted_prompt = prompt.format_messages(
        text=text,
        format_instructions=parser.get_format_instructions()
    )

    # Run extraction
    try:
        response = await llm.ainvoke(formatted_prompt)
        result = parser.parse(response.content)
        logger.info(
            f"✓ Extracted {len(result.extracted_entities)} entities from text")
        return result
    except Exception as e:
        logger.error(f"Entity extraction failed: {e}", exc_info=True)
        # Fallback: Return generic memory with no entities
        return ExtractedContext(
            extracted_entities=[],
            core_memory=text[:500],  # Truncate long text
            domain=DomainEnum.PERSONAL
        )


# =============================================================================
# Entity Management
# =============================================================================

async def find_similar_entity(
    name: str,
    entity_type: str,
    domain: DomainEnum,
    supabase: Client
) -> Optional[Entity]:
    """
    Fuzzy match existing entities by name, type, and domain.

    Uses PostgreSQL's ILIKE for case-insensitive partial matching.
    This prevents duplicate entities when users refer to the same thing
    with slight variations (e.g., "Baseball Game" vs "baseball game").

    Args:
        name: Entity name to search for
        entity_type: Entity type (project, person, event, etc.)
        domain: Domain enum
        supabase: Supabase client

    Returns:
        Matching Entity or None if not found
    """
    try:
        # Case-insensitive partial match on name, exact match on type and domain
        response = supabase.table("entities").select("*").ilike(
            "name", f"%{name}%"
        ).eq("type", entity_type).eq("domain", domain.value).eq(
            "status", "active"
        ).limit(1).execute()

        if response.data and len(response.data) > 0:
            entity_data = response.data[0]
            logger.info(
                f"✓ Found existing entity: {entity_data['name']} (ID: {entity_data['id']})")
            return Entity(**entity_data)

        return None

    except Exception as e:
        logger.error(f"Entity search failed: {e}", exc_info=True)
        return None


async def merge_entity_attributes(
    existing: Entity,
    new_attributes: Dict[str, Any],
    supabase: Client
) -> Entity:
    """
    Merge new attributes into existing entity (JSONB merge).

    This is smart merging - new keys are added, existing keys are updated,
    but we don't delete keys that aren't mentioned in the new data.

    Args:
        existing: Existing entity from DB
        new_attributes: New attributes to merge in
        supabase: Supabase client

    Returns:
        Updated Entity
    """
    try:
        # Merge attributes (new overwrites existing for same keys)
        merged_attributes = {**existing.attributes, **new_attributes}

        # Update in database
        response = supabase.table("entities").update({
            "attributes": merged_attributes,
            "updated_at": datetime.utcnow().isoformat()
        }).eq("id", str(existing.id)).execute()

        if response.data and len(response.data) > 0:
            updated = Entity(**response.data[0])
            logger.info(f"✓ Merged attributes for entity: {updated.name}")
            return updated
        else:
            logger.warning(f"Entity update returned no data for {existing.id}")
            return existing

    except Exception as e:
        logger.error(
            f"Failed to merge entity attributes for {existing.id}: {e}",
            exc_info=True
        )
        return existing


async def create_entity(
    extracted: ExtractedEntity,
    supabase: Client
) -> Entity:
    """
    Create a new entity in the database.

    Args:
        extracted: Extracted entity from LLM
        supabase: Supabase client

    Returns:
        Created Entity with ID assigned
    """
    try:
        entity_create = EntityCreate(
            name=extracted.name,
            type=extracted.type,
            domain=extracted.domain,
            attributes=extracted.attributes
        )

        response = supabase.table("entities").insert(
            entity_create.model_dump(exclude_none=True)
        ).execute()

        if response.data and len(response.data) > 0:
            created = Entity(**response.data[0])
            logger.info(
                f"✓ Created new entity: {created.name} (ID: {created.id})")
            return created
        else:
            raise ValueError("Entity creation returned no data")

    except Exception as e:
        logger.error(
            f"Failed to create entity {extracted.name}: {e}", exc_info=True)
        raise


# =============================================================================
# Memory Storage
# =============================================================================

async def store_memory(
    content: str,
    embedding: List[float],
    entity_ids: List[UUID],
    metadata: Dict[str, Any],
    supabase: Client
) -> Memory:
    """
    Store a memory with vector embedding and entity links.

    Args:
        content: Raw memory content
        embedding: Vector embedding (1536 dimensions)
        entity_ids: List of linked entity UUIDs
        metadata: Additional context (source, timestamp, etc.)
        supabase: Supabase client

    Returns:
        Created Memory object
    """
    try:
        memory_create = MemoryCreate(
            content=content,
            embedding=embedding,
            entity_links=entity_ids,
            metadata=metadata,
            importance_score=0.5  # Default importance
        )

        # Convert to dict for Supabase (handle UUID serialization)
        memory_dict = memory_create.model_dump(exclude_none=True)
        memory_dict['entity_links'] = [str(eid) for eid in entity_ids]

        response = supabase.table("memories").insert(memory_dict).execute()

        if response.data and len(response.data) > 0:
            created = Memory(**response.data[0])
            logger.info(
                f"✓ Stored memory (ID: {created.id}) linked to {len(entity_ids)} entities")
            return created
        else:
            raise ValueError("Memory creation returned no data")

    except Exception as e:
        logger.error(f"Failed to store memory: {e}", exc_info=True)
        raise


# =============================================================================
# The Ingestion Pipeline (Main Entry Point)
# =============================================================================

async def ingest_user_message(
    user_id: UUID,
    content: str,
    source: str = "api"
) -> Dict[str, Any]:
    """
    The complete ingestion pipeline - converts raw user input into structured knowledge.

    This is the main entry point for Phase 2 Context Engine. It orchestrates:
    1. Embedding generation
    2. Entity extraction via LLM
    3. Fuzzy entity matching and merging
    4. Memory storage with entity links

    Args:
        user_id: UUID of the user (for future multi-tenancy)
        content: Raw message content
        source: Source identifier (sms, email, api, etc.)

    Returns:
        Dict with ingestion summary:
        {
            "status": "success",
            "entities_created": 2,
            "entities_updated": 1,
            "memory_id": "uuid-here",
            "processing_time_ms": 1234
        }

    Example:
        >>> result = await ingest_user_message(
        ...     user_id=UUID("..."),
        ...     content="Baseball game moved to 5 PM Saturday",
        ...     source="sms"
        ... )
        >>> result["status"]
        'success'
        >>> result["entities_created"]
        1
    """
    start_time = datetime.utcnow()
    logger.info(f"🧠 Starting ingestion pipeline for user {user_id}")

    try:
        # Initialize clients
        supabase = get_supabase_client()
        embeddings_client = get_embeddings()

        # STEP 1: Generate embedding for raw content
        logger.info("Step 1: Generating embedding...")
        embedding_vector = await embeddings_client.aembed_query(content)

        if len(embedding_vector) != 1536:
            raise ValueError(
                f"Expected 1536-dim embedding, got {len(embedding_vector)}")

        logger.info(f"✓ Generated {len(embedding_vector)}-dim embedding")

        # STEP 2: Extract entities and context via LLM
        logger.info("Step 2: Extracting entities via Claude 3.5 Sonnet...")
        extracted = await extract_context(content)

        # STEP 3: Process entities (fuzzy match + merge or create)
        logger.info(
            f"Step 3: Processing {len(extracted.extracted_entities)} entities...")

        entity_ids: List[UUID] = []
        entities_created = 0
        entities_updated = 0

        for extracted_entity in extracted.extracted_entities:
            # Check if entity already exists (fuzzy match)
            existing = await find_similar_entity(
                name=extracted_entity.name,
                entity_type=extracted_entity.type,
                domain=extracted_entity.domain,
                supabase=supabase
            )

            if existing:
                # UPDATE: Merge attributes
                updated = await merge_entity_attributes(
                    existing=existing,
                    new_attributes=extracted_entity.attributes,
                    supabase=supabase
                )
                entity_ids.append(updated.id)
                entities_updated += 1
            else:
                # CREATE: New entity
                created = await create_entity(extracted_entity, supabase)
                entity_ids.append(created.id)
                entities_created += 1

        # STEP 4: Store memory with entity links
        logger.info("Step 4: Storing memory...")
        metadata = {
            "user_id": str(user_id),
            "source": source,
            "timestamp": datetime.utcnow().isoformat(),
            "domain": extracted.domain.value,
            "original_content": content[:500]  # Truncate for safety
        }

        memory = await store_memory(
            content=extracted.core_memory,
            embedding=embedding_vector,
            entity_ids=entity_ids,
            metadata=metadata,
            supabase=supabase
        )

        # Calculate processing time
        end_time = datetime.utcnow()
        processing_time_ms = int(
            (end_time - start_time).total_seconds() * 1000)

        logger.info(
            f"✓ Ingestion complete in {processing_time_ms}ms - "
            f"Created: {entities_created}, Updated: {entities_updated}"
        )

        return {
            "status": "success",
            "memory_id": str(memory.id),
            "entities_created": entities_created,
            "entities_updated": entities_updated,
            "total_entities": len(entity_ids),
            "entity_ids": [str(eid) for eid in entity_ids],
            "domain": extracted.domain.value,
            "processing_time_ms": processing_time_ms
        }

    except Exception as e:
        logger.error(
            f"❌ Ingestion pipeline failed: {e}",
            exc_info=True
        )
        return {
            "status": "error",
            "error": str(e),
            "processing_time_ms": int(
                (datetime.utcnow() - start_time).total_seconds() * 1000
            )
        }


# =============================================================================
# Utility Functions
# =============================================================================

async def search_memories_by_similarity(
    query: str,
    limit: int = 5,
    threshold: float = 0.7
) -> List[Memory]:
    """
    Search memories using vector similarity (cosine distance).

    This will be used in Phase 3 for retrieval.

    Args:
        query: Search query text
        limit: Max number of results
        threshold: Similarity threshold (0-1, higher = more similar)

    Returns:
        List of similar Memory objects
    """
    try:
        supabase = get_supabase_client()
        embeddings_client = get_embeddings()

        # Generate query embedding
        query_embedding = await embeddings_client.aembed_query(query)

        # Use pgvector's cosine distance search
        # Note: Supabase Python client doesn't have native vector search yet,
        # so we use RPC to call a custom function (to be created in migration)
        response = supabase.rpc(
            "search_memories",
            {
                "query_embedding": query_embedding,
                "match_threshold": 1 - threshold,  # Convert similarity to distance
                "match_count": limit
            }
        ).execute()

        memories = [Memory(**m) for m in response.data]
        logger.info(f"✓ Found {len(memories)} similar memories")
        return memories

    except Exception as e:
        logger.error(f"Memory search failed: {e}", exc_info=True)
        return []


# =============================================================================
# Testing / Example Usage
# =============================================================================

async def _test_ingestion():
    """Test the ingestion pipeline with sample data."""
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")

    test_messages = [
        "Baseball game moved to 5 PM Saturday at Lincoln Park",
        "Told Alice to review the Q1 budget deck by Friday",
        "Dr. appointment rescheduled to next Wednesday at 2 PM",
        "Need to pick up groceries: milk, eggs, bread, chicken"
    ]

    for msg in test_messages:
        print(f"\n{'=' * 60}")
        print(f"Ingesting: {msg}")
        print('=' * 60)

        result = await ingest_user_message(
            user_id=test_user_id,
            content=msg,
            source="test"
        )

        print(f"\nResult: {result}")


if __name__ == "__main__":
    # Enable logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    # Run test
    asyncio.run(_test_ingestion())
