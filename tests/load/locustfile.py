"""
Locust Load Test Suite for Sabine Super Agent API

This suite validates the PRD exit criteria: "Load test confirms 10-15s latency at P95."

Usage:
    # Headless mode (recommended for CI)
    BASE_URL=http://localhost:8000 API_KEY=your-key locust -f tests/load/locustfile.py --headless -u 5 -r 1 --run-time 60s

    # Web UI mode (recommended for interactive testing)
    BASE_URL=http://localhost:8000 API_KEY=your-key locust -f tests/load/locustfile.py

Environment Variables:
    BASE_URL: Base URL of the API server (default: http://localhost:8000)
    API_KEY: API key for authenticated endpoints (required for protected endpoints)
"""

import logging
import os
from locust import HttpUser, task, between, events

logger = logging.getLogger(__name__)


class SabineUser(HttpUser):
    """
    Simulated user for Sabine Super Agent API load testing.
    
    This class defines user behavior patterns for load testing various API endpoints.
    Task weights are distributed to simulate realistic usage patterns.
    """
    
    # Wait time between tasks (simulates user think time)
    wait_time = between(1, 3)
    
    def on_start(self):
        """
        Called when a simulated user starts.
        
        Performs initial health check to verify the API is responsive
        before proceeding with load testing.
        """
        self.host = os.getenv("BASE_URL", "http://localhost:8000")
        self.api_key = os.getenv("API_KEY", "")
        
        logger.info(f"Starting load test user against {self.host}")
        logger.info(f"API Key configured: {'Yes' if self.api_key else 'No'}")
        
        # Verify health endpoint before proceeding
        try:
            with self.client.get("/health", catch_response=True) as response:
                if response.status_code == 200:
                    logger.info("Health check passed - proceeding with load test")
                    response.success()
                else:
                    logger.error(f"Health check failed with status {response.status_code}")
                    response.failure(f"Health check failed: {response.status_code}")
        except Exception as e:
            logger.error(f"Health check exception: {e}")
    
    @task(3)
    def health_check(self):
        """
        Health check endpoint - most frequent task.
        
        Weight: 3 (high frequency)
        Target: P95 < 500ms
        """
        with self.client.get("/health", catch_response=True, name="/health") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code was {response.status_code}")
    
    @task(1)
    def invoke_agent(self):
        """
        Core agent invocation endpoint.
        
        Weight: 1 (lower frequency - more expensive operation)
        Target: P95 < 15,000ms (15 seconds)
        """
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        payload = {
            "user_id": "loadtest-user",
            "session_id": "loadtest",
            "message": "What tools do you have?"
        }
        
        with self.client.post(
            "/invoke",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/invoke"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code was {response.status_code}")
    
    @task(2)
    def invoke_cached(self):
        """
        Cached agent invocation endpoint (faster than /invoke).
        
        Weight: 2 (moderate frequency)
        Target: P95 < 10,000ms (10 seconds)
        """
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        payload = {
            "user_id": "loadtest-user",
            "session_id": "loadtest",
            "message": "What tools do you have?"
        }
        
        with self.client.post(
            "/invoke/cached",
            json=payload,
            headers=headers,
            catch_response=True,
            name="/invoke/cached"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code was {response.status_code}")
    
    @task(3)
    def list_tools(self):
        """
        List available tools endpoint.
        
        Weight: 3 (high frequency - lightweight read)
        Target: P95 < 1,000ms
        """
        with self.client.get("/tools", catch_response=True, name="/tools") as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code was {response.status_code}")
    
    @task(2)
    def wal_stats(self):
        """
        WAL statistics endpoint.
        
        Weight: 2 (moderate frequency)
        Target: P95 < 1,000ms
        """
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        
        with self.client.get(
            "/wal/stats",
            headers=headers,
            catch_response=True,
            name="/wal/stats"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code was {response.status_code}")
    
    @task(3)
    def prometheus_metrics(self):
        """
        Prometheus metrics endpoint.
        
        Weight: 3 (high frequency - monitoring)
        Target: P95 < 500ms
        """
        with self.client.get(
            "/metrics/prometheus",
            catch_response=True,
            name="/metrics/prometheus"
        ) as response:
            if response.status_code == 200:
                # Verify content type is text/plain
                content_type = response.headers.get("content-type", "")
                if "text/plain" in content_type:
                    response.success()
                else:
                    response.failure(f"Expected text/plain content-type, got {content_type}")
            else:
                response.failure(f"Status code was {response.status_code}")
    
    @task(1)
    def skill_gaps_list(self):
        """
        Skill gaps listing endpoint.
        
        Weight: 1 (lower frequency - admin operation)
        Target: P95 < 1,000ms
        """
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        
        with self.client.get(
            "/api/skills/gaps",
            headers=headers,
            catch_response=True,
            name="/api/skills/gaps"
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Status code was {response.status_code}")


@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Log test configuration when test starts."""
    base_url = os.getenv("BASE_URL", "http://localhost:8000")
    api_key_configured = bool(os.getenv("API_KEY"))
    
    logger.info("=" * 60)
    logger.info("Sabine Super Agent Load Test Starting")
    logger.info("=" * 60)
    logger.info(f"Target URL: {base_url}")
    logger.info(f"API Key: {'Configured' if api_key_configured else 'Not configured'}")
    logger.info("=" * 60)


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Log summary when test stops."""
    logger.info("=" * 60)
    logger.info("Sabine Super Agent Load Test Complete")
    logger.info("=" * 60)
