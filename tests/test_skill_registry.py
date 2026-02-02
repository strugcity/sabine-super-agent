"""
Tests for Skill Registry - Step 2.3 Verification
=================================================

BDD-style tests verifying that the create_reminder skill is properly
registered and discoverable by the skill registry system.

Run with: pytest tests/test_skill_registry.py -v

Tests cover:
1. Skill auto-discovery (manifest.json + handler.py)
2. Manifest schema validation
3. Handler function interface
4. LangChain tool conversion
5. End-to-end skill execution through registry
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.agent.registry import (
    SKILLS_DIR,
    LoadedSkill,
    SkillManifest,
    convert_local_skill_to_tool,
    create_args_schema_from_manifest,
    get_tool_by_name,
    list_available_tools,
    load_local_skills,
)


# =============================================================================
# Test Configuration
# =============================================================================

REMINDER_SKILL_DIR = SKILLS_DIR / "reminder"


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def reminder_manifest():
    """Load the reminder skill manifest."""
    manifest_path = REMINDER_SKILL_DIR / "manifest.json"
    with open(manifest_path, "r") as f:
        return json.load(f)


@pytest.fixture
def all_local_skills():
    """Load all local skills."""
    return load_local_skills()


@pytest.fixture
def reminder_skill(all_local_skills):
    """Get the loaded reminder skill."""
    for skill in all_local_skills:
        if skill.name == "create_reminder":
            return skill
    return None


# =============================================================================
# Unit Tests: Skill Discovery
# =============================================================================

class TestSkillDiscovery:
    """Test that the reminder skill is properly discovered."""

    def test_skills_directory_exists(self):
        """Skills directory should exist."""
        assert SKILLS_DIR.exists(), f"Skills directory not found: {SKILLS_DIR}"

    def test_reminder_skill_directory_exists(self):
        """Reminder skill directory should exist."""
        assert REMINDER_SKILL_DIR.exists(), f"Reminder skill directory not found: {REMINDER_SKILL_DIR}"

    def test_reminder_manifest_exists(self):
        """Reminder manifest.json should exist."""
        manifest_path = REMINDER_SKILL_DIR / "manifest.json"
        assert manifest_path.exists(), f"Manifest not found: {manifest_path}"

    def test_reminder_handler_exists(self):
        """Reminder handler.py should exist."""
        handler_path = REMINDER_SKILL_DIR / "handler.py"
        assert handler_path.exists(), f"Handler not found: {handler_path}"

    def test_reminder_skill_is_loaded(self, all_local_skills):
        """Reminder skill should be loaded by load_local_skills()."""
        skill_names = [skill.name for skill in all_local_skills]
        assert "create_reminder" in skill_names, (
            f"create_reminder not found in loaded skills: {skill_names}"
        )


# =============================================================================
# Unit Tests: Manifest Schema
# =============================================================================

class TestManifestSchema:
    """Test that the reminder manifest follows the expected schema."""

    def test_manifest_has_required_fields(self, reminder_manifest):
        """Manifest should have all required fields."""
        required_fields = ["name", "description", "parameters"]
        for field in required_fields:
            assert field in reminder_manifest, f"Missing required field: {field}"

    def test_manifest_name_is_create_reminder(self, reminder_manifest):
        """Manifest name should be 'create_reminder'."""
        assert reminder_manifest["name"] == "create_reminder"

    def test_manifest_has_version(self, reminder_manifest):
        """Manifest should have a version field."""
        assert "version" in reminder_manifest
        assert reminder_manifest["version"] == "1.0.0"

    def test_manifest_description_is_meaningful(self, reminder_manifest):
        """Manifest description should be meaningful."""
        desc = reminder_manifest["description"]
        assert len(desc) > 20, "Description too short"
        assert "reminder" in desc.lower(), "Description should mention reminder"

    def test_manifest_parameters_has_properties(self, reminder_manifest):
        """Manifest parameters should have properties."""
        params = reminder_manifest["parameters"]
        assert "properties" in params
        assert len(params["properties"]) > 0

    def test_manifest_has_required_parameters(self, reminder_manifest):
        """Manifest should specify required parameters."""
        params = reminder_manifest["parameters"]
        assert "required" in params
        assert "title" in params["required"]
        assert "scheduled_time" in params["required"]

    def test_manifest_parameter_types(self, reminder_manifest):
        """Manifest parameters should have correct types."""
        props = reminder_manifest["parameters"]["properties"]

        # Check title
        assert props["title"]["type"] == "string"

        # Check scheduled_time
        assert props["scheduled_time"]["type"] == "string"
        assert props["scheduled_time"]["format"] == "date-time"

        # Check reminder_type has enum
        assert "enum" in props["reminder_type"]
        assert "sms" in props["reminder_type"]["enum"]


# =============================================================================
# Unit Tests: Handler Interface
# =============================================================================

class TestHandlerInterface:
    """Test that the reminder handler follows the expected interface."""

    def test_reminder_skill_has_handler(self, reminder_skill):
        """Loaded skill should have a handler function."""
        assert reminder_skill is not None, "Reminder skill not loaded"
        assert callable(reminder_skill.handler), "Handler is not callable"

    def test_handler_is_async(self, reminder_skill):
        """Handler should be an async function."""
        import asyncio
        import inspect

        assert reminder_skill is not None, "Reminder skill not loaded"
        assert asyncio.iscoroutinefunction(reminder_skill.handler), (
            "Handler should be async (coroutine function)"
        )

    def test_handler_accepts_dict_param(self, reminder_skill):
        """Handler should accept a dict parameter."""
        import inspect

        assert reminder_skill is not None, "Reminder skill not loaded"
        sig = inspect.signature(reminder_skill.handler)
        params = list(sig.parameters.keys())
        assert len(params) >= 1, "Handler should accept at least one parameter"


# =============================================================================
# Unit Tests: LangChain Tool Conversion
# =============================================================================

class TestToolConversion:
    """Test conversion of skill to LangChain tool."""

    def test_skill_converts_to_structured_tool(self, reminder_skill):
        """Skill should convert to a LangChain StructuredTool."""
        from langchain_core.tools import StructuredTool

        assert reminder_skill is not None, "Reminder skill not loaded"
        tool = convert_local_skill_to_tool(reminder_skill)

        assert isinstance(tool, StructuredTool)
        assert tool.name == "create_reminder"

    def test_tool_has_description(self, reminder_skill):
        """Tool should have a description."""
        assert reminder_skill is not None, "Reminder skill not loaded"
        tool = convert_local_skill_to_tool(reminder_skill)

        assert tool.description is not None
        assert len(tool.description) > 0
        assert "reminder" in tool.description.lower()

    def test_tool_has_args_schema(self, reminder_skill):
        """Tool should have an args schema."""
        assert reminder_skill is not None, "Reminder skill not loaded"
        tool = convert_local_skill_to_tool(reminder_skill)

        assert tool.args_schema is not None

    def test_args_schema_has_required_fields(self, reminder_skill):
        """Args schema should have required fields."""
        assert reminder_skill is not None, "Reminder skill not loaded"

        args_schema = create_args_schema_from_manifest(reminder_skill)
        assert args_schema is not None

        # Get field names
        field_names = list(args_schema.model_fields.keys())
        assert "title" in field_names
        assert "scheduled_time" in field_names


# =============================================================================
# Unit Tests: Registry Functions
# =============================================================================

class TestRegistryFunctions:
    """Test registry utility functions."""

    def test_get_tool_by_name_found(self, all_local_skills):
        """get_tool_by_name should find existing tool."""
        tools = [convert_local_skill_to_tool(s) for s in all_local_skills]
        tool = get_tool_by_name("create_reminder", tools)

        assert tool is not None
        assert tool.name == "create_reminder"

    def test_get_tool_by_name_not_found(self, all_local_skills):
        """get_tool_by_name should return None for missing tool."""
        tools = [convert_local_skill_to_tool(s) for s in all_local_skills]
        tool = get_tool_by_name("nonexistent_tool", tools)

        assert tool is None

    def test_list_available_tools(self, all_local_skills):
        """list_available_tools should return dict of tools."""
        tools = [convert_local_skill_to_tool(s) for s in all_local_skills]
        tool_dict = list_available_tools(tools)

        assert isinstance(tool_dict, dict)
        assert "create_reminder" in tool_dict
        assert isinstance(tool_dict["create_reminder"], str)


# =============================================================================
# Integration Tests: End-to-End Skill Execution
# =============================================================================

class TestSkillExecution:
    """Test end-to-end skill execution through the registry."""

    @pytest.mark.asyncio
    async def test_tool_execution_with_mock_service(self, reminder_skill):
        """Tool should execute and return results."""
        from datetime import datetime, timedelta, timezone
        from backend.services.exceptions import OperationResult
        from uuid import uuid4

        assert reminder_skill is not None, "Reminder skill not loaded"

        # Create mock service
        mock_service = MagicMock()
        mock_service.create_reminder = AsyncMock(
            return_value=OperationResult.ok({
                "reminder_id": str(uuid4()),
                "reminder": {"id": str(uuid4()), "title": "Test"},
            })
        )

        # Create tool
        tool = convert_local_skill_to_tool(reminder_skill)

        # Execute with mocked service
        future_time = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        with patch(
            "backend.services.reminder_service.get_reminder_service",
            return_value=mock_service
        ):
            result = await tool.ainvoke({
                "title": "Test Reminder",
                "scheduled_time": future_time,
            })

        # Verify result is a string (tools return strings)
        assert isinstance(result, str)
        assert "success" in result.lower() or "remind" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_execution_validation_error(self, reminder_skill):
        """Tool should handle validation errors gracefully via Pydantic."""
        import pydantic

        assert reminder_skill is not None, "Reminder skill not loaded"

        tool = convert_local_skill_to_tool(reminder_skill)

        # Execute without required title - LangChain/Pydantic should catch this
        # The args_schema validates required fields BEFORE the handler runs
        with pytest.raises(pydantic.ValidationError) as exc_info:
            await tool.ainvoke({
                "scheduled_time": "2026-02-03T10:00:00Z",
            })

        # Verify it's a validation error for the missing title field
        error_message = str(exc_info.value)
        assert "title" in error_message.lower()

    @pytest.mark.asyncio
    async def test_tool_execution_handler_validation(self, reminder_skill):
        """Handler should validate past times even when Pydantic passes."""
        assert reminder_skill is not None, "Reminder skill not loaded"

        tool = convert_local_skill_to_tool(reminder_skill)

        # Execute with valid types but past time (handler-level validation)
        result = await tool.ainvoke({
            "title": "Test Reminder",
            "scheduled_time": "2020-01-01T10:00:00Z",  # Past time
        })

        # Handler should return error message, not raise exception
        assert isinstance(result, str)
        assert "error" in result.lower() or "past" in result.lower()


# =============================================================================
# Integration Tests: Multi-Skill Loading
# =============================================================================

class TestMultiSkillLoading:
    """Test loading multiple skills together."""

    def test_multiple_skills_loaded(self, all_local_skills):
        """Multiple skills should be loaded."""
        assert len(all_local_skills) >= 2, (
            f"Expected at least 2 skills, got {len(all_local_skills)}"
        )

    def test_skill_names_are_unique(self, all_local_skills):
        """All skill names should be unique."""
        names = [skill.name for skill in all_local_skills]
        assert len(names) == len(set(names)), (
            f"Duplicate skill names found: {names}"
        )

    def test_all_skills_have_handlers(self, all_local_skills):
        """All skills should have callable handlers."""
        for skill in all_local_skills:
            assert callable(skill.handler), (
                f"Skill {skill.name} has non-callable handler"
            )

    def test_all_skills_convert_to_tools(self, all_local_skills):
        """All skills should convert to LangChain tools."""
        from langchain_core.tools import StructuredTool

        for skill in all_local_skills:
            tool = convert_local_skill_to_tool(skill)
            assert isinstance(tool, StructuredTool), (
                f"Skill {skill.name} failed to convert to StructuredTool"
            )


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    print("Running skill registry tests...")
    pytest.main([__file__, "-v"])
