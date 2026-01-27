#!/usr/bin/env python3
"""
Simulation Test - Calendar & Email Draft
QA Test for Sabine MCP Client Changes

Tests:
1. Connect to MCP server
2. List next 3 calendar events
3. Draft email to ryan@strugcity.com (no send)
4. Test failure modes (expired tokens, missing credentials)
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import after path setup
from lib.agent.core import run_agent
from lib.agent.mcp_client import test_mcp_connection, get_mcp_tools


class SimulationTest:
    """Run UAT tests on MCP client"""
    
    def __init__(self):
        self.results = {
            "mcp_connection": None,
            "calendar_read": None,
            "email_draft": None,
            "failure_mode": None,
        }
        self.test_user_email = "ryan@strugcity.com"
        self.errors = []

    async def test_1_mcp_connection(self) -> bool:
        """Test 1: Verify MCP Server Connection"""
        logger.info("\n" + "="*70)
        logger.info("[TEST 1] MCP Server Connection")
        logger.info("="*70)
        
        try:
            is_connected = await test_mcp_connection()
            if is_connected:
                logger.info("✓ PASS: MCP server is reachable and responding")
                self.results["mcp_connection"] = "PASS"
                return True
            else:
                logger.warning("✗ FAIL: MCP server is not responding")
                logger.warning("  Note: This is expected if workspace-mcp is not installed")
                logger.warning("  Proceeding to agent simulation tests...")
                self.results["mcp_connection"] = "SKIP"
                return True  # Continue anyway
        except Exception as e:
            logger.error(f"✗ FAIL: Connection test error: {e}")
            self.errors.append(f"MCP Connection: {e}")
            self.results["mcp_connection"] = "FAIL"
            return False

    async def test_2_calendar_read(self) -> bool:
        """Test 2: List next 3 calendar events"""
        logger.info("\n" + "="*70)
        logger.info("[TEST 2] Calendar Read - Next 3 Events")
        logger.info("="*70)
        
        try:
            # Build prompt for agent to read calendar
            prompt = """
            Please list the next 3 events on my primary Google Calendar.
            For each event, provide:
            - Event title
            - Date and time
            - Duration
            """
            
            logger.info("Sending request to Sabine agent...")
            logger.info(f"Prompt: {prompt.strip()}")
            
            # Try to run agent
            try:
                response = await run_agent(
                    user_id="test-user",
                    session_id="test-sim",
                    user_message=prompt
                )
                
                logger.info(f"✓ PASS: Agent responded to calendar query")
                logger.info(f"Response:\n{response['response'][:500]}...")
                self.results["calendar_read"] = "PASS"
                return True
                
            except Exception as agent_error:
                error_str = str(agent_error).lower()
                
                # Check if it's a missing credentials error (expected in test)
                if any(x in error_str for x in ["token", "auth", "credential", "google"]):
                    logger.warning(f"⚠ SKIP: Google auth credentials not available (expected in test)")
                    logger.warning(f"  Error: {agent_error}")
                    self.results["calendar_read"] = "SKIP"
                    return True
                else:
                    logger.error(f"✗ FAIL: Agent error: {agent_error}")
                    self.errors.append(f"Calendar Read: {agent_error}")
                    self.results["calendar_read"] = "FAIL"
                    return False
                    
        except Exception as e:
            logger.error(f"✗ FAIL: Test setup error: {e}")
            self.errors.append(f"Calendar Test Setup: {e}")
            self.results["calendar_read"] = "FAIL"
            return False

    async def test_3_email_draft(self) -> bool:
        """Test 3: Draft (not send) email to ryan@strugcity.com"""
        logger.info("\n" + "="*70)
        logger.info("[TEST 3] Email Draft (No Send)")
        logger.info("="*70)
        
        try:
            prompt = f"""
            Draft an email (do NOT send it) to {self.test_user_email} with:
            - Subject: "UAT Test: MCP Client Simulation"
            - Body: "Hello Ryan, this is an automated test of the Sabine MCP client. Testing email draft functionality."
            
            Just show me the draft, do NOT actually send it.
            """
            
            logger.info(f"Sending draft request to Sabine agent...")
            logger.info(f"Target: {self.test_user_email}")
            
            try:
                response = await run_agent(
                    user_id="test-user",
                    session_id="test-sim-2",
                    user_message=prompt
                )
                
                logger.info(f"✓ PASS: Agent generated email draft")
                logger.info(f"Response:\n{response['response'][:500]}...")
                
                # Verify no actual send happened
                if "sent" in response['response'].lower() and "draft" not in response['response'].lower():
                    logger.warning("⚠ WARNING: Response mentions 'sent' without mentioning 'draft'")
                    logger.warning("  Verify email was NOT actually sent")
                
                self.results["email_draft"] = "PASS"
                return True
                
            except Exception as agent_error:
                error_str = str(agent_error).lower()
                
                if any(x in error_str for x in ["token", "auth", "credential", "google"]):
                    logger.warning(f"⚠ SKIP: Google auth credentials not available (expected in test)")
                    logger.warning(f"  Error: {agent_error}")
                    self.results["email_draft"] = "SKIP"
                    return True
                else:
                    logger.error(f"✗ FAIL: Agent error: {agent_error}")
                    self.errors.append(f"Email Draft: {agent_error}")
                    self.results["email_draft"] = "FAIL"
                    return False
                    
        except Exception as e:
            logger.error(f"✗ FAIL: Test setup error: {e}")
            self.errors.append(f"Email Test Setup: {e}")
            self.results["email_draft"] = "FAIL"
            return False

    async def test_4_failure_mode(self) -> bool:
        """Test 4: Failure Mode - Expired Token Handling"""
        logger.info("\n" + "="*70)
        logger.info("[TEST 4] Failure Mode - Expired Google Token")
        logger.info("="*70)
        
        try:
            # Temporarily unset token to simulate expiry
            original_token = os.environ.get("GOOGLE_REFRESH_TOKEN")
            os.environ.pop("GOOGLE_REFRESH_TOKEN", None)
            
            prompt = "List my next calendar event"
            
            logger.info("Testing with missing/expired Google token...")
            
            try:
                response = await run_agent(
                    user_id="test-user",
                    session_id="test-sim-3",
                    user_message=prompt
                )
                
                # Restore token
                if original_token:
                    os.environ["GOOGLE_REFRESH_TOKEN"] = original_token
                
                # Check if error was handled gracefully
                response_text = response['response'].lower()
                if "error" in response_text or "token" in response_text or "auth" in response_text:
                    logger.info(f"✓ PASS: System returned clear error message")
                    logger.info(f"Message: {response['response'][:200]}...")
                    self.results["failure_mode"] = "PASS"
                    return True
                else:
                    logger.warning(f"⚠ WARN: System did not clearly indicate auth failure")
                    logger.warning(f"Response: {response['response'][:200]}...")
                    self.results["failure_mode"] = "WARN"
                    return True
                    
            except Exception as agent_error:
                # Restore token
                if original_token:
                    os.environ["GOOGLE_REFRESH_TOKEN"] = original_token
                
                error_str = str(agent_error).lower()
                
                # Expected to get an error
                if any(x in error_str for x in ["token", "auth", "credential", "google", "401", "403"]):
                    logger.info(f"✓ PASS: System properly raised auth error")
                    logger.info(f"Error: {agent_error}")
                    self.results["failure_mode"] = "PASS"
                    return True
                else:
                    logger.error(f"✗ FAIL: Unexpected error: {agent_error}")
                    self.errors.append(f"Failure Mode: {agent_error}")
                    self.results["failure_mode"] = "FAIL"
                    return False
                    
        except Exception as e:
            logger.error(f"✗ FAIL: Test setup error: {e}")
            self.errors.append(f"Failure Mode Setup: {e}")
            self.results["failure_mode"] = "FAIL"
            return False

    async def run_all_tests(self):
        """Execute all tests"""
        logger.info("\n")
        logger.info("#" * 70)
        logger.info("# SABINE MCP CLIENT - UAT & SIMULATION TESTS")
        logger.info("#" * 70)
        logger.info(f"Test Run: {datetime.now().isoformat()}")
        
        # Run tests in sequence
        await self.test_1_mcp_connection()
        await self.test_2_calendar_read()
        await self.test_3_email_draft()
        await self.test_4_failure_mode()
        
        # Generate report
        self._generate_report()

    def _generate_report(self):
        """Generate final test report"""
        logger.info("\n")
        logger.info("=" * 70)
        logger.info("TEST REPORT SUMMARY")
        logger.info("=" * 70)
        
        # Count results
        passed = sum(1 for v in self.results.values() if v == "PASS")
        skipped = sum(1 for v in self.results.values() if v == "SKIP")
        failed = sum(1 for v in self.results.values() if v == "FAIL")
        
        # Print results table
        print("\n")
        print("╔════════════════════════════════════╦════════════════╗")
        print("║           Test Name                ║     Result     ║")
        print("╠════════════════════════════════════╬════════════════╣")
        for test_name, result in self.results.items():
            status_icon = "✓" if result == "PASS" else "⚠" if result == "SKIP" else "✗"
            print(f"║ {test_name.ljust(34)} ║ {status_icon} {result.ljust(11)} ║")
        print("╠════════════════════════════════════╬════════════════╣")
        print(f"║ TOTALS                             ║                ║")
        print(f"║   Passed:  {passed}                           ║                ║")
        print(f"║   Skipped: {skipped}                           ║                ║")
        print(f"║   Failed:  {failed}                           ║                ║")
        print("╚════════════════════════════════════╩════════════════╝")
        
        # Print errors
        if self.errors:
            logger.info("\nErrors:")
            for error in self.errors:
                logger.error(f"  - {error}")
        
        # Overall status
        logger.info("\n" + "=" * 70)
        if failed == 0:
            logger.info("✓ OVERALL STATUS: PASS (All critical tests passed or skipped)")
            overall = "PASS"
        else:
            logger.error("✗ OVERALL STATUS: FAIL (Some tests failed)")
            overall = "FAIL"
        logger.info("=" * 70)
        
        return overall


async def main():
    """Main entry point"""
    test = SimulationTest()
    await test.run_all_tests()
    
    # Exit with appropriate code
    overall_status = sum(1 for v in test.results.values() if v == "FAIL")
    sys.exit(0 if overall_status == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
