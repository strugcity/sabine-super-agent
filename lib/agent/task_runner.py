"""
Task Runner - Orchestration logic for Dream Team tasks

This module contains the task execution and dispatch logic moved from server.py
as part of Phase 2: Separate Agent Cores refactoring.

Functions:
- _task_requires_tool_execution: Heuristic to determine if a task needs tool use
- _dispatch_task: Auto-dispatch callback for task queue
- _run_task_agent: Main task execution logic (now calls run_task_agent())
"""

import logging
from typing import Dict

from backend.services.task_queue import Task, get_task_queue_service
from backend.services.output_sanitization import (
    sanitize_error_message,
    sanitize_for_logging,
)

logger = logging.getLogger(__name__)


def _task_requires_tool_execution(payload: dict) -> bool:
    """
    Determine if a task payload indicates that tool execution is required.

    This heuristic checks for keywords that suggest the task needs to produce
    actual artifacts (files, issues, code execution) rather than just analysis.

    Args:
        payload: The task payload dictionary

    Returns:
        True if the task likely requires tool execution, False otherwise
    """
    # Keywords that suggest tool execution is needed
    action_keywords = [
        # File/code creation keywords
        "implement", "create", "write", "build", "add", "generate",
        "deploy", "install", "configure", "setup", "update", "modify",
        # GitHub-specific
        "commit", "push", "pull request", "pr", "issue", "file",
        # Execution keywords
        "run", "execute", "test", "compile",
        # Specific tool hints
        "github_issues", "create_file", "update_file", "run_python",
    ]

    # Keywords that suggest analysis-only (no tools needed)
    analysis_keywords = [
        "analyze", "review", "assess", "evaluate", "describe",
        "explain", "summarize", "list", "identify", "recommend",
        "plan", "design", "spec", "specification", "requirements",
    ]

    # Convert payload to searchable string
    payload_text = str(payload).lower()

    # Check for action keywords
    has_action_keywords = any(kw in payload_text for kw in action_keywords)

    # Check for analysis keywords (these might not need tools)
    has_analysis_keywords = any(kw in payload_text for kw in analysis_keywords)

    # Check for explicit tool requirements in payload
    explicit_tool_requirement = (
        payload.get("requires_tools", False) or
        payload.get("deliverables") is not None or
        payload.get("target_files") is not None or
        "MUST use" in str(payload) or
        "use github_issues" in payload_text or
        "use the tool" in payload_text
    )

    # If explicit requirement, always require tools
    if explicit_tool_requirement:
        return True

    # If has action keywords but not purely analysis, likely needs tools
    if has_action_keywords and not (has_analysis_keywords and not has_action_keywords):
        return True

    return False


async def _dispatch_task(task: Task):
    """
    Dispatch callback for auto-dispatch after task completion.

    Called by TaskQueueService when a task completes.

    Uses atomic claiming to prevent race conditions - if another worker
    already claimed this task, the claim will fail and we skip execution.
    """
    service = get_task_queue_service()

    # Claim the task atomically
    # This returns the fresh task data if successful, None if already claimed
    claim_result = await service.claim_task_result(task.id)

    if claim_result.success:
        # Refresh task data from claim result for accurate started_at
        # Note: claim_task_result returns minimal data, so we use the original task
        # but could fetch fresh if needed
        logger.info(f"Handshake: Auto-dispatching Task {task.id} to {task.role}")
        await _run_task_agent(task)
    else:
        # Task already claimed by another worker - this is expected in concurrent scenarios
        logger.debug(
            f"Task {task.id} already claimed (likely by concurrent dispatch), skipping"
        )


async def _run_task_agent(task: Task):
    """
    Run the agent for a task.

    Extracts the message from payload and runs the task agent (run_task_agent).
    Sends real-time updates to Slack (threaded by task).

    Context Propagation: If this task depends on other tasks, their results
    are fetched and included as context for this agent.
    
    Phase 2 Update: Now calls run_task_agent() from task_agent.py module instead
    of the generic run_agent().
    """
    from lib.agent.slack_manager import send_task_update, log_agent_event, clear_task_thread
    from lib.agent.task_agent import run_task_agent

    service = get_task_queue_service()

    # Ensure dispatch callback is set for auto-dispatch chain
    if not service._dispatch_callback:
        service.set_dispatch_callback(_dispatch_task)

    try:
        # Extract message from payload - check multiple fields for flexibility
        # Priority: message > objective > instructions > fallback to full payload
        message = (
            task.payload.get("message") or
            task.payload.get("objective") or
            task.payload.get("instructions") or
            ""
        )
        if not message:
            message = f"Execute task: {task.payload}"

        # === CONTEXT PROPAGATION ===
        # Fetch results from parent tasks (dependencies) and include as context
        parent_context = ""
        if task.depends_on and len(task.depends_on) > 0:
            logger.info(f"Task {task.id} has {len(task.depends_on)} parent dependencies - fetching context")
            parent_results = []

            for parent_id in task.depends_on:
                parent_task = await service.get_task(parent_id)
                if parent_task and parent_task.result:
                    parent_response = parent_task.result.get("response", "")
                    if parent_response:
                        parent_results.append({
                            "task_id": str(parent_id),
                            "role": parent_task.role,
                            "task_name": parent_task.payload.get("name", "Unknown Task"),
                            "output": parent_response
                        })
                        logger.info(f"  - Got context from parent task {parent_id} ({parent_task.role}): {len(parent_response)} chars")

            if parent_results:
                parent_context = "\n\n=== CONTEXT FROM PREVIOUS TASKS ===\n"
                parent_context += "The following tasks have been completed before yours. Use their outputs as context:\n\n"

                for i, result in enumerate(parent_results, 1):
                    parent_context += f"--- Task {i}: {result['task_name']} (by {result['role']}) ---\n"
                    parent_context += f"{result['output']}\n\n"

                parent_context += "=== END OF PREVIOUS TASK CONTEXT ===\n\n"
                parent_context += "Now, here is YOUR task:\n\n"

                logger.info(f"Built parent context ({len(parent_context)} chars) from {len(parent_results)} tasks")

        # === REPO CONTEXT INJECTION ===
        # Extract repo targeting from payload (injected by create_task)
        repo_context = ""
        if "_repo_context" in task.payload:
            rc = task.payload["_repo_context"]
            repo_context = f"""
=== REPOSITORY TARGETING (MANDATORY) ===
Target Repository: {rc.get('owner')}/{rc.get('repo')}
{rc.get('instruction', '')}

When using github_issues tool, you MUST use:
- owner: "{rc.get('owner')}"
- repo: "{rc.get('repo')}"

DO NOT use any other repository. This is enforced by the orchestration system.
=== END REPOSITORY TARGETING ===

"""
            logger.info(f"Injected repo context: {rc.get('owner')}/{rc.get('repo')}")

        # Combine repo context, parent context, and task message
        full_message = repo_context + parent_context + message

        logger.info(f"Task message extracted ({len(full_message)} chars, {len(parent_context)} from parents, {len(repo_context)} repo context): {message[:200]}...")

        user_id = task.payload.get("user_id", "00000000-0000-0000-0000-000000000001")

        logger.info(f"Running agent for task {task.id} (role: {task.role})")

        # Send task_started event to Slack
        await send_task_update(
            task_id=task.id,
            role=task.role,
            event_type="task_started",
            message=f"Starting task execution",
            details=message[:200] if len(message) > 200 else message
        )

        # === PHASE 2: Call run_task_agent() instead of run_agent() ===
        # This uses the specialized Dream Team agent with:
        # - Only Dream Team tools (GitHub, sandbox, Slack, project board)
        # - Role manifest for specialized instructions
        # - No deep context (custody, calendar, preferences)
        # - No memory retrieval from Sabine's context engine
        result = await run_task_agent(
            user_id=user_id,
            session_id=f"task-{task.id}",
            user_message=full_message,
            role=task.role,  # REQUIRED for task agents
        )

        if result.get("success"):
            # === TOOL EXECUTION VERIFICATION ===
            # Check if the agent actually used tools (especially for code/file tasks)
            tool_execution = result.get("tool_execution", {})
            tools_called = tool_execution.get("tools_called", [])
            call_count = tool_execution.get("call_count", 0)
            executions = tool_execution.get("executions", [])

            # Determine if this task requires tool execution
            # Tasks with these keywords in payload likely need actual tool usage
            task_requires_tools = _task_requires_tool_execution(task.payload)

            # Extract enhanced tool execution metrics
            success_count = tool_execution.get("success_count", 0)
            failure_count = tool_execution.get("failure_count", 0)
            artifacts_created = tool_execution.get("artifacts_created", [])
            all_succeeded = tool_execution.get("all_succeeded", False)

            # Log tool execution details
            logger.info(f"Task {task.id} tool execution summary:")
            logger.info(f"  - Tools called: {tools_called}")
            logger.info(f"  - Call count: {call_count}")
            logger.info(f"  - Success/Failure: {success_count}/{failure_count}")
            logger.info(f"  - Artifacts created: {artifacts_created}")
            logger.info(f"  - Task requires tools: {task_requires_tools}")

            # Build verification result with enhanced checks
            verification_passed = True
            verification_warnings = []

            # Check 1: Tools were called if required
            if task_requires_tools and call_count == 0:
                verification_passed = False
                verification_warnings.append(
                    "NO_TOOLS_CALLED: Task requires tool execution but no tools were called. "
                    "Agent may have only planned/described work without executing it."
                )

            # Check 2: All tool calls succeeded (no failures)
            if failure_count > 0:
                verification_passed = False
                # Get failure details
                failed_tools = [
                    e for e in executions
                    if e.get("type") == "tool_result" and e.get("status") == "error"
                ]
                failure_details = "; ".join([
                    f"{t['tool_name']}: {t.get('error', 'unknown error')}"
                    for t in failed_tools[:3]  # Limit to first 3
                ])
                verification_warnings.append(
                    f"TOOL_FAILURES: {failure_count} tool call(s) failed. Details: {failure_details}"
                )

            # Check 3: For implementation tasks, verify artifacts were created
            if task_requires_tools and call_count > 0 and success_count > 0:
                # If we expected file operations but got no artifacts, warn
                payload_text = str(task.payload).lower()
                expects_files = any(kw in payload_text for kw in [
                    "create_file", "update_file", "write file", "create issue"
                ])
                if expects_files and not artifacts_created:
                    verification_warnings.append(
                        "NO_ARTIFACTS: Task expected file/issue creation but no artifacts were confirmed. "
                        "The operation may have failed silently."
                    )

            verification_warning = " | ".join(verification_warnings) if verification_warnings else None

            # Send completion update to Slack (with verification status)
            response_preview = result.get("response", "")[:300]
            if verification_passed:
                completion_message = f"Task completed successfully ({success_count} tool calls succeeded)"
                if artifacts_created:
                    completion_message += f"\nArtifacts: {', '.join(artifacts_created[:3])}"
            else:
                completion_message = f"⚠️ Task completed with issues: {verification_warning}"

            await send_task_update(
                task_id=task.id,
                role=task.role,
                event_type="task_completed" if verification_passed else "task_completed_unverified",
                message=completion_message,
                details=f"Tools used: {tools_called or 'None'}\n\n{response_preview}"
            )

            # Store result with enhanced tool execution metadata
            task_result = {
                "response": result.get("response"),
                "tool_execution": {
                    "tools_called": tools_called,
                    "call_count": call_count,
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "artifacts_created": artifacts_created,
                    "all_succeeded": all_succeeded,
                    "verification_passed": verification_passed,
                    "verification_warnings": verification_warnings
                }
            }

            # === PERSISTENT AUDIT LOGGING WITH TASK CONTEXT ===
            # Log tool executions to database with task_id for traceability
            if executions:
                try:
                    from backend.services.audit_logging import log_tool_executions_batch
                    user_id = task.payload.get("user_id", "00000000-0000-0000-0000-000000000001")
                    logged_count = await log_tool_executions_batch(
                        executions=executions,
                        task_id=task.id,
                        user_id=user_id,
                        agent_role=task.role,
                    )
                    logger.info(f"Task {task.id}: {logged_count} tool executions logged to audit trail")
                except ImportError:
                    logger.debug("Audit logging service not available")
                except Exception as e:
                    logger.warning(f"Task {task.id} audit logging failed (non-fatal): {e}")

            await service.complete_task(
                task.id,
                result=task_result,
                auto_dispatch=True  # Trigger next tasks in chain
            )

            # Clean up Slack thread tracking to prevent memory leak (P3 fix)
            clear_task_thread(task.id)

            if verification_passed:
                logger.info(f"Task {task.id} completed successfully (verified: {success_count}/{call_count} tool calls succeeded)")
            else:
                logger.warning(f"Task {task.id} completed with VERIFICATION WARNINGS: {verification_warnings}")
        else:
            error_msg = result.get("error", "Agent execution failed")
            # Sanitize error message before storing/sending
            sanitized_error_msg = sanitize_error_message(error_msg)

            # Use fail_task_with_retry for automatic retry on transient errors
            fail_result = await service.fail_task_with_retry(
                task.id,
                error=sanitized_error_msg
            )

            # Send appropriate Slack update based on retry status
            if fail_result.success and fail_result.data.get("retry_scheduled"):
                retry_info = fail_result.data
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="task_failed",
                    message=f"Task failed (attempt {retry_info['retry_count']}/{retry_info['max_retries']}), "
                            f"will retry in {retry_info['backoff_seconds']}s: {sanitized_error_msg}"
                )
                logger.warning(
                    f"Task {task.id} failed (attempt {retry_info['retry_count']}), "
                    f"retry scheduled for {retry_info['next_retry_at']}"
                )
            else:
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="task_failed",
                    message=f"Task permanently failed: {sanitized_error_msg}"
                )
                # Clean up Slack thread tracking for permanent failures (P3 fix)
                clear_task_thread(task.id)
                logger.error(f"Task {task.id} permanently failed: {sanitize_for_logging(error_msg)}")

    except Exception as e:
        # Sanitize exception before logging and storing
        sanitized_exc = sanitize_error_message(e)
        logger.error(f"Error running agent for task {task.id}: {sanitize_for_logging(str(e))}")

        # Use fail_task_with_retry for exceptions too (often transient network/API errors)
        fail_result = await service.fail_task_with_retry(task.id, error=sanitized_exc)

        # Send error update to Slack
        try:
            if fail_result.success and fail_result.data.get("retry_scheduled"):
                retry_info = fail_result.data
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="error",
                    message=f"Exception (attempt {retry_info['retry_count']}/{retry_info['max_retries']}), "
                            f"will retry in {retry_info['backoff_seconds']}s: {sanitized_exc}"
                )
            else:
                await send_task_update(
                    task_id=task.id,
                    role=task.role,
                    event_type="error",
                    message=f"Exception during task execution: {sanitized_exc}"
                )
                # Clean up Slack thread tracking for permanent failures (P3 fix)
                clear_task_thread(task.id)
        except Exception as slack_error:
            # Don't fail the main operation if Slack update fails
            logger.warning(f"Slack notification failed for task {task.id}: {slack_error}")
