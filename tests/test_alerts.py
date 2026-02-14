"""
Tests for backend.worker.alerts
================================

Tests the failure/recovery alert functions.  The Slack integration is a
stub, so these tests verify logging behaviour and that the async
functions run without error.
"""

import logging

import pytest

from backend.worker.alerts import send_failure_alert, send_recovery_alert


@pytest.mark.asyncio
async def test_send_failure_alert_logs_critical(caplog: pytest.LogCaptureFixture) -> None:
    """send_failure_alert should log at CRITICAL level."""
    with caplog.at_level(logging.CRITICAL, logger="backend.worker.alerts"):
        await send_failure_alert(
            error_summary="entity extraction timeout",
            wal_entry_id="wal-abc-123",
            retry_count=3,
        )
    assert any("permanently failed" in r.message for r in caplog.records)
    assert any("wal-abc-123" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_failure_alert_includes_retry_count(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.CRITICAL, logger="backend.worker.alerts"):
        await send_failure_alert(
            error_summary="boom",
            wal_entry_id="wal-999",
            retry_count=5,
        )
    assert any("5" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_send_recovery_alert_logs_info(caplog: pytest.LogCaptureFixture) -> None:
    """send_recovery_alert should log at INFO level."""
    with caplog.at_level(logging.INFO, logger="backend.worker.alerts"):
        await send_recovery_alert(wal_entry_id="wal-xyz-456")
    assert any("recovered" in r.message for r in caplog.records)
    assert any("wal-xyz-456" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_alerts_do_not_raise_without_slack_webhook() -> None:
    """Both alert functions should succeed even without a Slack webhook."""
    # Should not raise
    await send_failure_alert("err", "id-1", 1)
    await send_recovery_alert("id-2")
