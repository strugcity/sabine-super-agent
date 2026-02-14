"""
Tests for lib.agent.preflight
===============================

Validates the startup preflight-check logic:
- Missing critical env vars → SystemExit (or dict result)
- Missing optional vars → warning, no exit
- All-present → clean pass
- Redis reachability helper
"""

import logging
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

from lib.agent.preflight import (
    _ENV_REQUIREMENTS,
    check_redis_reachable,
    run_preflight_checks,
)


# =========================================================================
# Helpers
# =========================================================================

def _all_env_vars() -> Dict[str, str]:
    """Return a dict where every env var in _ENV_REQUIREMENTS is set."""
    return {name: "dummy-value" for name, _, _ in _ENV_REQUIREMENTS}


def _only_critical_env_vars() -> Dict[str, str]:
    """Return a dict where only critical vars are set."""
    return {name: "dummy-value" for name, is_crit, _ in _ENV_REQUIREMENTS if is_crit}


# =========================================================================
# run_preflight_checks
# =========================================================================

class TestRunPreflightChecks:

    @patch.dict("os.environ", _all_env_vars(), clear=True)
    def test_all_vars_present_returns_all_true(self) -> None:
        results = run_preflight_checks(fail_on_critical=False)
        assert all(results.values())

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_critical_exits(self) -> None:
        """Server should die (SystemExit) when critical vars are missing."""
        with pytest.raises(SystemExit):
            run_preflight_checks(fail_on_critical=True)

    @patch.dict("os.environ", {}, clear=True)
    def test_missing_critical_no_exit_when_disabled(self) -> None:
        """fail_on_critical=False suppresses SystemExit (for tests)."""
        results = run_preflight_checks(fail_on_critical=False)
        # At least one critical var should report False
        critical_names = {n for n, c, _ in _ENV_REQUIREMENTS if c}
        assert any(not results[n] for n in critical_names)

    @patch.dict("os.environ", _only_critical_env_vars(), clear=True)
    def test_missing_optional_passes_with_warnings(self, caplog: pytest.LogCaptureFixture) -> None:
        """Optional vars missing → warnings but no exit."""
        with caplog.at_level(logging.WARNING):
            results = run_preflight_checks(fail_on_critical=True)

        # All critical vars should be True
        for name, is_crit, _ in _ENV_REQUIREMENTS:
            if is_crit:
                assert results[name] is True

        # At least one optional var is False
        optional_names = {n for n, c, _ in _ENV_REQUIREMENTS if not c}
        assert any(not results[n] for n in optional_names)

        # A WARN-level message was emitted
        assert any("PREFLIGHT WARN" in r.message for r in caplog.records)

    @patch.dict("os.environ", _all_env_vars(), clear=True)
    def test_returns_correct_count(self) -> None:
        results = run_preflight_checks(fail_on_critical=False)
        assert len(results) == len(_ENV_REQUIREMENTS)

    @patch.dict("os.environ", {"ANTHROPIC_API_KEY": "  "}, clear=True)
    def test_whitespace_only_treated_as_missing(self) -> None:
        """A var set to only whitespace should be treated as unset."""
        results = run_preflight_checks(fail_on_critical=False)
        assert results["ANTHROPIC_API_KEY"] is False


# =========================================================================
# check_redis_reachable
# =========================================================================

class TestCheckRedisReachable:

    @patch("backend.services.redis_client.get_redis_client")
    def test_returns_true_on_successful_ping(self, mock_get: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.ping.return_value = True
        mock_get.return_value = mock_client

        assert check_redis_reachable() is True

    @patch("backend.services.redis_client.get_redis_client")
    def test_returns_false_on_failed_ping(self, mock_get: MagicMock) -> None:
        mock_client = MagicMock()
        mock_client.ping.return_value = False
        mock_get.return_value = mock_client

        assert check_redis_reachable() is False

    @patch("backend.services.redis_client.get_redis_client")
    def test_returns_false_on_connection_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = ConnectionError("connection refused")
        assert check_redis_reachable() is False

    @patch("backend.services.redis_client.get_redis_client")
    def test_returns_false_on_import_error(self, mock_get: MagicMock) -> None:
        mock_get.side_effect = ImportError("redis not installed")
        assert check_redis_reachable() is False
