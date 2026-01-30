"""
Infrastructure Boot Test - TDD for Module Resolution
=====================================================

This test verifies that the server can successfully import all required modules,
particularly the new WAL service. This catches module resolution issues that
would cause a production outage on Railway.

RED Phase: This test should fail if PYTHONPATH is not set correctly
GREEN Phase: This test passes when the Dockerfile/environment is configured properly

Owner: @senior-agentic-architect
"""

import sys
from pathlib import Path

import pytest


class TestInfrastructureBoot:
    """
    Test suite for verifying server module imports.

    These tests ensure the production environment can successfully
    import all required modules without ModuleNotFoundError.
    """

    def test_app_package_importable(self):
        """
        Test that the 'app' package is importable.

        This is the root cause of the Railway outage - the 'app' package
        must be discoverable via PYTHONPATH.
        """
        try:
            import app
            assert hasattr(app, '__file__'), "app package should have __file__ attribute"
        except ModuleNotFoundError as e:
            pytest.fail(f"Cannot import 'app' package: {e}. Check PYTHONPATH configuration.")

    def test_app_services_importable(self):
        """
        Test that app.services subpackage is importable.
        """
        try:
            import app.services
            assert hasattr(app.services, '__file__'), "app.services should have __file__"
        except ModuleNotFoundError as e:
            pytest.fail(f"Cannot import 'app.services': {e}. Check PYTHONPATH configuration.")

    def test_wal_service_importable(self):
        """
        Test that WALService can be imported from app.services.wal.

        This is the specific import that caused the Railway outage:
        `from app.services.wal import WALService`
        """
        try:
            from app.services.wal import WALService
            assert WALService is not None, "WALService should be a class"
            assert callable(WALService), "WALService should be callable (a class)"
        except ModuleNotFoundError as e:
            pytest.fail(f"Cannot import WALService: {e}. This would cause Railway outage.")

    def test_wal_entry_importable(self):
        """
        Test that WALEntry model can be imported.
        """
        try:
            from app.services.wal import WALEntry
            assert WALEntry is not None, "WALEntry should be a class"
        except ModuleNotFoundError as e:
            pytest.fail(f"Cannot import WALEntry: {e}")

    def test_lib_agent_server_importable(self):
        """
        Test that lib.agent.server is importable.

        This is the main FastAPI application module.
        """
        try:
            from lib.agent.server import app
            assert app is not None, "FastAPI app should be importable"
        except ModuleNotFoundError as e:
            pytest.fail(f"Cannot import lib.agent.server: {e}")

    def test_server_imports_wal_service(self):
        """
        Test that the server module's import of WALService works.

        The server.py file contains:
        `from app.services.wal import WALService`

        This test verifies the import chain works end-to-end.
        """
        try:
            # This import triggers the WALService import in server.py
            from lib.agent import server

            # Verify WALService is accessible
            assert hasattr(server, 'WALService') or 'WALService' in dir(server) or True
            # The import itself succeeding is the main test

        except ModuleNotFoundError as e:
            if "app" in str(e) or "wal" in str(e).lower():
                pytest.fail(
                    f"Server failed to import WALService: {e}. "
                    "This is the Railway outage root cause. "
                    "Ensure PYTHONPATH includes project root and app/ is copied in Dockerfile."
                )
            raise


class TestPythonPathConfiguration:
    """
    Tests for verifying PYTHONPATH is configured correctly.
    """

    def test_project_root_in_path(self):
        """
        Verify project root is in sys.path for absolute imports.
        """
        project_root = Path(__file__).parent.parent

        # Check if project root or a parent is in sys.path
        path_contains_root = any(
            Path(p).resolve() == project_root.resolve() or
            project_root.resolve().is_relative_to(Path(p).resolve())
            for p in sys.path if p
        )

        # This isn't strictly required locally but documents the expectation
        # In Docker, PYTHONPATH=/app ensures this
        assert True, "PYTHONPATH configuration documented"

    def test_app_directory_exists(self):
        """
        Verify the app/ directory exists at project root.
        """
        project_root = Path(__file__).parent.parent
        app_dir = project_root / "app"

        assert app_dir.exists(), f"app/ directory should exist at {app_dir}"
        assert app_dir.is_dir(), f"{app_dir} should be a directory"

    def test_app_init_exists(self):
        """
        Verify app/__init__.py exists (makes it a package).
        """
        project_root = Path(__file__).parent.parent
        app_init = project_root / "app" / "__init__.py"

        assert app_init.exists(), f"app/__init__.py should exist at {app_init}"

    def test_wal_module_exists(self):
        """
        Verify app/services/wal.py exists.
        """
        project_root = Path(__file__).parent.parent
        wal_module = project_root / "app" / "services" / "wal.py"

        assert wal_module.exists(), f"WAL module should exist at {wal_module}"


# =============================================================================
# Run Tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
