"""
Family Entity Graph Loader
==========================

Utilities for loading, validating, and seeding the Family Entity Graph
into Supabase. Integrates with the existing memory/entity pipeline.

Usage:
    # Load from JSON seed file
    from lib.db.family_graph_loader import load_family_context, seed_family_entities

    # Get the FamilyContext for inference
    context = await load_family_context(supabase)
    member, confidence, evidence = context.infer_owner("BTBA Bandits practice")

    # Seed from JSON file (first-time setup)
    await seed_family_entities(supabase, "data/seeds/family_entity_graph.json")
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import UUID

from lib.db.family_models import (
    CalendarKeywords,
    FamilyContext,
    FamilyMember,
    FamilyMemberProfile,
    KeywordMapping,
)

logger = logging.getLogger(__name__)

# Cache for family context (avoids repeated DB queries)
_family_context_cache: Optional[tuple[FamilyContext, float]] = None
_CACHE_TTL_SECONDS = 300  # 5 minutes


async def load_family_context(
    supabase,
    force_refresh: bool = False
) -> FamilyContext:
    """
    Load the Family Entity Graph from Supabase.

    Queries all entities where:
        type = "family_member" AND domain = "family" AND status = "active"

    Results are cached for 5 minutes to avoid repeated DB calls.

    Args:
        supabase: Supabase client instance
        force_refresh: If True, bypass cache and reload from DB

    Returns:
        FamilyContext with all family members and their keyword mappings
    """
    import time
    global _family_context_cache

    # Check cache
    if not force_refresh and _family_context_cache:
        cached_context, cached_time = _family_context_cache
        if time.time() - cached_time < _CACHE_TTL_SECONDS:
            logger.debug("Returning cached FamilyContext")
            return cached_context

    # Query entities
    logger.info("Loading FamilyContext from Supabase")
    response = supabase.table("entities").select("*").eq(
        "type", "family_member"
    ).eq(
        "domain", "family"
    ).eq(
        "status", "active"
    ).execute()

    members: List[FamilyMember] = []
    for row in response.data:
        try:
            profile = _parse_profile(row.get("attributes", {}))
            member = FamilyMember(
                entity_id=UUID(row["id"]),
                name=row["name"],
                profile=profile
            )
            members.append(member)
        except Exception as e:
            logger.error(f"Failed to parse family member {row.get('name')}: {e}")
            continue

    context = FamilyContext(members=members)

    # Update cache
    _family_context_cache = (context, time.time())
    logger.info(f"Loaded {len(members)} family members into context")

    return context


def _parse_profile(attributes: Dict[str, Any]) -> FamilyMemberProfile:
    """Parse the attributes JSONB into a FamilyMemberProfile."""
    # Parse calendar_keywords if present
    calendar_keywords = CalendarKeywords()
    kw_data = attributes.get("calendar_keywords", {})

    for category in ["sports", "school", "activities", "medical", "social"]:
        if category in kw_data:
            mapping = KeywordMapping(**kw_data[category])
            setattr(calendar_keywords, category, mapping)

    # Handle any extra categories
    standard_categories = {"sports", "school", "activities", "medical", "social"}
    for key, value in kw_data.items():
        if key not in standard_categories and isinstance(value, dict):
            calendar_keywords.extra[key] = KeywordMapping(**value)

    return FamilyMemberProfile(
        age=attributes.get("age"),
        grade=attributes.get("grade"),
        birthday=attributes.get("birthday"),
        relationship=attributes.get("relationship", "child"),
        calendar_keywords=calendar_keywords,
        schools=attributes.get("schools", []),
        teams=attributes.get("teams", []),
        notes=attributes.get("notes")
    )


async def seed_family_entities(
    supabase,
    seed_file_path: str = "data/seeds/family_entity_graph.json",
    upsert: bool = True
) -> Dict[str, Any]:
    """
    Seed family member entities from a JSON file.

    Args:
        supabase: Supabase client instance
        seed_file_path: Path to the JSON seed file
        upsert: If True, update existing members by name; if False, skip existing

    Returns:
        Summary dict with created, updated, and skipped counts
    """
    seed_path = Path(seed_file_path)
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file_path}")

    with open(seed_path, 'r', encoding='utf-8') as f:
        seed_data = json.load(f)

    results = {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    for member_data in seed_data.get("members", []):
        name = member_data["name"]
        try:
            # Check if entity already exists
            existing = supabase.table("entities").select("id").eq(
                "name", name
            ).eq(
                "type", "family_member"
            ).eq(
                "domain", "family"
            ).limit(1).execute()

            if existing.data:
                if upsert:
                    # Update existing
                    supabase.table("entities").update({
                        "attributes": member_data["attributes"],
                        "status": member_data.get("status", "active")
                    }).eq("id", existing.data[0]["id"]).execute()
                    results["updated"] += 1
                    logger.info(f"Updated family member: {name}")
                else:
                    results["skipped"] += 1
                    logger.debug(f"Skipped existing family member: {name}")
            else:
                # Create new
                supabase.table("entities").insert({
                    "name": member_data["name"],
                    "type": member_data["type"],
                    "domain": member_data["domain"],
                    "status": member_data.get("status", "active"),
                    "attributes": member_data["attributes"]
                }).execute()
                results["created"] += 1
                logger.info(f"Created family member: {name}")

        except Exception as e:
            error_msg = f"Failed to process {name}: {str(e)}"
            results["errors"].append(error_msg)
            logger.error(error_msg)

    # Invalidate cache after seeding
    global _family_context_cache
    _family_context_cache = None

    return results


def load_seed_file(seed_file_path: str = "data/seeds/family_entity_graph.json") -> Dict[str, Any]:
    """
    Load and validate a seed file without connecting to the database.
    Useful for testing and validation.

    Args:
        seed_file_path: Path to the JSON seed file

    Returns:
        Parsed seed data with validated FamilyMemberProfile objects
    """
    seed_path = Path(seed_file_path)
    if not seed_path.exists():
        raise FileNotFoundError(f"Seed file not found: {seed_file_path}")

    with open(seed_path, 'r', encoding='utf-8') as f:
        seed_data = json.load(f)

    # Validate each member's profile
    validated_members = []
    for member_data in seed_data.get("members", []):
        profile = _parse_profile(member_data.get("attributes", {}))
        validated_members.append({
            "name": member_data["name"],
            "profile": profile
        })

    return {
        "household": seed_data.get("household", {}),
        "members": validated_members
    }


# =============================================================================
# CLI for manual seeding
# =============================================================================

async def _main():
    """CLI entry point for seeding family entities."""
    import os
    from supabase import create_client

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
        return

    supabase = create_client(supabase_url, supabase_key)

    print("Seeding family entities...")
    results = await seed_family_entities(supabase)
    print(f"Results: {results}")

    print("\nLoading family context...")
    context = await load_family_context(supabase)
    print(f"Loaded {len(context.members)} family members:")
    for member in context.members:
        print(f"  - {member.name}: {list(member.profile.calendar_keywords.all_keywords().keys())}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
