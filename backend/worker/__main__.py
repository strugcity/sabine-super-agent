"""
Allow ``python -m backend.worker`` to start the rq worker.

This thin wrapper delegates to ``backend.worker.main.run_worker()``.
"""

from backend.worker.main import run_worker

run_worker()
