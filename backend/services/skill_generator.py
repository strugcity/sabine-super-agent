"""
Skill Generator Service
========================

Given a detected skill gap, this service:
1. Uses Claude Haiku to generate a skill (manifest.json + handler.py)
2. Tests the generated code in the E2B sandbox
3. Creates a skill_proposals record with test results

This is the core of Sabine's autonomous skill acquisition pipeline.

PRD Requirements: SKILL-003 through SKILL-008
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase import Client, create_client

logger = logging.getLogger(__name__)

# Max retries for Haiku generation
MAX_GENERATION_RETRIES = 2

# Prompt template for skill generation
SKILL_GENERATION_PROMPT = """You are a Python skill generator for an AI agent named Sabine.

Given the following capability gap, generate a Python skill that addresses it.

## Gap Information
- Gap Type: {gap_type}
- Tool Name: {tool_name}
- Pattern Description: {pattern_description}
- Occurrence Count: {occurrence_count}

## Requirements
1. Generate a manifest.json that follows this exact schema:
{{
  "name": "skill_name_snake_case",
  "description": "Clear description of what the skill does",
  "version": "1.0.0",
  "parameters": {{
    "type": "object",
    "properties": {{
      "param_name": {{"type": "string", "description": "What this param does"}}
    }},
    "required": ["param_name"]
  }}
}}

2. Generate a handler.py with this exact signature:
```python
async def execute(params: dict) -> dict:
    # params will match the manifest's parameters schema
    # Must return a dict with at minimum: {{"status": "success"|"error", ...}}
```

3. The handler must:
   - Be completely self-contained (import everything it needs)
   - Handle errors gracefully and return error dicts, never raise
   - Not require any external API keys unless absolutely necessary
   - Be safe to run in a sandbox environment

## Output Format
Return a JSON object with exactly these keys:
{{
  "manifest": {{ ... the manifest.json content ... }},
  "handler_code": "... the complete handler.py source code ...",
  "test_code": "... a short test script that calls execute() with sample params ...",
  "roi_estimate": "Brief explanation of why this skill is valuable"
}}

Return ONLY the JSON, no markdown fences or extra text."""


def _get_supabase_client() -> Optional[Client]:
    """Get Supabase client."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


async def _call_haiku(prompt: str) -> Optional[str]:
    """
    Call Claude Haiku for skill generation.

    Parameters
    ----------
    prompt : str
        The generation prompt.

    Returns
    -------
    str or None
        Haiku's response text, or None on failure.
    """
    try:
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not set — cannot generate skills")
            return None

        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        if response.content and len(response.content) > 0:
            return response.content[0].text
        return None

    except Exception as e:
        logger.error("Haiku call failed: %s", e)
        return None


def _parse_generation_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Parse Haiku's JSON response into structured skill data.

    Handles cases where the response might be wrapped in markdown
    code fences or have extra whitespace.

    Parameters
    ----------
    response_text : str
        Raw response from Haiku.

    Returns
    -------
    dict or None
        Parsed skill data with manifest, handler_code, test_code, roi_estimate.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        # Remove opening fence (possibly with "json" label)
        first_newline = text.index("\n")
        text = text[first_newline + 1:]
    if text.endswith("```"):
        text = text[:-3].rstrip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse Haiku response as JSON: %s", e)
        logger.debug("Raw response: %s", text[:500])
        return None

    # Validate required keys
    required_keys = {"manifest", "handler_code"}
    if not required_keys.issubset(data.keys()):
        missing = required_keys - set(data.keys())
        logger.error("Haiku response missing keys: %s", missing)
        return None

    # Validate manifest structure
    manifest = data["manifest"]
    if not isinstance(manifest, dict) or "name" not in manifest:
        logger.error("Invalid manifest structure: missing 'name'")
        return None

    return data


async def _test_in_sandbox(handler_code: str, test_code: str) -> Dict[str, Any]:
    """
    Test generated skill code in E2B sandbox.

    Runs the handler code followed by the test code to verify
    the skill works correctly.

    Parameters
    ----------
    handler_code : str
        The handler.py source code.
    test_code : str
        Test script that exercises the handler.

    Returns
    -------
    dict
        Test results with passed (bool), stdout, stderr, errors.
    """
    try:
        # Lazy import to avoid circular deps
        from lib.skills.e2b_sandbox.handler import execute as sandbox_execute

        # Combine handler + test code into a single script
        combined_code = f"""
import asyncio
import json

# ---- Handler Code ----
{handler_code}

# ---- Test Code ----
async def _run_test():
{_indent(test_code, 4)}

# Run the test
result = asyncio.run(_run_test())
print("TEST_RESULT:", json.dumps(result) if isinstance(result, dict) else str(result))
"""

        result = await sandbox_execute({
            "code": combined_code,
            "timeout": 30,
        })

        passed = result.get("status") == "success"
        stdout: List[Any] = result.get("stdout", [])

        # Check if test produced a result
        test_output: Optional[str] = None
        for line in stdout:
            if isinstance(line, str) and line.startswith("TEST_RESULT:"):
                test_output = line[len("TEST_RESULT:"):].strip()

        return {
            "passed": passed,
            "test_output": test_output,
            "stdout": stdout,
            "stderr": result.get("stderr", []),
            "errors": result.get("errors", []),
        }

    except Exception as e:
        logger.error("Sandbox test failed: %s", e)
        return {
            "passed": False,
            "error": str(e),
            "stdout": [],
            "stderr": [],
            "errors": [{"phase": "sandbox_setup", "error": str(e)}],
        }


def _indent(code: str, spaces: int) -> str:
    """Indent each line of code by a number of spaces."""
    prefix = " " * spaces
    return "\n".join(prefix + line for line in code.splitlines())


async def generate_and_test_skill(gap_id: str) -> Dict[str, Any]:
    """
    Generate a skill proposal from a detected gap, test it, and save.

    This is the main entry point for skill generation. It:
    1. Fetches the gap record
    2. Calls Claude Haiku to generate manifest + handler
    3. Tests in E2B sandbox
    4. Creates a skill_proposals row

    Parameters
    ----------
    gap_id : str
        UUID of the skill_gaps record.

    Returns
    -------
    dict
        {"status": "proposed"|"failed", "proposal_id": ..., ...}
    """
    client = _get_supabase_client()
    if not client:
        return {"status": "failed", "error": "Supabase not configured"}

    # 1. Fetch gap
    gap_result = client.table("skill_gaps").select("*").eq("id", gap_id).single().execute()
    gap = gap_result.data
    if not gap:
        return {"status": "failed", "error": f"Gap {gap_id} not found"}

    logger.info(
        "Generating skill for gap: %s (tool=%s, type=%s)",
        gap_id, gap.get("tool_name"), gap.get("gap_type"),
    )

    # Update gap status to researching
    client.table("skill_gaps")\
        .update({"status": "researching"})\
        .eq("id", gap_id)\
        .execute()

    # 2. Generate skill with Haiku
    prompt = SKILL_GENERATION_PROMPT.format(
        gap_type=gap.get("gap_type", "unknown"),
        tool_name=gap.get("tool_name", "unknown"),
        pattern_description=gap.get("pattern_description", ""),
        occurrence_count=gap.get("occurrence_count", 0),
    )

    generated: Optional[Dict[str, Any]] = None
    for attempt in range(MAX_GENERATION_RETRIES + 1):
        response = await _call_haiku(prompt)
        if response:
            generated = _parse_generation_response(response)
            if generated:
                break
        logger.warning("Generation attempt %d failed, retrying...", attempt + 1)

    if not generated:
        logger.error("Failed to generate skill after %d attempts", MAX_GENERATION_RETRIES + 1)
        client.table("skill_gaps")\
            .update({"status": "open"})\
            .eq("id", gap_id)\
            .execute()
        return {"status": "failed", "error": "Haiku generation failed"}

    # 3. Test in sandbox
    test_code = generated.get("test_code", "return {'status': 'success', 'note': 'no test provided'}")
    test_results = await _test_in_sandbox(
        handler_code=generated["handler_code"],
        test_code=test_code,
    )
    sandbox_passed = test_results.get("passed", False)

    logger.info(
        "Sandbox test %s for gap %s (skill=%s)",
        "PASSED" if sandbox_passed else "FAILED",
        gap_id,
        generated["manifest"].get("name", "unknown"),
    )

    # 4. Create proposal
    proposal: Dict[str, Any] = {
        "gap_id": gap_id,
        "user_id": gap["user_id"],
        "skill_name": generated["manifest"]["name"],
        "description": generated["manifest"].get("description", ""),
        "manifest_json": generated["manifest"],
        "handler_code": generated["handler_code"],
        "test_results": test_results,
        "sandbox_passed": sandbox_passed,
        "roi_estimate": generated.get("roi_estimate", ""),
        "status": "pending",
    }

    proposal_result = client.table("skill_proposals").insert(proposal).execute()
    proposal_id: Optional[str] = proposal_result.data[0]["id"] if proposal_result.data else None

    # Update gap status
    client.table("skill_gaps")\
        .update({"status": "proposed"})\
        .eq("id", gap_id)\
        .execute()

    logger.info(
        "Created skill proposal %s for gap %s (sandbox_passed=%s)",
        proposal_id, gap_id, sandbox_passed,
    )

    return {
        "status": "proposed",
        "proposal_id": proposal_id,
        "skill_name": generated["manifest"]["name"],
        "sandbox_passed": sandbox_passed,
        "test_results": test_results,
    }


async def generate_skill_from_description(
    user_id: str,
    description: str,
) -> Dict[str, Any]:
    """
    Generate and test a skill from a free-text description.

    This is the manual trigger path -- the user describes what they want
    and we generate a proposal directly (no gap record needed).

    Parameters
    ----------
    user_id : str
        User requesting the skill.
    description : str
        Free-text description of what the skill should do.

    Returns
    -------
    dict
        {"status": "proposed"|"failed", "proposal_id": ..., ...}
    """
    client = _get_supabase_client()
    if not client:
        return {"status": "failed", "error": "Supabase not configured"}

    logger.info("Generating skill from description for user %s", user_id)

    # Generate using a simpler prompt
    prompt = SKILL_GENERATION_PROMPT.format(
        gap_type="user_requested",
        tool_name="N/A",
        pattern_description=description,
        occurrence_count=0,
    )

    response = await _call_haiku(prompt)
    if not response:
        return {"status": "failed", "error": "Haiku generation failed"}

    generated = _parse_generation_response(response)
    if not generated:
        return {"status": "failed", "error": "Failed to parse generated skill"}

    # Test in sandbox
    test_code = generated.get("test_code", "return {'status': 'success'}")
    test_results = await _test_in_sandbox(
        handler_code=generated["handler_code"],
        test_code=test_code,
    )

    # Create proposal (no gap_id)
    proposal: Dict[str, Any] = {
        "user_id": user_id,
        "skill_name": generated["manifest"]["name"],
        "description": generated["manifest"].get("description", description),
        "manifest_json": generated["manifest"],
        "handler_code": generated["handler_code"],
        "test_results": test_results,
        "sandbox_passed": test_results.get("passed", False),
        "roi_estimate": generated.get("roi_estimate", ""),
        "status": "pending",
    }

    result = client.table("skill_proposals").insert(proposal).execute()
    proposal_id: Optional[str] = result.data[0]["id"] if result.data else None

    return {
        "status": "proposed",
        "proposal_id": proposal_id,
        "skill_name": generated["manifest"]["name"],
        "sandbox_passed": test_results.get("passed", False),
    }
