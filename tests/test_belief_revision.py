"""
Tests for Belief Revision System (Phase 2C)
=============================================

Tests the revision formula, Martingale score, conflict classification,
and lambda_alpha management.

Covers:
  - backend.belief.revision: revise_belief, calculate_martingale_score,
    get_lambda_alpha, set_lambda_alpha, resolve_conflict_with_revision
  - backend.belief.conflict_detector: classify_conflict, detect_belief_conflicts
"""

import math
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures & setup
# ---------------------------------------------------------------------------


@pytest.fixture
def revision_module():
    """Import revision module (lazy to handle creation order)."""
    from backend.belief.revision import (
        DEFAULT_LAMBDA_ALPHA,
        MARTINGALE_ALERT_THRESHOLD,
        MARTINGALE_CONSECUTIVE_DAYS,
        MAX_LAMBDA_ALPHA,
        MIN_LAMBDA_ALPHA,
        MartingaleResult,
        RevisionResult,
        calculate_martingale_score,
        get_lambda_alpha,
        resolve_conflict_with_revision,
        revise_belief,
        set_lambda_alpha,
    )
    return {
        "revise_belief": revise_belief,
        "calculate_martingale_score": calculate_martingale_score,
        "get_lambda_alpha": get_lambda_alpha,
        "set_lambda_alpha": set_lambda_alpha,
        "resolve_conflict_with_revision": resolve_conflict_with_revision,
        "RevisionResult": RevisionResult,
        "MartingaleResult": MartingaleResult,
        "DEFAULT_LAMBDA_ALPHA": DEFAULT_LAMBDA_ALPHA,
        "MIN_LAMBDA_ALPHA": MIN_LAMBDA_ALPHA,
        "MAX_LAMBDA_ALPHA": MAX_LAMBDA_ALPHA,
        "MARTINGALE_ALERT_THRESHOLD": MARTINGALE_ALERT_THRESHOLD,
        "MARTINGALE_CONSECUTIVE_DAYS": MARTINGALE_CONSECUTIVE_DAYS,
    }


@pytest.fixture
def detector_module():
    """Import conflict detector module."""
    from backend.belief.conflict_detector import (
        CONFIDENCE_OVERRIDE_THRESHOLD,
        OUTLIER_CONTRADICTION_THRESHOLD,
        BeliefConflict,
        ConflictClassification,
        classify_conflict,
        detect_belief_conflicts,
    )
    return {
        "classify_conflict": classify_conflict,
        "detect_belief_conflicts": detect_belief_conflicts,
        "ConflictClassification": ConflictClassification,
        "BeliefConflict": BeliefConflict,
        "CONFIDENCE_OVERRIDE_THRESHOLD": CONFIDENCE_OVERRIDE_THRESHOLD,
        "OUTLIER_CONTRADICTION_THRESHOLD": OUTLIER_CONTRADICTION_THRESHOLD,
    }


# =============================================================================
# Revision Formula Tests
# =============================================================================


class TestReviseBeliefFormula:
    """Test the core v' = a * lambda_alpha + v formula."""

    def test_basic_positive_revision(self, revision_module):
        """Positive argument force increases confidence."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.4,
            lambda_alpha=0.5,
            current_version=1,
        )
        # v' = 0.4 * 0.5 + 0.5 = 0.7
        assert math.isclose(result.new_confidence, 0.7, rel_tol=1e-5)
        assert result.new_version == 2
        assert result.delta > 0

    def test_small_positive_revision(self, revision_module):
        """Small argument force produces proportionally small change."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.1,
            lambda_alpha=0.5,
            current_version=3,
        )
        # v' = 0.1 * 0.5 + 0.5 = 0.55
        assert math.isclose(result.new_confidence, 0.55, rel_tol=1e-5)
        assert result.new_version == 4

    def test_clamped_to_max(self, revision_module):
        """Result should be clamped to 1.0 max."""
        result = revision_module["revise_belief"](
            current_confidence=0.9,
            argument_force=0.5,
            lambda_alpha=0.9,
        )
        # v' = 0.5 * 0.9 + 0.9 = 1.35 -> clamped to 1.0
        assert result.new_confidence == 1.0

    def test_clamped_to_min(self, revision_module):
        """Result should be clamped to 0.0 min with zero-ish force."""
        # Use a scenario where argument force is 0 and confidence is already 0
        result = revision_module["revise_belief"](
            current_confidence=0.0,
            argument_force=0.0,
            lambda_alpha=0.5,
        )
        # v' = 0.0 * 0.5 + 0.0 = 0.0
        assert result.new_confidence == 0.0

    def test_stubborn_lambda(self, revision_module):
        """Low lambda_alpha (stubborn) barely changes confidence."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.4,
            lambda_alpha=0.1,
        )
        # v' = 0.4 * 0.1 + 0.5 = 0.54
        assert math.isclose(result.new_confidence, 0.54, rel_tol=1e-5)

    def test_malleable_lambda(self, revision_module):
        """High lambda_alpha (malleable) changes confidence significantly."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.4,
            lambda_alpha=0.9,
        )
        # v' = 0.4 * 0.9 + 0.5 = 0.86
        assert math.isclose(result.new_confidence, 0.86, rel_tol=1e-5)

    def test_zero_argument_force(self, revision_module):
        """Zero argument force means no change."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.0,
            lambda_alpha=0.5,
        )
        assert math.isclose(result.new_confidence, 0.5, rel_tol=1e-5)
        assert math.isclose(result.delta, 0.0, abs_tol=1e-5)

    def test_version_incremented(self, revision_module):
        """Version should always increment by 1."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.1,
            current_version=7,
        )
        assert result.new_version == 8

    def test_lambda_alpha_clamped_to_min(self, revision_module):
        """Lambda alpha below MIN_LAMBDA_ALPHA (0.05) is clamped."""
        min_la = revision_module["MIN_LAMBDA_ALPHA"]
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.4,
            lambda_alpha=0.01,  # Below min
        )
        # Should use MIN_LAMBDA_ALPHA (0.05)
        # v' = 0.4 * 0.05 + 0.5 = 0.52
        assert math.isclose(result.new_confidence, 0.5 + 0.4 * min_la, rel_tol=1e-5)
        assert math.isclose(result.lambda_alpha, min_la, rel_tol=1e-5)

    def test_lambda_alpha_clamped_to_max(self, revision_module):
        """Lambda alpha above MAX_LAMBDA_ALPHA (0.95) is clamped."""
        max_la = revision_module["MAX_LAMBDA_ALPHA"]
        result = revision_module["revise_belief"](
            current_confidence=0.3,
            argument_force=0.5,
            lambda_alpha=1.0,  # Above max
        )
        # Should use MAX_LAMBDA_ALPHA (0.95)
        # v' = 0.5 * 0.95 + 0.3 = 0.775
        assert math.isclose(result.new_confidence, 0.3 + 0.5 * max_la, rel_tol=1e-5)
        assert math.isclose(result.lambda_alpha, max_la, rel_tol=1e-5)

    def test_revision_result_fields(self, revision_module):
        """RevisionResult should populate all expected fields."""
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.3,
            lambda_alpha=0.5,
            current_version=2,
        )
        assert math.isclose(result.original_confidence, 0.5, rel_tol=1e-5)
        # v' = 0.3 * 0.5 + 0.5 = 0.65
        assert math.isclose(result.new_confidence, 0.65, rel_tol=1e-5)
        assert math.isclose(result.argument_force, 0.3, rel_tol=1e-5)
        assert math.isclose(result.lambda_alpha, 0.5, rel_tol=1e-5)
        assert math.isclose(result.delta, 0.15, rel_tol=1e-5)
        assert result.new_version == 3

    def test_high_confidence_large_force(self, revision_module):
        """Starting at high confidence with large force clamps to 1.0."""
        result = revision_module["revise_belief"](
            current_confidence=0.95,
            argument_force=0.8,
            lambda_alpha=0.5,
        )
        # v' = 0.8 * 0.5 + 0.95 = 1.35 -> clamped to 1.0
        assert result.new_confidence == 1.0
        # Delta is difference between clamped output and original
        assert result.delta > 0

    def test_default_lambda_alpha_used(self, revision_module):
        """When lambda_alpha is not specified, default (0.5) is used."""
        default = revision_module["DEFAULT_LAMBDA_ALPHA"]
        result = revision_module["revise_belief"](
            current_confidence=0.5,
            argument_force=0.2,
        )
        # v' = 0.2 * 0.5 + 0.5 = 0.6
        assert math.isclose(result.new_confidence, 0.5 + 0.2 * default, rel_tol=1e-5)


# =============================================================================
# Martingale Score Tests
# =============================================================================


class TestMartingaleScore:
    """Test the Martingale score M = sum((predicted - actual)^2) / n."""

    def test_perfect_prediction(self, revision_module):
        """When predicted == actual, M should be 0."""
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.1, 0.2, 0.3],
            actual_updates=[0.1, 0.2, 0.3],
        )
        assert math.isclose(result.score, 0.0, abs_tol=1e-6)

    def test_high_divergence(self, revision_module):
        """Large prediction errors produce high M score."""
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.5, 0.5, 0.5],
            actual_updates=[0.0, 0.0, 0.0],
        )
        # M = (0.25 + 0.25 + 0.25) / 3 = 0.25
        assert math.isclose(result.score, 0.25, rel_tol=1e-5)
        assert not result.is_alert

    def test_alert_triggered(self, revision_module):
        """Low M over 7+ samples triggers alert."""
        n = 10
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.1] * n,
            actual_updates=[0.11] * n,  # Very close predictions
        )
        # M = (0.01)^2 * 10 / 10 = 0.0001
        assert result.score < 0.1
        assert result.n_samples >= 7
        assert result.is_alert

    def test_no_alert_insufficient_samples(self, revision_module):
        """Low M with < 7 samples should NOT alert."""
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.1, 0.1, 0.1],
            actual_updates=[0.1, 0.1, 0.1],
        )
        assert result.score < 0.1
        assert result.n_samples < 7
        assert not result.is_alert

    def test_empty_inputs(self, revision_module):
        """Empty inputs should return zero score, no alert."""
        result = revision_module["calculate_martingale_score"]([], [])
        assert result.score == 0.0
        assert result.n_samples == 0
        assert not result.is_alert

    def test_mismatched_lengths_uses_minimum(self, revision_module):
        """When lists have different lengths, use the shorter one."""
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.1, 0.2, 0.3, 0.4],
            actual_updates=[0.1, 0.2],
        )
        assert result.n_samples == 2

    def test_exactly_7_samples_with_low_m_alerts(self, revision_module):
        """Exactly 7 samples (MARTINGALE_CONSECUTIVE_DAYS) with low M triggers alert."""
        n = 7
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.5] * n,
            actual_updates=[0.5] * n,  # Perfect match -> M=0
        )
        assert result.score < 0.1
        assert result.n_samples == 7
        assert result.is_alert

    def test_exactly_6_samples_no_alert(self, revision_module):
        """6 samples (below threshold) with low M does NOT trigger alert."""
        n = 6
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.5] * n,
            actual_updates=[0.5] * n,
        )
        assert result.score < 0.1
        assert result.n_samples == 6
        assert not result.is_alert

    def test_score_above_threshold_no_alert_even_with_enough_samples(self, revision_module):
        """M above 0.1 should not alert regardless of sample count."""
        n = 10
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.5] * n,
            actual_updates=[0.0] * n,  # Large divergence
        )
        # M = 0.25 > 0.1
        assert result.score > 0.1
        assert result.n_samples >= 7
        assert not result.is_alert

    def test_martingale_result_has_message(self, revision_module):
        """MartingaleResult should always have a human-readable message."""
        result = revision_module["calculate_martingale_score"](
            predicted_updates=[0.1, 0.2],
            actual_updates=[0.1, 0.2],
        )
        assert isinstance(result.message, str)
        assert len(result.message) > 0


# =============================================================================
# Conflict Classification Tests
# =============================================================================


class TestClassifyConflict:
    """Test the PRD 4.1.2 Decision Matrix."""

    def test_pattern_violation_highest_priority(self, detector_module):
        """PATTERN_VIOLATION should win even when other conditions are met."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.9,
            existing_confidence=0.1,  # Would be HIGH_CONFIDENCE_OVERRIDE
            contradicted_memories_count=5,  # Would be OUTLIER
            violates_rule=True,  # But this wins
        )
        assert result == cls.PATTERN_VIOLATION

    def test_outlier_detection(self, detector_module):
        """OUTLIER_DETECTION when contradicts >3 memories."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.5,
            existing_confidence=0.5,
            contradicted_memories_count=4,
        )
        assert result == cls.OUTLIER_DETECTION

    def test_high_confidence_override(self, detector_module):
        """HIGH_CONFIDENCE_OVERRIDE when delta > 0.2."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.9,
            existing_confidence=0.5,
            contradicted_memories_count=0,
        )
        # delta = 0.9 - 0.5 = 0.4 > 0.2
        assert result == cls.HIGH_CONFIDENCE_OVERRIDE

    def test_marginal_update(self, detector_module):
        """MARGINAL_UPDATE when delta <= 0.2 and no other triggers."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.6,
            existing_confidence=0.5,
            contradicted_memories_count=1,
        )
        # delta = 0.1 <= 0.2, no violation, contradictions <= 3
        assert result == cls.MARGINAL_UPDATE

    def test_exact_threshold_is_marginal(self, detector_module):
        """Delta exactly 0.2 should be MARGINAL (not strictly greater)."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.7,
            existing_confidence=0.5,
            # delta = 0.2, threshold check is >0.2, so this is NOT override
        )
        assert result == cls.MARGINAL_UPDATE

    def test_exactly_3_contradictions_is_not_outlier(self, detector_module):
        """Exactly 3 contradicted memories should NOT be OUTLIER (>3 required)."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.5,
            existing_confidence=0.5,
            contradicted_memories_count=3,
        )
        assert result != cls.OUTLIER_DETECTION

    def test_outlier_has_higher_priority_than_high_confidence(self, detector_module):
        """OUTLIER_DETECTION takes priority over HIGH_CONFIDENCE_OVERRIDE."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.9,
            existing_confidence=0.1,  # delta=0.8 > 0.2
            contradicted_memories_count=5,  # >3
            violates_rule=False,
        )
        assert result == cls.OUTLIER_DETECTION

    def test_pattern_violation_alone(self, detector_module):
        """PATTERN_VIOLATION even with no other conditions."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.5,
            existing_confidence=0.5,
            contradicted_memories_count=0,
            violates_rule=True,
        )
        assert result == cls.PATTERN_VIOLATION

    def test_marginal_with_no_contradictions_or_violations(self, detector_module):
        """Completely benign update is MARGINAL."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.51,
            existing_confidence=0.5,
            contradicted_memories_count=0,
            violates_rule=False,
        )
        assert result == cls.MARGINAL_UPDATE

    def test_negative_delta_is_marginal(self, detector_module):
        """When new_confidence < existing, delta is negative, so never > 0.2."""
        cls = detector_module["ConflictClassification"]
        result = detector_module["classify_conflict"](
            new_confidence=0.3,
            existing_confidence=0.8,
            contradicted_memories_count=0,
            violates_rule=False,
        )
        # delta = 0.3 - 0.8 = -0.5, not > 0.2
        assert result == cls.MARGINAL_UPDATE


# =============================================================================
# Conflict Detection Constants Tests
# =============================================================================


class TestConflictDetectorConstants:
    """Verify threshold constants match PRD spec."""

    def test_confidence_override_threshold(self, detector_module):
        """CONFIDENCE_OVERRIDE_THRESHOLD should be 0.2 per PRD 4.1.2."""
        assert detector_module["CONFIDENCE_OVERRIDE_THRESHOLD"] == 0.2

    def test_outlier_contradiction_threshold(self, detector_module):
        """OUTLIER_CONTRADICTION_THRESHOLD should be 3 per PRD 4.1.2."""
        assert detector_module["OUTLIER_CONTRADICTION_THRESHOLD"] == 3

    def test_conflict_classification_values(self, detector_module):
        """All four PRD 4.1.2 classifications should be present."""
        cls = detector_module["ConflictClassification"]
        assert hasattr(cls, "HIGH_CONFIDENCE_OVERRIDE")
        assert hasattr(cls, "MARGINAL_UPDATE")
        assert hasattr(cls, "OUTLIER_DETECTION")
        assert hasattr(cls, "PATTERN_VIOLATION")


# =============================================================================
# Lambda Alpha Management Tests
# =============================================================================


class TestLambdaAlpha:
    """Test lambda_alpha configuration management."""

    @pytest.mark.asyncio
    async def test_default_lambda_alpha(self, revision_module):
        """Default lambda_alpha should be 0.5 when nothing is configured."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ""  # No config set
            result = await revision_module["get_lambda_alpha"]("test-user-id")
            assert result == 0.5

    @pytest.mark.asyncio
    async def test_global_lambda_alpha(self, revision_module):
        """Should use global lambda_alpha from user_config."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = "0.3"
            result = await revision_module["get_lambda_alpha"]("test-user-id")
            assert math.isclose(result, 0.3, rel_tol=1e-5)

    @pytest.mark.asyncio
    async def test_domain_override(self, revision_module):
        """Per-domain lambda_alpha should override global."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
        ) as mock:
            async def side_effect(user_id: str, key: str, default: str = "") -> str:
                if key == "lambda_alpha_work":
                    return "0.2"
                if key == "lambda_alpha":
                    return "0.5"
                return default
            mock.side_effect = side_effect
            result = await revision_module["get_lambda_alpha"](
                "test-user-id", domain="work"
            )
            assert math.isclose(result, 0.2, rel_tol=1e-5)

    @pytest.mark.asyncio
    async def test_domain_fallback_to_global(self, revision_module):
        """When domain override is missing, fall back to global."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
        ) as mock:
            async def side_effect(user_id: str, key: str, default: str = "") -> str:
                if key == "lambda_alpha_work":
                    return ""  # No domain override
                if key == "lambda_alpha":
                    return "0.7"
                return default
            mock.side_effect = side_effect
            result = await revision_module["get_lambda_alpha"](
                "test-user-id", domain="work"
            )
            assert math.isclose(result, 0.7, rel_tol=1e-5)

    @pytest.mark.asyncio
    async def test_exception_returns_default(self, revision_module):
        """On exception, should return DEFAULT_LAMBDA_ALPHA."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB connection failed"),
        ):
            result = await revision_module["get_lambda_alpha"]("test-user-id")
            assert result == revision_module["DEFAULT_LAMBDA_ALPHA"]


# =============================================================================
# Set Lambda Alpha Tests
# =============================================================================


class TestSetLambdaAlpha:
    """Test lambda_alpha persistence."""

    @pytest.mark.asyncio
    async def test_set_global_lambda_alpha(self, revision_module):
        """Should write global key to user_config."""
        with patch(
            "lib.db.user_config.set_user_config",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            success = await revision_module["set_lambda_alpha"](
                "test-user-id", 0.3
            )
            assert success is True
            mock.assert_called_once_with("test-user-id", "lambda_alpha", "0.3")

    @pytest.mark.asyncio
    async def test_set_domain_lambda_alpha(self, revision_module):
        """Should write domain-specific key to user_config."""
        with patch(
            "lib.db.user_config.set_user_config",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock:
            success = await revision_module["set_lambda_alpha"](
                "test-user-id", 0.2, domain="work"
            )
            assert success is True
            mock.assert_called_once_with(
                "test-user-id", "lambda_alpha_work", "0.2"
            )

    @pytest.mark.asyncio
    async def test_reject_out_of_range(self, revision_module):
        """Should return False for values outside [MIN, MAX]."""
        # Below minimum
        result_low = await revision_module["set_lambda_alpha"](
            "test-user-id", 0.01
        )
        assert result_low is False

        # Above maximum
        result_high = await revision_module["set_lambda_alpha"](
            "test-user-id", 0.99
        )
        assert result_high is False

    @pytest.mark.asyncio
    async def test_exception_returns_false(self, revision_module):
        """On exception, should return False."""
        with patch(
            "lib.db.user_config.set_user_config",
            new_callable=AsyncMock,
            side_effect=RuntimeError("DB write failed"),
        ):
            result = await revision_module["set_lambda_alpha"](
                "test-user-id", 0.5
            )
            assert result is False


# =============================================================================
# Resolve Conflict with Revision (Integration Helper) Tests
# =============================================================================


class TestResolveConflictWithRevision:
    """Test the convenience wrapper that loads lambda_alpha and applies revision."""

    @pytest.mark.asyncio
    async def test_basic_resolution(self, revision_module):
        """Should compute argument_force as new - existing and apply revision."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
            return_value="0.5",
        ):
            result, la = await revision_module["resolve_conflict_with_revision"](
                existing_confidence=0.4,
                new_evidence_confidence=0.8,
                user_id="test-user-id",
                domain=None,
                current_version=1,
            )
            # argument_force = 0.8 - 0.4 = 0.4
            # v' = 0.4 * 0.5 + 0.4 = 0.6
            assert math.isclose(result.new_confidence, 0.6, rel_tol=1e-5)
            assert math.isclose(la, 0.5, rel_tol=1e-5)
            assert result.new_version == 2

    @pytest.mark.asyncio
    async def test_resolution_with_domain(self, revision_module):
        """Should use domain-specific lambda_alpha."""
        with patch(
            "lib.db.user_config.get_user_config",
            new_callable=AsyncMock,
        ) as mock:
            async def side_effect(user_id: str, key: str, default: str = "") -> str:
                if key == "lambda_alpha_personal":
                    return "0.8"
                return ""
            mock.side_effect = side_effect
            result, la = await revision_module["resolve_conflict_with_revision"](
                existing_confidence=0.5,
                new_evidence_confidence=0.7,
                user_id="test-user-id",
                domain="personal",
                current_version=3,
            )
            # argument_force = 0.7 - 0.5 = 0.2
            # v' = 0.2 * 0.8 + 0.5 = 0.66
            assert math.isclose(result.new_confidence, 0.66, rel_tol=1e-5)
            assert math.isclose(la, 0.8, rel_tol=1e-5)
            assert result.new_version == 4


# =============================================================================
# Revision Constants Tests
# =============================================================================


class TestRevisionConstants:
    """Verify revision module constants match PRD spec."""

    def test_default_lambda_alpha_is_half(self, revision_module):
        """DEFAULT_LAMBDA_ALPHA should be 0.5."""
        assert revision_module["DEFAULT_LAMBDA_ALPHA"] == 0.5

    def test_martingale_alert_threshold(self, revision_module):
        """MARTINGALE_ALERT_THRESHOLD should be 0.1."""
        assert revision_module["MARTINGALE_ALERT_THRESHOLD"] == 0.1

    def test_martingale_consecutive_days(self, revision_module):
        """MARTINGALE_CONSECUTIVE_DAYS should be 7."""
        assert revision_module["MARTINGALE_CONSECUTIVE_DAYS"] == 7


# =============================================================================
# Detect Belief Conflicts (async integration) Tests
# =============================================================================


class TestDetectBeliefConflicts:
    """Test the high-level async detect_belief_conflicts function."""

    @pytest.mark.asyncio
    async def test_returns_conflict_for_large_delta(self, detector_module):
        """Should detect HIGH_CONFIDENCE_OVERRIDE when delta is large."""
        existing_memories = [
            {"confidence": 0.3},
            {"confidence": 0.3},
        ]
        cls = detector_module["ConflictClassification"]

        with patch(
            "backend.magma.query.get_entity_relationships",
            new_callable=AsyncMock,
            return_value=[],
        ):
            conflicts = await detector_module["detect_belief_conflicts"](
                entity_name="Test Entity",
                entity_id="entity-uuid-123",
                new_confidence=0.9,
                user_id="user-uuid-456",
                existing_memories=existing_memories,
            )
            # avg_existing = 0.3, delta = 0.6 > 0.2
            assert len(conflicts) >= 1
            assert conflicts[0].classification == cls.HIGH_CONFIDENCE_OVERRIDE
            assert math.isclose(conflicts[0].existing_confidence, 0.3, rel_tol=1e-5)
            assert math.isclose(conflicts[0].new_confidence, 0.9, rel_tol=1e-5)

    @pytest.mark.asyncio
    async def test_returns_empty_for_trivial_marginal(self, detector_module):
        """Trivial marginal updates (abs(delta) <= 0.05) are filtered out."""
        existing_memories = [
            {"confidence": 0.5},
        ]

        with patch(
            "backend.magma.query.get_entity_relationships",
            new_callable=AsyncMock,
            return_value=[],
        ):
            conflicts = await detector_module["detect_belief_conflicts"](
                entity_name="Test Entity",
                entity_id="entity-uuid-123",
                new_confidence=0.51,
                user_id="user-uuid-456",
                existing_memories=existing_memories,
            )
            # delta = 0.01, MARGINAL_UPDATE, abs(delta)=0.01 <= 0.05
            assert len(conflicts) == 0

    @pytest.mark.asyncio
    async def test_handles_graph_query_failure_gracefully(self, detector_module):
        """Should not crash if the contradiction graph is unavailable."""
        existing_memories = [
            {"confidence": 0.3},
        ]

        with patch(
            "backend.magma.query.get_entity_relationships",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Graph unavailable"),
        ):
            conflicts = await detector_module["detect_belief_conflicts"](
                entity_name="Test Entity",
                entity_id="entity-uuid-123",
                new_confidence=0.9,
                user_id="user-uuid-456",
                existing_memories=existing_memories,
            )
            # Should still classify based on confidence delta
            assert len(conflicts) >= 1

    @pytest.mark.asyncio
    async def test_uses_default_confidence_when_no_memories(self, detector_module):
        """With no existing memories, default avg_existing=0.5 is used."""
        with patch(
            "backend.magma.query.get_entity_relationships",
            new_callable=AsyncMock,
            return_value=[],
        ):
            conflicts = await detector_module["detect_belief_conflicts"](
                entity_name="Test Entity",
                entity_id="entity-uuid-123",
                new_confidence=0.9,
                user_id="user-uuid-456",
                existing_memories=None,
            )
            # avg_existing defaults to 0.5, delta = 0.4 > 0.2
            assert len(conflicts) >= 1
            if conflicts:
                assert math.isclose(
                    conflicts[0].existing_confidence, 0.5, rel_tol=1e-5
                )

    @pytest.mark.asyncio
    async def test_outlier_from_contradiction_graph(self, detector_module):
        """Should detect OUTLIER_DETECTION from contradiction graph edges."""
        cls = detector_module["ConflictClassification"]
        # Simulate 4 contradiction edges from graph
        fake_rels = [
            {"target_entity_id": f"target-{i}", "source_entity_id": ""}
            for i in range(4)
        ]

        with patch(
            "backend.magma.query.get_entity_relationships",
            new_callable=AsyncMock,
            return_value=fake_rels,
        ):
            conflicts = await detector_module["detect_belief_conflicts"](
                entity_name="Suspicious Entity",
                entity_id="entity-uuid-789",
                new_confidence=0.5,
                user_id="user-uuid-456",
                existing_memories=[{"confidence": 0.5}],
            )
            assert len(conflicts) >= 1
            assert conflicts[0].classification == cls.OUTLIER_DETECTION
            assert conflicts[0].contradicted_count == 4


# =============================================================================
# Pydantic Model Validation Tests
# =============================================================================


class TestRevisionResultModel:
    """Test Pydantic validation on RevisionResult."""

    def test_valid_revision_result(self, revision_module):
        """RevisionResult should accept valid data."""
        RevisionResult = revision_module["RevisionResult"]
        result = RevisionResult(
            original_confidence=0.5,
            new_confidence=0.7,
            argument_force=0.4,
            lambda_alpha=0.5,
            delta=0.2,
            new_version=2,
        )
        assert result.new_confidence == 0.7


class TestMartingaleResultModel:
    """Test Pydantic validation on MartingaleResult."""

    def test_valid_martingale_result(self, revision_module):
        """MartingaleResult should accept valid data."""
        MartingaleResult = revision_module["MartingaleResult"]
        result = MartingaleResult(
            score=0.05,
            n_samples=10,
            is_alert=True,
            message="Alert triggered",
        )
        assert result.is_alert is True
        assert result.n_samples == 10


class TestBeliefConflictModel:
    """Test Pydantic validation on BeliefConflict."""

    def test_valid_belief_conflict(self, detector_module):
        """BeliefConflict should accept valid data."""
        BeliefConflict = detector_module["BeliefConflict"]
        cls = detector_module["ConflictClassification"]
        conflict = BeliefConflict(
            classification=cls.HIGH_CONFIDENCE_OVERRIDE,
            entity_name="Test",
            new_confidence=0.9,
            existing_confidence=0.3,
            confidence_delta=0.6,
            recommended_action="Append with version tag",
        )
        assert conflict.classification == cls.HIGH_CONFIDENCE_OVERRIDE
        assert conflict.confidence_delta == 0.6
