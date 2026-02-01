"""
Test suite for Repository Authorization System

This tests the validate_role_repo_authorization function which ensures
agents can only work in their authorized repositories.
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import the function we're testing
from lib.agent.server import (
    validate_role_repo_authorization,
    ROLE_REPO_AUTHORIZATION,
    VALID_REPOS
)


def test_valid_repos_defined():
    """Ensure valid repos are properly defined."""
    assert "sabine-super-agent" in VALID_REPOS
    assert "dream-team-strug" in VALID_REPOS

    # Check repo structure
    for repo_id, repo_info in VALID_REPOS.items():
        assert "owner" in repo_info, f"Repo {repo_id} missing 'owner'"
        assert "repo" in repo_info, f"Repo {repo_id} missing 'repo'"
        assert repo_info["owner"] == "strugcity", f"Repo {repo_id} has wrong owner"

    print("  Valid repos defined correctly")


def test_backend_roles_authorized_for_backend_repo():
    """Backend roles should only access sabine-super-agent."""
    backend_roles = ["backend-architect-sabine", "data-ai-engineer-sabine", "SABINE_ARCHITECT"]

    for role in backend_roles:
        # Should be authorized for sabine-super-agent
        is_valid, error = validate_role_repo_authorization(role, "sabine-super-agent")
        assert is_valid, f"Role {role} should be authorized for sabine-super-agent: {error}"

        # Should NOT be authorized for dream-team-strug
        is_valid, error = validate_role_repo_authorization(role, "dream-team-strug")
        assert not is_valid, f"Role {role} should NOT be authorized for dream-team-strug"

    print("  Backend roles correctly restricted to sabine-super-agent")


def test_frontend_roles_authorized_for_frontend_repo():
    """Frontend roles should only access dream-team-strug."""
    frontend_roles = ["frontend-ops-sabine"]

    for role in frontend_roles:
        # Should be authorized for dream-team-strug
        is_valid, error = validate_role_repo_authorization(role, "dream-team-strug")
        assert is_valid, f"Role {role} should be authorized for dream-team-strug: {error}"

        # Should NOT be authorized for sabine-super-agent
        is_valid, error = validate_role_repo_authorization(role, "sabine-super-agent")
        assert not is_valid, f"Role {role} should NOT be authorized for sabine-super-agent"

    print("  Frontend roles correctly restricted to dream-team-strug")


def test_cross_functional_roles_have_multi_repo_access():
    """Cross-functional roles should access both repos."""
    cross_functional_roles = ["product-manager-sabine", "qa-security-sabine"]

    for role in cross_functional_roles:
        # Should be authorized for sabine-super-agent
        is_valid, error = validate_role_repo_authorization(role, "sabine-super-agent")
        assert is_valid, f"Role {role} should be authorized for sabine-super-agent: {error}"

        # Should also be authorized for dream-team-strug
        is_valid, error = validate_role_repo_authorization(role, "dream-team-strug")
        assert is_valid, f"Role {role} should be authorized for dream-team-strug: {error}"

    print("  Cross-functional roles have multi-repo access")


def test_invalid_repo_rejected():
    """Invalid repo identifiers should be rejected."""
    is_valid, error = validate_role_repo_authorization("backend-architect-sabine", "invalid-repo")
    assert not is_valid, "Invalid repo should be rejected"
    assert "Invalid target_repo" in error
    print("  Invalid repos correctly rejected")


def test_unknown_role_rejected():
    """Unknown roles should be rejected."""
    is_valid, error = validate_role_repo_authorization("unknown-role", "sabine-super-agent")
    assert not is_valid, "Unknown role should be rejected"
    assert "not found in authorization mapping" in error
    print("  Unknown roles correctly rejected")


def test_all_roles_have_authorization():
    """All defined roles should have at least one authorized repo."""
    for role in ROLE_REPO_AUTHORIZATION.keys():
        authorized_repos = ROLE_REPO_AUTHORIZATION[role]
        assert len(authorized_repos) > 0, f"Role {role} has no authorized repos"

        # Verify each authorized repo is valid
        for repo in authorized_repos:
            assert repo in VALID_REPOS, f"Role {role} references invalid repo {repo}"

    print("  All roles have valid authorization mappings")


def test_dark_mode_scenario():
    """
    Test the scenario that caused the original Dark Mode bug.

    The frontend-ops-sabine role should ONLY work in dream-team-strug,
    preventing accidental commits to the wrong repo.
    """
    role = "frontend-ops-sabine"

    # Frontend role targeting frontend repo (CORRECT)
    is_valid, error = validate_role_repo_authorization(role, "dream-team-strug")
    assert is_valid, f"Frontend role should work in frontend repo: {error}"

    # Frontend role targeting backend repo (WRONG - should be blocked)
    is_valid, error = validate_role_repo_authorization(role, "sabine-super-agent")
    assert not is_valid, "Frontend role should NOT work in backend repo"
    assert "not authorized" in error.lower()

    print("  Dark Mode scenario: frontend-ops-sabine correctly restricted")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Repository Authorization Tests")
    print("=" * 60)

    print("\n1. Testing valid repos defined...")
    test_valid_repos_defined()
    print("   [PASSED]")

    print("\n2. Testing backend role authorization...")
    test_backend_roles_authorized_for_backend_repo()
    print("   [PASSED]")

    print("\n3. Testing frontend role authorization...")
    test_frontend_roles_authorized_for_frontend_repo()
    print("   [PASSED]")

    print("\n4. Testing cross-functional role authorization...")
    test_cross_functional_roles_have_multi_repo_access()
    print("   [PASSED]")

    print("\n5. Testing invalid repo rejection...")
    test_invalid_repo_rejected()
    print("   [PASSED]")

    print("\n6. Testing unknown role rejection...")
    test_unknown_role_rejected()
    print("   [PASSED]")

    print("\n7. Testing all roles have authorization...")
    test_all_roles_have_authorization()
    print("   [PASSED]")

    print("\n8. Testing Dark Mode scenario...")
    test_dark_mode_scenario()
    print("   [PASSED]")

    print("\n" + "=" * 60)
    print("All repository authorization tests passed!")
    print("=" * 60)
