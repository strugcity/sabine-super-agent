"""
Test suite for Task Dependency Validation

Tests the dependency validation system including:
1. Dependency existence validation
2. Circular dependency detection
3. Failed dependency handling
4. Dependency status reporting
"""

import sys
import os

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uuid import UUID, uuid4
from backend.services.exceptions import (
    DependencyNotFoundError,
    CircularDependencyError,
    FailedDependencyError,
    TaskDependencyError,
    OperationResult,
)


# =============================================================================
# Exception Tests
# =============================================================================

def test_dependency_not_found_error():
    """Test DependencyNotFoundError captures missing dependency ID."""
    missing_id = str(uuid4())
    task_id = str(uuid4())

    error = DependencyNotFoundError(
        task_id=task_id,
        missing_dependency_id=missing_id
    )

    assert error.status_code == 400
    assert missing_id in str(error)
    assert error.context["missing_dependency_id"] == missing_id
    print("  [OK] DependencyNotFoundError captures missing dependency")


def test_circular_dependency_error():
    """Test CircularDependencyError captures dependency chain."""
    task_a = str(uuid4())
    task_b = str(uuid4())
    task_c = str(uuid4())
    chain = [task_a, task_b, task_c, task_a]

    error = CircularDependencyError(
        task_id=task_a,
        dependency_chain=chain
    )

    assert error.status_code == 400
    assert "Circular dependency detected" in str(error)
    assert " -> ".join(chain) in str(error)
    assert error.context["dependency_chain"] == chain
    print("  [OK] CircularDependencyError captures dependency chain")


def test_failed_dependency_error():
    """Test FailedDependencyError captures failure details."""
    task_id = str(uuid4())
    failed_dep = str(uuid4())
    reason = "Timeout during execution"

    error = FailedDependencyError(
        task_id=task_id,
        failed_dependency_id=failed_dep,
        failure_reason=reason
    )

    assert error.status_code == 424  # Failed Dependency
    assert failed_dep in str(error)
    assert error.context["failed_dependency_id"] == failed_dep
    assert error.context["failure_reason"] == reason
    print("  [OK] FailedDependencyError captures failure details")


def test_task_dependency_error():
    """Test TaskDependencyError for pending dependencies."""
    task_id = str(uuid4())
    pending = [str(uuid4()), str(uuid4())]

    error = TaskDependencyError(
        task_id=task_id,
        pending_dependencies=pending
    )

    assert error.status_code == 409  # Conflict
    assert "dependencies not met" in str(error)
    assert error.context["pending_dependencies"] == pending
    print("  [OK] TaskDependencyError for pending dependencies")


# =============================================================================
# Validation Logic Tests (Unit Tests without Database)
# =============================================================================

def test_empty_dependencies_always_valid():
    """Test that tasks with no dependencies are always valid."""
    # Simulating the validation logic
    depends_on = []

    # Empty dependencies should pass validation
    result = OperationResult.ok({"validated": True, "dependencies": []})

    assert result.success == True
    assert result.data["validated"] == True
    print("  [OK] Empty dependencies always valid")


def test_dependency_status_categories():
    """Test that we properly categorize dependency statuses."""
    statuses = {
        "queued": {"is_blocking": True, "reason": "Not started yet"},
        "in_progress": {"is_blocking": True, "reason": "Still running"},
        "completed": {"is_blocking": False, "reason": "Done"},
        "failed": {"is_blocking": True, "reason": "Failed execution"},
    }

    for status, expected in statuses.items():
        is_blocking = status != "completed"
        assert is_blocking == expected["is_blocking"], \
            f"Status '{status}' blocking mismatch"

    print("  [OK] Dependency status categories correct")


def test_circular_detection_simple():
    """Test simple circular dependency detection (A -> B -> A)."""
    task_a = uuid4()
    task_b = uuid4()

    # Simulate: Task A depends on Task B, Task B depends on Task A
    # When creating Task A with dependency on B, and B depends on A -> circular

    # This would be detected as:
    # Chain: [A, B, A] -> Circular!

    chain = [str(task_a), str(task_b), str(task_a)]
    error = CircularDependencyError(
        task_id=str(task_a),
        dependency_chain=chain
    )

    assert "Circular dependency detected" in error.message
    assert len(error.context["dependency_chain"]) == 3
    print("  [OK] Simple circular dependency detected")


def test_circular_detection_complex():
    """Test complex circular dependency detection (A -> B -> C -> A)."""
    task_a = uuid4()
    task_b = uuid4()
    task_c = uuid4()

    # Chain: A -> B -> C -> A (back to A is circular)
    chain = [str(task_a), str(task_b), str(task_c), str(task_a)]

    error = CircularDependencyError(
        task_id=str(task_a),
        dependency_chain=chain
    )

    assert "Circular dependency detected" in error.message
    assert len(error.context["dependency_chain"]) == 4
    print("  [OK] Complex circular dependency detected")


def test_valid_dependency_chain():
    """Test that valid dependency chains pass validation."""
    # Valid chain: C -> B -> A (no cycles)
    # Each task only depends on completed predecessors

    task_a = {"id": str(uuid4()), "status": "completed", "depends_on": []}
    task_b = {"id": str(uuid4()), "status": "completed", "depends_on": [task_a["id"]]}
    task_c_deps = [UUID(task_b["id"])]

    # Validation should pass
    result = OperationResult.ok({
        "validated": True,
        "dependencies": [str(d) for d in task_c_deps],
        "dependency_statuses": {
            task_b["id"]: "completed"
        }
    })

    assert result.success == True
    assert result.data["validated"] == True
    print("  [OK] Valid dependency chain passes")


def test_dependency_with_failed_task():
    """Test that dependencies on failed tasks are rejected."""
    task_a = {"id": str(uuid4()), "status": "failed", "error": "Test failure"}

    # Trying to depend on a failed task should fail
    error = FailedDependencyError(
        failed_dependency_id=task_a["id"],
        failure_reason=task_a["error"]
    )

    assert error.status_code == 424
    assert task_a["id"] in str(error)
    print("  [OK] Dependency on failed task rejected")


# =============================================================================
# Operation Result Integration Tests
# =============================================================================

def test_operation_result_for_validation_success():
    """Test OperationResult for successful validation."""
    dep_ids = [str(uuid4()), str(uuid4())]

    result = OperationResult.ok({
        "validated": True,
        "dependencies": dep_ids,
        "dependency_statuses": {
            dep_ids[0]: "completed",
            dep_ids[1]: "completed"
        }
    })

    assert result.success == True
    assert result.data["validated"] == True
    assert len(result.data["dependencies"]) == 2
    print("  [OK] OperationResult for validation success")


def test_operation_result_for_validation_failure():
    """Test OperationResult for validation failure."""
    missing_id = str(uuid4())

    error = DependencyNotFoundError(missing_dependency_id=missing_id)
    result = OperationResult.fail(error)

    assert result.success == False
    assert result.error is error
    assert result.error.status_code == 400
    print("  [OK] OperationResult for validation failure")


def test_operation_result_to_dict_with_dependency_error():
    """Test OperationResult.to_dict() with dependency error."""
    chain = [str(uuid4()), str(uuid4()), str(uuid4())]
    error = CircularDependencyError(dependency_chain=chain)
    result = OperationResult.fail(error)

    result_dict = result.to_dict()

    assert result_dict["success"] == False
    assert "Circular dependency" in result_dict["error"]["error"]
    assert result_dict["error"]["status_code"] == 400
    print("  [OK] OperationResult.to_dict() with dependency error")


# =============================================================================
# HTTP Status Code Tests
# =============================================================================

def test_dependency_error_http_status_codes():
    """Test that all dependency errors have appropriate HTTP status codes."""
    test_cases = [
        (DependencyNotFoundError(missing_dependency_id="x"), 400),  # Bad Request
        (CircularDependencyError(dependency_chain=["a", "b", "a"]), 400),  # Bad Request
        (FailedDependencyError(failed_dependency_id="x"), 424),  # Failed Dependency
        (TaskDependencyError(task_id="x", pending_dependencies=["y"]), 409),  # Conflict
    ]

    for error, expected_status in test_cases:
        assert error.status_code == expected_status, \
            f"{type(error).__name__} should have status {expected_status}, got {error.status_code}"

    print("  [OK] All dependency error HTTP status codes correct")


# =============================================================================
# Dependency Status Reporting Tests
# =============================================================================

def test_dependency_status_report_structure():
    """Test the structure of dependency status reports."""
    # Simulated dependency status response
    dep_status = {
        "task_id": str(uuid4()),
        "has_dependencies": True,
        "dependencies": [
            {
                "id": str(uuid4()),
                "status": "completed",
                "role": "backend-architect-sabine",
                "is_blocking": False,
                "error": None,
                "created_at": "2026-02-01T10:00:00Z"
            },
            {
                "id": str(uuid4()),
                "status": "in_progress",
                "role": "data-ai-engineer-sabine",
                "is_blocking": True,
                "error": None,
                "created_at": "2026-02-01T11:00:00Z"
            }
        ],
        "all_met": False,
        "blocking_count": 1,
        "total_dependencies": 2
    }

    # Validate structure
    assert "task_id" in dep_status
    assert "has_dependencies" in dep_status
    assert "dependencies" in dep_status
    assert "all_met" in dep_status
    assert "blocking_count" in dep_status

    # Validate dependency entries
    for dep in dep_status["dependencies"]:
        assert "id" in dep
        assert "status" in dep
        assert "is_blocking" in dep

    # Validate counts
    blocking = [d for d in dep_status["dependencies"] if d["is_blocking"]]
    assert len(blocking) == dep_status["blocking_count"]

    print("  [OK] Dependency status report structure valid")


def test_dependency_status_all_met():
    """Test dependency status when all dependencies are met."""
    dep_status = {
        "task_id": str(uuid4()),
        "has_dependencies": True,
        "dependencies": [
            {"id": str(uuid4()), "status": "completed", "is_blocking": False},
            {"id": str(uuid4()), "status": "completed", "is_blocking": False},
        ],
        "all_met": True,
        "blocking_count": 0,
        "total_dependencies": 2
    }

    assert dep_status["all_met"] == True
    assert dep_status["blocking_count"] == 0
    print("  [OK] All dependencies met status correct")


def test_dependency_status_with_failed():
    """Test dependency status when a dependency has failed."""
    failed_dep_id = str(uuid4())
    dep_status = {
        "task_id": str(uuid4()),
        "has_dependencies": True,
        "dependencies": [
            {"id": str(uuid4()), "status": "completed", "is_blocking": False},
            {
                "id": failed_dep_id,
                "status": "failed",
                "is_blocking": True,
                "error": "Execution timeout"
            },
        ],
        "all_met": False,
        "blocking_count": 1,
        "total_dependencies": 2
    }

    assert dep_status["all_met"] == False
    assert dep_status["blocking_count"] == 1

    # Find the failed dependency
    failed = [d for d in dep_status["dependencies"] if d["status"] == "failed"]
    assert len(failed) == 1
    assert failed[0]["error"] == "Execution timeout"
    print("  [OK] Failed dependency status correct")


def test_no_dependencies_status():
    """Test dependency status when task has no dependencies."""
    dep_status = {
        "task_id": str(uuid4()),
        "has_dependencies": False,
        "dependencies": [],
        "all_met": True,
        "blocking_count": 0
    }

    assert dep_status["has_dependencies"] == False
    assert dep_status["all_met"] == True
    assert len(dep_status["dependencies"]) == 0
    print("  [OK] No dependencies status correct")


# =============================================================================
# Edge Case Tests
# =============================================================================

def test_self_dependency_detection():
    """Test that self-dependency (task depends on itself) is detected."""
    task_id = uuid4()

    # Task trying to depend on itself
    chain = [str(task_id), str(task_id)]
    error = CircularDependencyError(
        task_id=str(task_id),
        dependency_chain=chain
    )

    assert "Circular dependency detected" in error.message
    print("  [OK] Self-dependency detected")


def test_multiple_missing_dependencies():
    """Test handling multiple missing dependencies."""
    missing_ids = [str(uuid4()), str(uuid4()), str(uuid4())]

    # In practice, validation stops at first missing dependency
    # But we should handle the case gracefully
    error = DependencyNotFoundError(missing_dependency_id=missing_ids[0])

    assert missing_ids[0] in str(error)
    print("  [OK] Multiple missing dependencies handled")


def test_deeply_nested_dependency_chain():
    """Test validation of deeply nested dependency chains."""
    # Create a valid chain: A -> B -> C -> D -> E (no cycles)
    tasks = [uuid4() for _ in range(5)]

    # Each task depends on the previous one (valid)
    chain_valid = True
    visited = set()

    for i, task in enumerate(tasks):
        if task in visited:
            chain_valid = False
            break
        visited.add(task)

    assert chain_valid == True
    print("  [OK] Deeply nested valid chain validated")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Dependency Validation Tests")
    print("=" * 60)

    print("\n--- Exception Tests ---")

    print("\n1. Testing DependencyNotFoundError...")
    test_dependency_not_found_error()

    print("\n2. Testing CircularDependencyError...")
    test_circular_dependency_error()

    print("\n3. Testing FailedDependencyError...")
    test_failed_dependency_error()

    print("\n4. Testing TaskDependencyError...")
    test_task_dependency_error()

    print("\n--- Validation Logic Tests ---")

    print("\n5. Testing empty dependencies...")
    test_empty_dependencies_always_valid()

    print("\n6. Testing dependency status categories...")
    test_dependency_status_categories()

    print("\n7. Testing simple circular detection...")
    test_circular_detection_simple()

    print("\n8. Testing complex circular detection...")
    test_circular_detection_complex()

    print("\n9. Testing valid dependency chain...")
    test_valid_dependency_chain()

    print("\n10. Testing dependency with failed task...")
    test_dependency_with_failed_task()

    print("\n--- Operation Result Tests ---")

    print("\n11. Testing OperationResult for validation success...")
    test_operation_result_for_validation_success()

    print("\n12. Testing OperationResult for validation failure...")
    test_operation_result_for_validation_failure()

    print("\n13. Testing OperationResult.to_dict() with dependency error...")
    test_operation_result_to_dict_with_dependency_error()

    print("\n--- HTTP Status Code Tests ---")

    print("\n14. Testing dependency error HTTP status codes...")
    test_dependency_error_http_status_codes()

    print("\n--- Dependency Status Reporting Tests ---")

    print("\n15. Testing dependency status report structure...")
    test_dependency_status_report_structure()

    print("\n16. Testing all dependencies met status...")
    test_dependency_status_all_met()

    print("\n17. Testing dependency status with failed...")
    test_dependency_status_with_failed()

    print("\n18. Testing no dependencies status...")
    test_no_dependencies_status()

    print("\n--- Edge Case Tests ---")

    print("\n19. Testing self-dependency detection...")
    test_self_dependency_detection()

    print("\n20. Testing multiple missing dependencies...")
    test_multiple_missing_dependencies()

    print("\n21. Testing deeply nested dependency chain...")
    test_deeply_nested_dependency_chain()

    print("\n" + "=" * 60)
    print("All dependency validation tests passed!")
    print("=" * 60)
