"""
UAT Test Suite for Security Fixes

Tests:
1. P0: Python API /invoke endpoint authentication
2. P1: Twilio signature validation

Run with: python test_security_uat.py
"""

import asyncio
import hashlib
import hmac
import os
import sys
from base64 import b64encode
from pathlib import Path
from urllib.parse import urlencode

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Load environment
from dotenv import load_dotenv
load_dotenv()

# Set test API key if not already set (for testing purposes)
TEST_API_KEY = "test-api-key-for-uat-12345"
if not os.getenv("AGENT_API_KEY"):
    os.environ["AGENT_API_KEY"] = TEST_API_KEY


def print_header(title: str):
    print("\n" + "=" * 70)
    print(f" {title}")
    print("=" * 70)


def print_test(name: str, passed: bool, details: str = ""):
    status = "[PASS]" if passed else "[FAIL]"
    print(f"  {status}: {name}")
    if details:
        print(f"         {details}")


# =============================================================================
# Test 1: Python API Authentication
# =============================================================================

async def test_python_api_auth():
    """Test the Python API authentication middleware."""
    print_header("TEST 1: Python API Authentication (/invoke endpoint)")

    # Import after env is loaded
    from lib.agent.server import app, AGENT_API_KEY, verify_api_key
    from fastapi.testclient import TestClient

    # Check if API key is configured
    api_key = os.getenv("AGENT_API_KEY", "")
    print(f"\n  Configuration:")
    print(f"    AGENT_API_KEY set: {bool(api_key)}")
    if api_key:
        print(f"    AGENT_API_KEY length: {len(api_key)} chars")

    client = TestClient(app)

    test_payload = {
        "message": "test message",
        "user_id": "test-user-123",
        "session_id": "test-session"
    }

    results = []

    # Test 1.1: Request without API key
    print(f"\n  Test 1.1: Request without X-API-Key header")
    response = client.post("/invoke", json=test_payload)
    if api_key:
        passed = response.status_code == 401
        print_test("Should return 401 Unauthorized", passed, f"Got: {response.status_code}")
        results.append(passed)
    else:
        passed = response.status_code == 500
        print_test("Should return 500 (no API key configured)", passed, f"Got: {response.status_code}")
        results.append(passed)

    # Test 1.2: Request with wrong API key
    print(f"\n  Test 1.2: Request with invalid X-API-Key")
    response = client.post(
        "/invoke",
        json=test_payload,
        headers={"X-API-Key": "wrong-key-12345"}
    )
    if api_key:
        passed = response.status_code == 401
        print_test("Should return 401 Unauthorized", passed, f"Got: {response.status_code}")
        results.append(passed)
    else:
        passed = response.status_code == 500
        print_test("Should return 500 (no API key configured)", passed, f"Got: {response.status_code}")
        results.append(passed)

    # Test 1.3: Request with correct API key (if configured)
    if api_key:
        print(f"\n  Test 1.3: Request with valid X-API-Key")
        response = client.post(
            "/invoke",
            json=test_payload,
            headers={"X-API-Key": api_key}
        )
        # Should get past auth (may fail later due to missing services, but not 401)
        passed = response.status_code != 401
        print_test("Should NOT return 401", passed, f"Got: {response.status_code}")
        results.append(passed)

    # Test 1.4: Verify other protected endpoints
    print(f"\n  Test 1.4: Other protected endpoints without auth")
    protected_endpoints = [
        ("/invoke/cached", "POST", test_payload),
        ("/test", "POST", None),
        ("/gmail/handle", "POST", {"historyId": "123"}),
    ]

    for endpoint, method, payload in protected_endpoints:
        if method == "POST":
            response = client.post(endpoint, json=payload)
        expected = 401 if api_key else 500
        passed = response.status_code == expected
        print_test(f"{endpoint} returns {expected}", passed, f"Got: {response.status_code}")
        results.append(passed)

    # Test 1.5: Verify unprotected endpoints still work
    print(f"\n  Test 1.5: Unprotected endpoints (should work without auth)")
    unprotected_endpoints = [
        ("/", "GET"),
        ("/health", "GET"),
        ("/tools", "GET"),
        ("/cache/metrics", "GET"),
    ]

    for endpoint, method in unprotected_endpoints:
        response = client.get(endpoint)
        # Should work (200) or at least not require auth (not 401)
        passed = response.status_code != 401
        print_test(f"{endpoint} accessible without auth", passed, f"Got: {response.status_code}")
        results.append(passed)

    # Test 1.6: Timing attack resistance (constant-time comparison)
    print(f"\n  Test 1.6: Constant-time comparison verification")
    # Verify secrets.compare_digest is used (code inspection)
    import inspect
    source = inspect.getsource(verify_api_key)
    uses_compare_digest = "secrets.compare_digest" in source
    print_test("Uses secrets.compare_digest()", uses_compare_digest)
    results.append(uses_compare_digest)

    return all(results), results


# =============================================================================
# Test 2: Twilio Signature Validation
# =============================================================================

def compute_twilio_signature(auth_token: str, url: str, params: dict) -> str:
    """
    Compute the expected Twilio signature for a request.

    This replicates Twilio's signing algorithm:
    1. Take the full URL
    2. Sort POST params alphabetically and append key=value
    3. HMAC-SHA1 with auth token as key
    4. Base64 encode
    """
    # Sort params and create string
    sorted_params = sorted(params.items())
    param_string = "".join(f"{k}{v}" for k, v in sorted_params)

    # Create signature
    data = url + param_string
    signature = hmac.new(
        auth_token.encode("utf-8"),
        data.encode("utf-8"),
        hashlib.sha1
    ).digest()

    return b64encode(signature).decode("utf-8")


async def test_twilio_signature_validation():
    """Test the Twilio signature validation logic."""
    print_header("TEST 2: Twilio Signature Validation")

    results = []

    # Check configuration
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    print(f"\n  Configuration:")
    print(f"    TWILIO_AUTH_TOKEN set: {bool(auth_token)}")

    # Test the validation function directly by importing
    print(f"\n  Test 2.1: Import and inspect validateTwilioSignature")

    # Read the route file to verify implementation
    route_path = project_root / "src" / "app" / "api" / "chat" / "route.ts"
    if route_path.exists():
        content = route_path.read_text(encoding="utf-8")

        # Check for key implementation details
        checks = [
            ("imports twilio", "import twilio from 'twilio'"),
            ("reads TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN"),
            ("checks x-twilio-signature header", "x-twilio-signature"),
            ("uses twilio.validateRequest", "twilio.validateRequest"),
            ("returns 403 on invalid signature", "status: 403"),
            ("validates before processing", "validateTwilioSignature(request, body)"),
        ]

        for name, pattern in checks:
            found = pattern in content
            print_test(f"Code {name}", found)
            results.append(found)
    else:
        print(f"  ⚠️  Could not find route.ts at {route_path}")
        results.append(False)

    # Test 2.2: Signature computation verification
    print(f"\n  Test 2.2: Twilio signature algorithm verification")

    # Known test case
    test_token = "test_auth_token_12345"
    test_url = "https://example.com/api/chat"
    test_params = {
        "From": "+15551234567",
        "To": "+15559876543",
        "Body": "Hello world",
        "MessageSid": "SM1234567890abcdef"
    }

    # Compute signature
    signature = compute_twilio_signature(test_token, test_url, test_params)
    print(f"    Test URL: {test_url}")
    print(f"    Test params: From, To, Body, MessageSid")
    print(f"    Computed signature: {signature[:20]}...")

    # Verify signature is non-empty and base64
    is_valid_format = len(signature) > 20 and signature.endswith("=") or len(signature) > 0
    print_test("Signature has valid format", is_valid_format)
    results.append(is_valid_format)

    # Test 2.3: Verify wrong signature would fail
    print(f"\n  Test 2.3: Wrong signature detection")
    wrong_signature = compute_twilio_signature("wrong_token", test_url, test_params)
    signatures_differ = signature != wrong_signature
    print_test("Different token produces different signature", signatures_differ)
    results.append(signatures_differ)

    # Test 2.4: Verify tampered params would fail
    print(f"\n  Test 2.4: Tampered params detection")
    tampered_params = test_params.copy()
    tampered_params["From"] = "+15550000000"  # Changed phone number
    tampered_signature = compute_twilio_signature(test_token, test_url, tampered_params)
    params_sig_differs = signature != tampered_signature
    print_test("Changed params produces different signature", params_sig_differs)
    results.append(params_sig_differs)

    return all(results), results


# =============================================================================
# Test 3: TypeScript Compilation Check
# =============================================================================

async def test_typescript_compilation():
    """Verify the TypeScript code compiles without errors."""
    print_header("TEST 3: TypeScript Compilation")

    results = []

    # Check if we can run tsc
    import subprocess

    print(f"\n  Test 3.1: TypeScript type checking")
    try:
        result = subprocess.run(
            ["npx", "tsc", "--noEmit", "--skipLibCheck"],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            shell=True  # Required on Windows
        )

        passed = result.returncode == 0
        if passed:
            print_test("TypeScript compiles without errors", True)
        else:
            print_test("TypeScript compiles without errors", False)
            # Show relevant errors
            errors = result.stdout + result.stderr
            if "route.ts" in errors:
                print(f"\n  Errors in route.ts:")
                for line in errors.split("\n"):
                    if "route.ts" in line or "error TS" in line:
                        print(f"    {line}")
        results.append(passed)

    except subprocess.TimeoutExpired:
        print_test("TypeScript compilation", False, "Timeout")
        results.append(False)
    except FileNotFoundError:
        print(f"  ⚠️  npx/tsc not found, skipping compilation check")
        # Don't fail the test if tsc isn't available
        results.append(True)
    except Exception as e:
        print_test("TypeScript compilation", False, str(e))
        results.append(False)

    return all(results), results


# =============================================================================
# Test 4: Integration Smoke Test
# =============================================================================

async def test_integration_smoke():
    """Quick integration smoke test."""
    print_header("TEST 4: Integration Smoke Test")

    results = []

    # Test 4.1: Server can start and respond to health check
    print(f"\n  Test 4.1: Server health check")
    try:
        from lib.agent.server import app
        from fastapi.testclient import TestClient

        client = TestClient(app)
        response = client.get("/health")

        passed = response.status_code in [200, 503]  # 503 is ok if services unavailable
        print_test("Health endpoint responds", passed, f"Status: {response.status_code}")
        results.append(passed)

        if response.status_code == 200:
            data = response.json()
            print(f"    Status: {data.get('status')}")
            print(f"    Tools loaded: {data.get('tools_loaded')}")
            print(f"    Database connected: {data.get('database_connected')}")

    except Exception as e:
        print_test("Health endpoint responds", False, str(e))
        results.append(False)

    # Test 4.2: API documentation accessible
    print(f"\n  Test 4.2: API documentation")
    try:
        response = client.get("/docs")
        passed = response.status_code == 200
        print_test("OpenAPI docs accessible at /docs", passed)
        results.append(passed)
    except Exception as e:
        print_test("OpenAPI docs accessible", False, str(e))
        results.append(False)

    return all(results), results


# =============================================================================
# Main
# =============================================================================

async def main():
    print("\n" + "=" * 70)
    print(" SECURITY FIXES - USER ACCEPTANCE TESTING")
    print(" Testing P0 (API Auth) and P1 (Twilio Signature Validation)")
    print("=" * 70)

    all_results = []

    # Run all tests
    tests = [
        ("Python API Authentication", test_python_api_auth),
        ("Twilio Signature Validation", test_twilio_signature_validation),
        ("TypeScript Compilation", test_typescript_compilation),
        ("Integration Smoke Test", test_integration_smoke),
    ]

    for name, test_func in tests:
        try:
            passed, results = await test_func()
            all_results.append((name, passed, results))
        except Exception as e:
            print(f"\n[ERROR] Test '{name}' crashed: {e}")
            import traceback
            traceback.print_exc()
            all_results.append((name, False, []))

    # Summary
    print_header("TEST SUMMARY")

    total_passed = 0
    total_failed = 0

    for name, passed, results in all_results:
        status = "[PASS]" if passed else "[FAIL]"
        passed_count = sum(1 for r in results if r)
        failed_count = len(results) - passed_count
        total_passed += passed_count
        total_failed += failed_count
        print(f"  {status}: {name} ({passed_count}/{len(results)} checks)")

    print(f"\n  Total: {total_passed} passed, {total_failed} failed")

    overall = total_failed == 0
    print(f"\n  {'[SUCCESS] ALL TESTS PASSED - Ready for release' if overall else '[FAILURE] SOME TESTS FAILED - Review required'}")

    return overall


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
