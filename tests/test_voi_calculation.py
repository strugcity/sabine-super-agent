"""
Tests for Active Inference / VoI Calculation (Phase 2D)
========================================================

Tests the Value-of-Information calculator, action classification,
ambiguity scoring, and push-back protocol.

Covers:
  - backend.inference.value_of_info: classify_action, calculate_ambiguity,
    calculate_voi, evaluate_action, ActionType, VoIResult, AmbiguitySignals
  - backend.inference.push_back: generate_alternatives, format_push_back,
    build_push_back, EvidenceItem, Alternative, PushBackResponse
"""

import math
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def voi_module():
    """Import VoI module (lazy to handle creation order)."""
    from backend.inference.value_of_info import (
        ACTION_TYPE_COSTS,
        DEFAULT_C_INT,
        ActionType,
        AmbiguitySignals,
        VoIResult,
        calculate_ambiguity,
        calculate_voi,
        evaluate_action,
        classify_action,
    )
    return {
        "classify_action": classify_action,
        "calculate_ambiguity": calculate_ambiguity,
        "calculate_voi": calculate_voi,
        "evaluate_action": evaluate_action,
        "ActionType": ActionType,
        "VoIResult": VoIResult,
        "AmbiguitySignals": AmbiguitySignals,
        "ACTION_TYPE_COSTS": ACTION_TYPE_COSTS,
        "DEFAULT_C_INT": DEFAULT_C_INT,
    }


@pytest.fixture
def pushback_module():
    """Import push-back module (lazy; may not exist until other agent finishes)."""
    from backend.inference.push_back import (
        MIN_ALTERNATIVES,
        Alternative,
        EvidenceItem,
        PushBackResponse,
        build_push_back,
        format_push_back,
        generate_alternatives,
    )
    return {
        "generate_alternatives": generate_alternatives,
        "format_push_back": format_push_back,
        "build_push_back": build_push_back,
        "EvidenceItem": EvidenceItem,
        "Alternative": Alternative,
        "PushBackResponse": PushBackResponse,
        "MIN_ALTERNATIVES": MIN_ALTERNATIVES,
    }


# =============================================================================
# Action Classification Tests (DECIDE-001)
# =============================================================================


class TestClassifyAction:
    """Test tool name -> ActionType mapping."""

    def test_irreversible_tools(self, voi_module: Dict[str, Any]) -> None:
        """Known irreversible tools should map correctly."""
        at = voi_module["ActionType"]
        assert voi_module["classify_action"]("send_email") == at.IRREVERSIBLE
        assert voi_module["classify_action"]("send_sms") == at.IRREVERSIBLE
        assert voi_module["classify_action"]("delete_file") == at.IRREVERSIBLE

    def test_reversible_tools(self, voi_module: Dict[str, Any]) -> None:
        """Known reversible tools should map correctly."""
        at = voi_module["ActionType"]
        assert voi_module["classify_action"]("create_draft") == at.REVERSIBLE
        assert voi_module["classify_action"]("schedule_event") == at.REVERSIBLE
        assert voi_module["classify_action"]("create_reminder") == at.REVERSIBLE

    def test_informational_tools(self, voi_module: Dict[str, Any]) -> None:
        """Known informational tools should map correctly."""
        at = voi_module["ActionType"]
        assert voi_module["classify_action"]("search") == at.INFORMATIONAL
        assert voi_module["classify_action"]("get_weather") == at.INFORMATIONAL
        assert voi_module["classify_action"]("summarize") == at.INFORMATIONAL

    def test_unknown_tool_defaults_reversible(self, voi_module: Dict[str, Any]) -> None:
        """Unknown tools should default to REVERSIBLE (conservative)."""
        at = voi_module["ActionType"]
        assert voi_module["classify_action"]("some_unknown_tool_xyz") == at.REVERSIBLE

    def test_case_insensitive(self, voi_module: Dict[str, Any]) -> None:
        """Tool names should be case-insensitive (lowered before lookup)."""
        at = voi_module["ActionType"]
        assert voi_module["classify_action"]("Send_Email") == at.IRREVERSIBLE
        assert voi_module["classify_action"]("SEARCH") == at.INFORMATIONAL
        assert voi_module["classify_action"]("Create_Draft") == at.REVERSIBLE

    def test_hyphen_and_space_normalization(self, voi_module: Dict[str, Any]) -> None:
        """Hyphens and spaces should be normalized to underscores."""
        at = voi_module["ActionType"]
        assert voi_module["classify_action"]("send-email") == at.IRREVERSIBLE
        assert voi_module["classify_action"]("send email") == at.IRREVERSIBLE

    def test_action_type_costs(self, voi_module: Dict[str, Any]) -> None:
        """Each action type should have the correct C_error cost."""
        at = voi_module["ActionType"]
        costs = voi_module["ACTION_TYPE_COSTS"]
        assert costs[at.IRREVERSIBLE] == 1.0
        assert costs[at.REVERSIBLE] == 0.5
        assert costs[at.INFORMATIONAL] == 0.2

    def test_all_mapped_tools_have_valid_action_types(self, voi_module: Dict[str, Any]) -> None:
        """Every tool in the map should produce a valid ActionType member."""
        at = voi_module["ActionType"]
        valid_types = set(at)
        # Smoke test: classify a sampling of tools
        for tool in ["send_email", "create_draft", "search", "get_weather",
                      "delete_file", "schedule_event", "summarize"]:
            result = voi_module["classify_action"](tool)
            assert result in valid_types, f"{tool} returned invalid type {result}"


# =============================================================================
# Ambiguity Scoring Tests (DECIDE-002)
# =============================================================================


class TestCalculateAmbiguity:
    """Test P_error estimation from context signals."""

    def test_no_context_high_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """No memories, no entities, short query, no target -> high ambiguity."""
        signals = voi_module["AmbiguitySignals"](
            retrieval_count=0,
            avg_salience=0.0,
            query_length=2,
            has_explicit_target=False,
            entity_count=0,
        )
        p_error = voi_module["calculate_ambiguity"](signals)
        assert p_error > 0.7, f"Expected >0.7, got {p_error}"

    def test_rich_context_low_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """Many memories, high salience, explicit target -> low ambiguity."""
        signals = voi_module["AmbiguitySignals"](
            retrieval_count=10,
            avg_salience=0.9,
            query_length=20,
            has_explicit_target=True,
            entity_count=5,
        )
        p_error = voi_module["calculate_ambiguity"](signals)
        assert p_error < 0.3, f"Expected <0.3, got {p_error}"

    def test_moderate_context(self, voi_module: Dict[str, Any]) -> None:
        """Moderate signals -> moderate ambiguity."""
        signals = voi_module["AmbiguitySignals"](
            retrieval_count=3,
            avg_salience=0.5,
            query_length=8,
            has_explicit_target=True,
            entity_count=2,
        )
        p_error = voi_module["calculate_ambiguity"](signals)
        assert 0.2 < p_error < 0.6, f"Expected 0.2-0.6, got {p_error}"

    def test_output_range_extreme_high(self, voi_module: Dict[str, Any]) -> None:
        """P_error should always be in [0.0, 1.0] even at extremes."""
        signals = voi_module["AmbiguitySignals"](
            retrieval_count=0,
            avg_salience=0.0,
            query_length=1,
            has_explicit_target=False,
            entity_count=0,
        )
        p = voi_module["calculate_ambiguity"](signals)
        assert 0.0 <= p <= 1.0

    def test_output_range_extreme_low(self, voi_module: Dict[str, Any]) -> None:
        """P_error should always be in [0.0, 1.0] even at extremes."""
        signals = voi_module["AmbiguitySignals"](
            retrieval_count=20,
            avg_salience=1.0,
            query_length=50,
            has_explicit_target=True,
            entity_count=10,
        )
        p = voi_module["calculate_ambiguity"](signals)
        assert 0.0 <= p <= 1.0

    def test_low_salience_increases_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """Lower avg_salience should produce higher P_error, all else equal."""
        base = dict(retrieval_count=5, query_length=10,
                    has_explicit_target=True, entity_count=3)
        p_low = voi_module["calculate_ambiguity"](
            voi_module["AmbiguitySignals"](avg_salience=0.2, **base)
        )
        p_high = voi_module["calculate_ambiguity"](
            voi_module["AmbiguitySignals"](avg_salience=0.9, **base)
        )
        assert p_low > p_high, f"Low salience {p_low} should > high salience {p_high}"

    def test_more_retrievals_decreases_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """More retrieved memories should produce lower P_error."""
        base = dict(avg_salience=0.5, query_length=10,
                    has_explicit_target=True, entity_count=3)
        p_sparse = voi_module["calculate_ambiguity"](
            voi_module["AmbiguitySignals"](retrieval_count=0, **base)
        )
        p_dense = voi_module["calculate_ambiguity"](
            voi_module["AmbiguitySignals"](retrieval_count=10, **base)
        )
        assert p_sparse > p_dense, f"Sparse {p_sparse} should > dense {p_dense}"

    def test_explicit_target_decreases_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """Having an explicit target should decrease P_error."""
        base = dict(retrieval_count=3, avg_salience=0.5,
                    query_length=10, entity_count=2)
        p_no_target = voi_module["calculate_ambiguity"](
            voi_module["AmbiguitySignals"](has_explicit_target=False, **base)
        )
        p_target = voi_module["calculate_ambiguity"](
            voi_module["AmbiguitySignals"](has_explicit_target=True, **base)
        )
        assert p_no_target > p_target

    def test_default_signals_produce_moderate_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """Default AmbiguitySignals() should give moderate-to-high P_error."""
        signals = voi_module["AmbiguitySignals"]()
        p = voi_module["calculate_ambiguity"](signals)
        assert 0.3 < p < 0.9, f"Default signals gave {p}, expected moderate"


# =============================================================================
# VoI Calculation Tests (DECIDE-002, DECIDE-003)
# =============================================================================


class TestCalculateVoI:
    """Test the VoI = (C_error x P_error) - C_int formula."""

    def test_should_clarify_irreversible_high_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """Irreversible + high ambiguity -> should clarify."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].IRREVERSIBLE,
            p_error=0.8,
            c_int=0.3,
        )
        # VoI = 1.0 * 0.8 - 0.3 = 0.5
        assert math.isclose(result.voi_score, 0.5, abs_tol=1e-4)
        assert result.should_clarify is True

    def test_proceed_informational_low_ambiguity(self, voi_module: Dict[str, Any]) -> None:
        """Informational + low ambiguity -> proceed without clarification."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].INFORMATIONAL,
            p_error=0.3,
            c_int=0.3,
        )
        # VoI = 0.2 * 0.3 - 0.3 = -0.24
        assert result.voi_score < 0
        assert result.should_clarify is False

    def test_boundary_exactly_zero(self, voi_module: Dict[str, Any]) -> None:
        """VoI = 0 -> should NOT clarify (strictly > 0 required)."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].REVERSIBLE,
            p_error=0.6,
            c_int=0.3,
        )
        # VoI = 0.5 * 0.6 - 0.3 = 0.0
        assert math.isclose(result.voi_score, 0.0, abs_tol=1e-5)
        assert result.should_clarify is False

    def test_high_c_int_reduces_push_backs(self, voi_module: Dict[str, Any]) -> None:
        """High C_int (less chatty) -> fewer push-backs."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].REVERSIBLE,
            p_error=0.6,
            c_int=0.8,
        )
        # VoI = 0.5 * 0.6 - 0.8 = -0.5
        assert result.should_clarify is False

    def test_low_c_int_increases_push_backs(self, voi_module: Dict[str, Any]) -> None:
        """Low C_int (more chatty) -> more push-backs."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].REVERSIBLE,
            p_error=0.6,
            c_int=0.1,
        )
        # VoI = 0.5 * 0.6 - 0.1 = 0.2
        assert result.should_clarify is True

    def test_voi_result_has_all_fields(self, voi_module: Dict[str, Any]) -> None:
        """VoIResult should include all required fields."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].IRREVERSIBLE,
            p_error=0.5,
            c_int=0.3,
            tool_name="send_email",
        )
        assert result.action_type == voi_module["ActionType"].IRREVERSIBLE
        assert result.c_error == 1.0
        assert result.p_error == 0.5
        assert result.c_int == 0.3
        assert result.tool_name == "send_email"
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    def test_voi_formula_numerical_accuracy(self, voi_module: Dict[str, Any]) -> None:
        """Verify exact VoI formula: (C_error * P_error) - C_int."""
        at = voi_module["ActionType"]
        costs = voi_module["ACTION_TYPE_COSTS"]

        for action_type, c_error in costs.items():
            for p_error in [0.0, 0.25, 0.5, 0.75, 1.0]:
                for c_int in [0.1, 0.3, 0.5]:
                    result = voi_module["calculate_voi"](
                        action_type=action_type, p_error=p_error, c_int=c_int,
                    )
                    expected = (c_error * p_error) - c_int
                    assert math.isclose(result.voi_score, expected, abs_tol=1e-4), (
                        f"action={action_type}, p={p_error}, c_int={c_int}: "
                        f"got {result.voi_score}, expected {expected}"
                    )

    def test_should_clarify_matches_sign(self, voi_module: Dict[str, Any]) -> None:
        """should_clarify must be True iff voi_score > 0."""
        positive = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].IRREVERSIBLE,
            p_error=0.9, c_int=0.1,
        )
        assert positive.voi_score > 0
        assert positive.should_clarify is True

        negative = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].INFORMATIONAL,
            p_error=0.1, c_int=0.5,
        )
        assert negative.voi_score < 0
        assert negative.should_clarify is False

    def test_default_c_int(self, voi_module: Dict[str, Any]) -> None:
        """When c_int is not specified, DEFAULT_C_INT (0.3) should be used."""
        result = voi_module["calculate_voi"](
            action_type=voi_module["ActionType"].REVERSIBLE,
            p_error=0.5,
            # c_int not specified -> should use DEFAULT_C_INT
        )
        assert result.c_int == voi_module["DEFAULT_C_INT"]


# =============================================================================
# VoI Constants Tests
# =============================================================================


class TestVoIConstants:
    """Verify VoI module constants match PRD spec."""

    def test_default_c_int(self, voi_module: Dict[str, Any]) -> None:
        """DEFAULT_C_INT should be 0.3 (balanced)."""
        assert voi_module["DEFAULT_C_INT"] == 0.3

    def test_action_type_enum_members(self, voi_module: Dict[str, Any]) -> None:
        """ActionType should have exactly 3 members."""
        at = voi_module["ActionType"]
        assert hasattr(at, "IRREVERSIBLE")
        assert hasattr(at, "REVERSIBLE")
        assert hasattr(at, "INFORMATIONAL")
        assert len(at) == 3


# =============================================================================
# Evaluate Action (Full Pipeline) Tests
# =============================================================================


class TestEvaluateAction:
    """Test the async full VoI evaluation pipeline."""

    @pytest.mark.asyncio
    async def test_basic_evaluation(self, voi_module: Dict[str, Any]) -> None:
        """Should combine classify + ambiguity + c_int into a VoIResult."""
        with patch(
            "backend.inference.value_of_info.get_c_int",
            new_callable=AsyncMock,
            return_value=0.3,
        ):
            signals = voi_module["AmbiguitySignals"](
                retrieval_count=0,
                avg_salience=0.0,
                query_length=2,
                has_explicit_target=False,
                entity_count=0,
            )
            result = await voi_module["evaluate_action"](
                tool_name="send_email",
                user_id="test-user-id",
                ambiguity_signals=signals,
            )
            # send_email -> IRREVERSIBLE (C=1.0), high ambiguity -> should clarify
            assert result.action_type == voi_module["ActionType"].IRREVERSIBLE
            assert result.should_clarify is True

    @pytest.mark.asyncio
    async def test_informational_with_good_context_proceeds(self, voi_module: Dict[str, Any]) -> None:
        """Informational tool with good context should proceed."""
        with patch(
            "backend.inference.value_of_info.get_c_int",
            new_callable=AsyncMock,
            return_value=0.3,
        ):
            signals = voi_module["AmbiguitySignals"](
                retrieval_count=10,
                avg_salience=0.9,
                query_length=20,
                has_explicit_target=True,
                entity_count=5,
            )
            result = await voi_module["evaluate_action"](
                tool_name="search",
                user_id="test-user-id",
                ambiguity_signals=signals,
            )
            assert result.action_type == voi_module["ActionType"].INFORMATIONAL
            assert result.should_clarify is False

    @pytest.mark.asyncio
    async def test_default_signals_when_none(self, voi_module: Dict[str, Any]) -> None:
        """When ambiguity_signals is None, conservative defaults are used."""
        with patch(
            "backend.inference.value_of_info.get_c_int",
            new_callable=AsyncMock,
            return_value=0.3,
        ):
            result = await voi_module["evaluate_action"](
                tool_name="create_draft",
                user_id="test-user-id",
                ambiguity_signals=None,
            )
            # Should still produce a valid result
            assert isinstance(result, voi_module["VoIResult"])
            assert result.action_type == voi_module["ActionType"].REVERSIBLE

    @pytest.mark.asyncio
    async def test_user_specific_c_int(self, voi_module: Dict[str, Any]) -> None:
        """Pipeline should use the user-specific C_int from config."""
        with patch(
            "backend.inference.value_of_info.get_c_int",
            new_callable=AsyncMock,
            return_value=0.8,  # Very tolerant user
        ):
            signals = voi_module["AmbiguitySignals"](
                retrieval_count=2,
                avg_salience=0.4,
                query_length=5,
                has_explicit_target=False,
                entity_count=1,
            )
            result = await voi_module["evaluate_action"](
                tool_name="create_draft",
                user_id="test-user-id",
                ambiguity_signals=signals,
            )
            assert result.c_int == 0.8
            # With high c_int, even moderate ambiguity should not trigger clarify
            # VoI = 0.5 * p_error - 0.8, p_error is moderate, VoI likely < 0
            assert result.should_clarify is False

    @pytest.mark.asyncio
    async def test_tool_name_passed_through(self, voi_module: Dict[str, Any]) -> None:
        """The tool_name should be preserved in the VoIResult."""
        with patch(
            "backend.inference.value_of_info.get_c_int",
            new_callable=AsyncMock,
            return_value=0.3,
        ):
            result = await voi_module["evaluate_action"](
                tool_name="send_sms",
                user_id="test-user-id",
            )
            assert result.tool_name == "send_sms"


# =============================================================================
# Pydantic Model Validation Tests
# =============================================================================


class TestVoIResultModel:
    """Test Pydantic validation on VoIResult."""

    def test_valid_voi_result(self, voi_module: Dict[str, Any]) -> None:
        """VoIResult should accept valid data."""
        VoIResult = voi_module["VoIResult"]
        result = VoIResult(
            action_type=voi_module["ActionType"].IRREVERSIBLE,
            c_error=1.0,
            p_error=0.5,
            c_int=0.3,
            voi_score=0.2,
            should_clarify=True,
            tool_name="send_email",
            reasoning="Test reasoning",
        )
        assert result.voi_score == 0.2
        assert result.should_clarify is True

    def test_voi_result_optional_fields(self, voi_module: Dict[str, Any]) -> None:
        """tool_name is optional, reasoning defaults to empty string."""
        VoIResult = voi_module["VoIResult"]
        result = VoIResult(
            action_type=voi_module["ActionType"].REVERSIBLE,
            c_error=0.5,
            p_error=0.3,
            c_int=0.3,
            voi_score=-0.15,
            should_clarify=False,
        )
        assert result.tool_name is None
        assert result.reasoning == ""


class TestAmbiguitySignalsModel:
    """Test Pydantic validation on AmbiguitySignals."""

    def test_defaults(self, voi_module: Dict[str, Any]) -> None:
        """AmbiguitySignals should have sensible defaults."""
        signals = voi_module["AmbiguitySignals"]()
        assert signals.retrieval_count == 0
        assert signals.avg_salience == 0.5
        assert signals.query_length == 0
        assert signals.has_explicit_target is False
        assert signals.entity_count == 0

    def test_custom_values(self, voi_module: Dict[str, Any]) -> None:
        """AmbiguitySignals should accept custom values."""
        signals = voi_module["AmbiguitySignals"](
            retrieval_count=5,
            avg_salience=0.8,
            query_length=15,
            has_explicit_target=True,
            entity_count=3,
        )
        assert signals.retrieval_count == 5
        assert signals.avg_salience == 0.8


# =============================================================================
# Push-Back Alternatives Tests (PUSH-002)
# =============================================================================


class TestGenerateAlternatives:
    """Test alternative generation for push-backs."""

    def test_minimum_two_alternatives(self, pushback_module: Dict[str, Any]) -> None:
        """Must always return at least 2 alternatives (PUSH-002)."""
        alts = pushback_module["generate_alternatives"](
            original_action="search something",
            tool_name="search",
            concern="ambiguous query",
        )
        assert len(alts) >= pushback_module["MIN_ALTERNATIVES"]
        assert len(alts) >= 2

    def test_first_is_original_action(self, pushback_module: Dict[str, Any]) -> None:
        """First alternative should always be the original action."""
        alts = pushback_module["generate_alternatives"](
            original_action="send email to John",
            tool_name="send_email",
            concern="uncertain recipient",
        )
        assert alts[0].is_original is True
        assert alts[0].label == "A"

    def test_email_gets_draft_alternative(self, pushback_module: Dict[str, Any]) -> None:
        """Email tools should offer a 'save as draft' alternative."""
        alts = pushback_module["generate_alternatives"](
            original_action="send email to John",
            tool_name="send_email",
            concern="uncertain recipient",
        )
        descriptions = [a.description.lower() for a in alts]
        assert any("draft" in d for d in descriptions), (
            f"Expected 'draft' alternative, got: {descriptions}"
        )

    def test_delete_gets_archive_alternative(self, pushback_module: Dict[str, Any]) -> None:
        """Delete tools should offer an 'archive' alternative."""
        alts = pushback_module["generate_alternatives"](
            original_action="delete meeting notes",
            tool_name="delete_file",
            concern="might need later",
        )
        descriptions = [a.description.lower() for a in alts]
        assert any("archive" in d for d in descriptions), (
            f"Expected 'archive' alternative, got: {descriptions}"
        )

    def test_alternatives_have_sequential_labels(self, pushback_module: Dict[str, Any]) -> None:
        """Alternatives should be labeled A, B, C, ... in order."""
        alts = pushback_module["generate_alternatives"](
            original_action="send email",
            tool_name="send_email",
            concern="test",
        )
        for i, alt in enumerate(alts):
            expected_label = chr(ord("A") + i)
            assert alt.label == expected_label, (
                f"Alt {i} label={alt.label}, expected={expected_label}"
            )

    def test_at_least_one_non_original(self, pushback_module: Dict[str, Any]) -> None:
        """There should be at least one alternative that is NOT the original."""
        alts = pushback_module["generate_alternatives"](
            original_action="send email",
            tool_name="send_email",
            concern="test",
        )
        non_originals = [a for a in alts if not a.is_original]
        assert len(non_originals) >= 1


# =============================================================================
# Push-Back Formatting Tests
# =============================================================================


class TestFormatPushBack:
    """Test push-back message formatting."""

    def test_includes_concern(self, pushback_module: Dict[str, Any]) -> None:
        """Formatted message should include the concern."""
        msg = pushback_module["format_push_back"](
            concern="This email might go to the wrong person",
            evidence=[],
            alternatives=[
                pushback_module["Alternative"](
                    label="A", description="Send anyway", is_original=True,
                ),
                pushback_module["Alternative"](
                    label="B", description="Cancel", is_original=False,
                ),
            ],
            voi_score=0.5,
        )
        assert "wrong person" in msg

    def test_includes_evidence(self, pushback_module: Dict[str, Any]) -> None:
        """Formatted message should include evidence items."""
        evidence = [
            pushback_module["EvidenceItem"](
                summary="Alice works_at Acme Corp",
                confidence=0.9,
            ),
        ]
        msg = pushback_module["format_push_back"](
            concern="Uncertain about recipient",
            evidence=evidence,
            alternatives=[
                pushback_module["Alternative"](
                    label="A", description="Proceed", is_original=True,
                ),
                pushback_module["Alternative"](
                    label="B", description="Cancel", is_original=False,
                ),
            ],
            voi_score=0.3,
        )
        assert "Alice works_at Acme Corp" in msg

    def test_includes_all_alternatives(self, pushback_module: Dict[str, Any]) -> None:
        """Formatted message should list all alternatives with labels."""
        alts = [
            pushback_module["Alternative"](
                label="A", description="Send email", is_original=True,
            ),
            pushback_module["Alternative"](
                label="B", description="Cancel", is_original=False,
            ),
            pushback_module["Alternative"](
                label="C", description="Save as draft", is_original=False,
            ),
        ]
        msg = pushback_module["format_push_back"](
            concern="test",
            evidence=[],
            alternatives=alts,
            voi_score=0.1,
        )
        assert "A)" in msg
        assert "B)" in msg
        assert "C)" in msg

    def test_returns_string(self, pushback_module: Dict[str, Any]) -> None:
        """format_push_back should always return a non-empty string."""
        msg = pushback_module["format_push_back"](
            concern="any concern",
            evidence=[],
            alternatives=[
                pushback_module["Alternative"](
                    label="A", description="Proceed", is_original=True,
                ),
                pushback_module["Alternative"](
                    label="B", description="Stop", is_original=False,
                ),
            ],
            voi_score=0.2,
        )
        assert isinstance(msg, str)
        assert len(msg) > 0


# =============================================================================
# Security Tests (SQL Injection, DoS Protection)
# =============================================================================


class TestEntityResolutionSecurity:
    """Test security fixes for entity name resolution."""

    @pytest.mark.asyncio
    async def test_wildcard_sanitization(self, pushback_module: Dict[str, Any]) -> None:
        """Entity name with SQL wildcards should be sanitized to prevent DoS."""
        from backend.inference.push_back import _resolve_entity_id
        
        # Mock the Supabase client to verify sanitized input
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_ilike = MagicMock()
        mock_limit = MagicMock()
        mock_execute = MagicMock()
        
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.ilike.return_value = mock_ilike
        mock_ilike.limit.return_value = mock_limit
        mock_limit.execute.return_value = MagicMock(data=[])
        
        # Patch the get_supabase_client from backend.services.wal where it's imported
        with patch("backend.services.wal.get_supabase_client", return_value=mock_client):
            # Try to exploit with wildcard DoS attack
            malicious_input = "%%%%"
            result = await _resolve_entity_id(malicious_input)
            
            # Should return None (empty after sanitization)
            assert result is None
            
            # Verify wildcards were removed
            # The function should either not call the query (empty string) or call with sanitized input
            if mock_select.ilike.called:
                call_args = mock_select.ilike.call_args
                sanitized = call_args[0][1]
                # Verify no wildcards remain
                assert "%" not in sanitized

    @pytest.mark.asyncio
    async def test_entity_resolution_normal_input(self, pushback_module: Dict[str, Any]) -> None:
        """Normal entity names should work correctly."""
        from backend.inference.push_back import _resolve_entity_id
        
        # Mock successful lookup
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_ilike = MagicMock()
        mock_limit = MagicMock()
        mock_execute = MagicMock()
        
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.ilike.return_value = mock_ilike
        mock_ilike.limit.return_value = mock_limit
        mock_limit.execute.return_value = MagicMock(
            data=[{"id": "test-uuid-123"}]
        )
        
        with patch("backend.services.wal.get_supabase_client", return_value=mock_client):
            result = await _resolve_entity_id("Alice")
            assert result == "test-uuid-123"

    @pytest.mark.asyncio
    async def test_underscore_wildcard_sanitization(self, pushback_module: Dict[str, Any]) -> None:
        """Underscore wildcards should be sanitized (replaced with space)."""
        from backend.inference.push_back import _resolve_entity_id
        
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_ilike = MagicMock()
        mock_limit = MagicMock()
        mock_limit.execute.return_value = MagicMock(data=[])
        
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.ilike.return_value = mock_ilike
        mock_ilike.limit.return_value = mock_limit
        
        with patch("backend.services.wal.get_supabase_client", return_value=mock_client):
            # All underscores becomes empty after sanitization
            result = await _resolve_entity_id("___")
            assert result is None
            
            # Query should not be called because input is empty after sanitization
            # (This prevents DoS from wildcard-only queries)
            
    @pytest.mark.asyncio
    async def test_mixed_wildcard_sanitization(self, pushback_module: Dict[str, Any]) -> None:
        """Entity names with mixed wildcards should be sanitized."""
        from backend.inference.push_back import _resolve_entity_id
        
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_select = MagicMock()
        mock_ilike = MagicMock()
        mock_limit = MagicMock()
        mock_limit.execute.return_value = MagicMock(data=[])
        
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_select
        mock_select.ilike.return_value = mock_ilike
        mock_ilike.limit.return_value = mock_limit
        
        with patch("backend.services.wal.get_supabase_client", return_value=mock_client):
            result = await _resolve_entity_id("Alice_%_Bob")
            
            # Should call query with underscores replaced
            call_args = mock_select.ilike.call_args
            sanitized = call_args[0][1]
            # Wildcards should be removed/replaced
            assert "%" not in sanitized
            assert sanitized == "Alice  Bob"  # % removed, _ replaced with space


class TestCausalTraceTimeout:
    """Test timeout protection for causal trace calls."""

    @pytest.mark.asyncio
    async def test_causal_trace_timeout_handling(self, pushback_module: Dict[str, Any]) -> None:
        """Causal trace should timeout after 200ms and return partial evidence."""
        from backend.inference.push_back import gather_evidence
        
        # Mock entity resolution
        with patch("backend.inference.push_back._resolve_entity_id", return_value="test-entity-id"):
            # Mock get_entity_relationships to return some evidence
            mock_relationships = [
                {
                    "id": "rel-1",
                    "source_name": "Alice",
                    "target_name": "Bob",
                    "relationship_type": "works_with",
                    "confidence": 0.9,
                }
            ]
            
            # Mock causal_trace to hang (simulate slow query)
            async def slow_causal_trace(*args, **kwargs):
                import asyncio
                await asyncio.sleep(1.0)  # Simulate 1 second delay
                return {"chain": []}
            
            with patch("backend.magma.query.get_entity_relationships", return_value=mock_relationships):
                with patch("backend.magma.query.causal_trace", side_effect=slow_causal_trace):
                    # Should timeout and return only the relationship evidence
                    evidence = await gather_evidence("Alice", "test-user-id", max_items=5)
                    
                    # Should have relationship evidence but not causal evidence
                    assert len(evidence) == 1
                    assert evidence[0].entity_name in ["Bob", "Alice"]

    @pytest.mark.asyncio
    async def test_causal_trace_success(self, pushback_module: Dict[str, Any]) -> None:
        """Causal trace that completes quickly should include causal evidence."""
        from backend.inference.push_back import gather_evidence
        
        with patch("backend.inference.push_back._resolve_entity_id", return_value="test-entity-id"):
            mock_relationships = [
                {
                    "id": "rel-1",
                    "source_name": "Alice",
                    "target_name": "Bob",
                    "relationship_type": "works_with",
                    "confidence": 0.9,
                }
            ]
            
            # Mock fast causal_trace
            async def fast_causal_trace(*args, **kwargs):
                import asyncio
                await asyncio.sleep(0.05)  # 50ms - well under timeout
                return {
                    "chain": [
                        {
                            "from": "Alice",
                            "to": "Project X",
                            "type": "caused_by",
                            "from_id": "alice-id",
                            "to_id": "project-id",
                            "confidence": 0.8,
                        }
                    ]
                }
            
            with patch("backend.magma.query.get_entity_relationships", return_value=mock_relationships):
                with patch("backend.magma.query.causal_trace", side_effect=fast_causal_trace):
                    evidence = await gather_evidence("Alice", "test-user-id", max_items=5)
                    
                    # Should have both relationship and causal evidence
                    assert len(evidence) == 2
                    # Check causal evidence is present
                    causal_items = [e for e in evidence if "Causal chain" in e.summary]
                    assert len(causal_items) == 1


class TestJsonSerialization:
    """Test JSON serialization safety for JSONB fields."""

    @pytest.mark.asyncio
    async def test_datetime_serialization_in_alternatives(self, pushback_module: Dict[str, Any]) -> None:
        """Alternatives with datetime objects should serialize correctly."""
        from backend.inference.push_back import log_push_back_event, PushBackLogEntry
        from datetime import datetime, timezone
        
        # Mock Supabase client
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_execute = MagicMock()
        
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_insert
        mock_insert.execute.return_value = MagicMock(data=[{"id": "log-id"}])
        
        with patch("backend.services.wal.get_supabase_client", return_value=mock_client):
            # Create an entry with a datetime in alternatives
            entry = PushBackLogEntry(
                user_id="test-user-id",
                action_type="irreversible",
                c_error=1.0,
                p_error=0.5,
                c_int=0.3,
                voi_score=0.2,
                push_back_triggered=True,
                alternatives_offered=[
                    {
                        "label": "A",
                        "description": "Test",
                        "timestamp": datetime.now(timezone.utc),  # datetime object
                    }
                ],
            )
            
            result = await log_push_back_event(entry)
            assert result is True
            
            # Verify insert was called
            mock_table.insert.assert_called_once()
            
            # Get the data that was inserted
            call_args = mock_table.insert.call_args
            inserted_data = call_args[0][0]
            
            # Verify alternatives were serialized properly
            alternatives = inserted_data["alternatives_offered"]
            assert len(alternatives) == 1
            # The timestamp should be a string (ISO format), not a datetime object
            assert isinstance(alternatives[0]["timestamp"], str)

    @pytest.mark.asyncio
    async def test_pydantic_model_serialization(self, pushback_module: Dict[str, Any]) -> None:
        """Pydantic Alternative models should serialize correctly."""
        from backend.inference.push_back import log_push_back_event, PushBackLogEntry
        
        Alternative = pushback_module["Alternative"]
        
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = MagicMock(data=[{"id": "log-id"}])
        mock_table.insert.return_value = mock_insert
        mock_client.table.return_value = mock_table
        
        with patch("backend.services.wal.get_supabase_client", return_value=mock_client):
            # Create an Alternative model and dump it to dict
            alt = Alternative(
                label="A",
                description="Proceed",
                is_original=True,
                risk_level="high",
            )
            
            entry = PushBackLogEntry(
                user_id="test-user-id",
                action_type="irreversible",
                c_error=1.0,
                p_error=0.5,
                c_int=0.3,
                voi_score=0.2,
                push_back_triggered=True,
                alternatives_offered=[alt.model_dump()],  # Pass as dict
            )
            
            result = await log_push_back_event(entry)
            assert result is True
            
            # Verify the alternative was serialized
            call_args = mock_table.insert.call_args
            inserted_data = call_args[0][0]
            alternatives = inserted_data["alternatives_offered"]
            
            assert len(alternatives) == 1
            assert alternatives[0]["label"] == "A"
            assert alternatives[0]["description"] == "Proceed"
            assert alternatives[0]["is_original"] is True
