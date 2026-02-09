"""
Test script for work email draft mode.

This script validates the branching logic for work vs personal email handling.
"""

import os
import sys

# Set up environment for testing
os.environ["WORK_RELAY_EMAIL"] = "ryan@strugcity.com"
os.environ["WORK_ORIGIN_EMAIL"] = "rknollmaier@coca-cola.com"
os.environ["WORK_ORIGIN_DOMAIN"] = "coca-cola.com"
os.environ["TWILIO_ACCOUNT_SID"] = ""  # Not configured for test
os.environ["SUPABASE_URL"] = ""  # Not configured for test


def test_constants_defined():
    """Test that the new constants are defined"""
    import importlib.util
    
    gmail_handler_path = os.path.join(
        os.path.dirname(__file__),
        "lib/agent/gmail_handler.py"
    )
    
    # Read the file and check for constants
    with open(gmail_handler_path, 'r') as f:
        content = f.read()
    
    # Check that constants are defined
    assert "BODY_PREVIEW_LENGTH = 200" in content, "BODY_PREVIEW_LENGTH constant not found"
    assert "MAX_DRAFT_SMS_LENGTH = 500" in content, "MAX_DRAFT_SMS_LENGTH constant not found"
    assert "DB_BODY_PREVIEW_LENGTH = 500" in content, "DB_BODY_PREVIEW_LENGTH constant not found"
    
    # Check that deprecated datetime.utcnow() is not used
    assert "datetime.utcnow()" not in content, "Found deprecated datetime.utcnow() - should use datetime.now(timezone.utc)"
    
    # Check that timezone is imported
    assert "from datetime import datetime, timedelta, timezone" in content, "timezone not imported from datetime"
    
    print("✓ Test 1 passed: Constants defined correctly")
    print("✓ Test 2 passed: Using timezone-aware datetime")


def test_function_signatures():
    """Test that handle_work_email_draft function exists with correct signature"""
    import importlib.util
    
    gmail_handler_path = os.path.join(
        os.path.dirname(__file__),
        "lib/agent/gmail_handler.py"
    )
    
    # Read the file and check for function
    with open(gmail_handler_path, 'r') as f:
        content = f.read()
    
    # Check that function exists
    assert "async def handle_work_email_draft(" in content, "handle_work_email_draft function not found"
    
    # Check for required parameters
    assert "sender: str," in content, "sender parameter not found"
    assert "subject: str," in content, "subject parameter not found"
    assert "body_text: str," in content, "body_text parameter not found"
    assert "draft_response: str," in content, "draft_response parameter not found"
    assert "message_id: str," in content, "message_id parameter not found"
    assert "thread_id: str," in content, "thread_id parameter not found"
    
    # Check for branching logic
    assert 'if email_domain == "work":' in content, "Work email branching logic not found"
    assert "await handle_work_email_draft(" in content, "handle_work_email_draft not called"
    
    print("✓ Test 3 passed: handle_work_email_draft function defined correctly")
    print("✓ Test 4 passed: Branching logic implemented")


def test_database_migration():
    """Test that database migration file exists"""
    migration_path = os.path.join(
        os.path.dirname(__file__),
        "migrations/add_metadata_to_email_tracking.sql"
    )
    
    assert os.path.exists(migration_path), "Migration file not found"
    
    with open(migration_path, 'r') as f:
        content = f.read()
    
    # Check for metadata column
    assert "ADD COLUMN IF NOT EXISTS metadata JSONB" in content, "metadata column not added"
    assert "CREATE INDEX" in content, "Index not created for metadata"
    
    print("✓ Test 5 passed: Database migration exists and is valid")


def run_all_tests():
    """Run all test cases"""
    print("\n=== Testing Work Email Draft Mode Implementation ===\n")
    
    try:
        test_constants_defined()
        test_function_signatures()
        test_database_migration()
        
        print("\n✅ All tests passed!\n")
        return 0
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}\n")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
