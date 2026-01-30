"""
E2B Sandbox Skill - Secure Python Code Execution

This skill provides a secure sandbox environment for executing Python code
using E2B's Code Interpreter. It's useful for:
- Running tests in isolation
- Prototyping new skills
- Data analysis and visualization
- Executing user-provided code safely

Requires: E2B_API_KEY environment variable (automatically used by SDK)
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default and maximum timeout values
DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 300


def get_e2b_api_key() -> Optional[str]:
    """Get E2B API key from environment variables."""
    return os.getenv("E2B_API_KEY")


async def execute(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute Python code in an E2B sandbox.

    Args:
        params: Dict with:
            - code (str): Python code to execute
            - timeout (int): Max execution time in seconds (default: 30)
            - install_packages (list): Optional packages to pip install first

    Returns:
        Dict with status, stdout, stderr, results, and execution metadata
    """
    # Check for API key (SDK reads from E2B_API_KEY env var automatically)
    api_key = get_e2b_api_key()
    if not api_key:
        return {
            "status": "error",
            "error": "E2B_API_KEY environment variable not set",
            "message": "Please set E2B_API_KEY to use the sandbox. Get a key at https://e2b.dev"
        }

    code = params.get("code")
    if not code:
        return {
            "status": "error",
            "error": "No code provided",
            "message": "The 'code' parameter is required"
        }

    # Validate and cap timeout
    timeout = params.get("timeout", DEFAULT_TIMEOUT)
    if timeout > MAX_TIMEOUT:
        logger.warning(f"Timeout {timeout}s exceeds max {MAX_TIMEOUT}s, capping")
        timeout = MAX_TIMEOUT

    install_packages = params.get("install_packages", [])

    try:
        from e2b_code_interpreter import Sandbox

        logger.info(f"Creating E2B sandbox (timeout: {timeout}s)")

        results = {
            "stdout": [],
            "stderr": [],
            "results": [],
            "errors": []
        }

        # Create sandbox - SDK reads E2B_API_KEY from environment automatically
        # No constructor args in latest SDK - use set_timeout after creation
        sandbox = Sandbox()

        try:
            # Set timeout after creation if method exists
            if hasattr(sandbox, 'set_timeout'):
                sandbox.set_timeout(timeout)

            # Install packages if requested
            if install_packages:
                logger.info(f"Installing packages: {install_packages}")
                pip_cmd = f"pip install {' '.join(install_packages)}"
                pip_result = sandbox.run_code(pip_cmd)
                if pip_result.error:
                    results["errors"].append({
                        "phase": "package_installation",
                        "error": str(pip_result.error)
                    })
                    logger.warning(f"Package installation error: {pip_result.error}")

            # Execute the main code
            logger.info(f"Executing code ({len(code)} chars)")
            execution = sandbox.run_code(code)

            # Collect stdout - handle both list and single string formats
            if execution.logs:
                if hasattr(execution.logs, 'stdout'):
                    stdout = execution.logs.stdout
                    if isinstance(stdout, list):
                        results["stdout"] = stdout
                    elif stdout:
                        results["stdout"] = [stdout]
                    logger.debug(f"Stdout: {results['stdout']}")

                if hasattr(execution.logs, 'stderr'):
                    stderr = execution.logs.stderr
                    if isinstance(stderr, list):
                        results["stderr"] = stderr
                    elif stderr:
                        results["stderr"] = [stderr]
                    logger.debug(f"Stderr: {results['stderr']}")

            # Collect results (for things like plots, dataframes, etc.)
            if execution.results:
                for result in execution.results:
                    result_item = {
                        "type": type(result).__name__
                    }
                    # Handle different result types
                    if hasattr(result, "text") and result.text:
                        result_item["text"] = result.text
                    if hasattr(result, "html") and result.html:
                        result_item["html"] = result.html[:500] if len(result.html) > 500 else result.html
                    if hasattr(result, "png") and result.png:
                        result_item["png"] = "(base64 image data available)"
                    if hasattr(result, "data") and result.data:
                        result_item["data"] = str(result.data)[:1000]
                    results["results"].append(result_item)

            # Check for execution errors
            if execution.error:
                results["errors"].append({
                    "phase": "execution",
                    "error": str(execution.error),
                    "traceback": getattr(execution.error, "traceback", None)
                })
                return {
                    "status": "error",
                    "error": str(execution.error),
                    **results
                }

            logger.info("Code execution completed successfully")

            # Format output nicely
            output_summary = ""
            if results["stdout"]:
                output_summary = "\n".join(results["stdout"])

            return {
                "status": "success",
                "message": "Code executed successfully",
                "output": output_summary,
                **results
            }

        finally:
            # Clean up sandbox
            try:
                sandbox.kill()
            except Exception as cleanup_error:
                logger.warning(f"Error cleaning up sandbox: {cleanup_error}")

    except ImportError as e:
        logger.error(f"e2b-code-interpreter package import error: {e}")
        return {
            "status": "error",
            "error": "e2b-code-interpreter package not installed or import error",
            "message": f"Run: pip install e2b-code-interpreter. Error: {e}"
        }

    except TimeoutError:
        logger.error(f"Sandbox execution timed out after {timeout}s")
        return {
            "status": "error",
            "error": f"Execution timed out after {timeout} seconds",
            "message": "Consider increasing the timeout or optimizing the code"
        }

    except Exception as e:
        logger.error(f"E2B sandbox error: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "error_type": type(e).__name__,
            "message": "An unexpected error occurred during sandbox execution"
        }
