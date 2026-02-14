"""
Sabine 2.0 Background Worker Package
=====================================

rq-based worker service for Slow Path processing (ADR-002).

This package contains:
- ``main.py``       -- Worker entry point (starts rq worker + health server)
- ``jobs.py``       -- Job handler functions executed by the worker
- ``slow_path.py``  -- Slow Path consolidation pipeline (entity resolution,
                       relationship extraction, conflict resolution)
- ``checkpoint.py`` -- Redis-backed checkpoint manager for batch recovery
- ``alerts.py``     -- Failure and recovery alerting (Slack stub + logging)
- ``health.py``     -- Lightweight HTTP health-check server

The worker listens on the ``sabine-slow-path`` queue and processes
WAL entries enqueued by the FastAPI application.

See ``docs/architecture/ADR-002-job-queue-slow-path.md`` for full context.
"""
