"""
Output Sanitization Service
============================

This module provides comprehensive output sanitization for API responses
to prevent sensitive data leakage. It handles:

1. Sensitive Data Redaction: API keys, tokens, passwords, credentials
2. PII Protection: Email addresses, phone numbers, SSNs (optional)
3. Path Sanitization: Removes internal file paths from error messages
4. Error Message Cleaning: Strips stack traces and internal details
5. Field Filtering: Removes internal-only fields from responses
6. Size Limiting: Prevents oversized responses

Owner: @backend-architect-sabine
PRD Reference: Project Dream Team - Security & Output Sanitization
"""

import html
import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Maximum response size (characters)
MAX_RESPONSE_SIZE = 50000

# Maximum error message length
MAX_ERROR_MESSAGE_LENGTH = 500

# Fields that should never appear in API responses
INTERNAL_ONLY_FIELDS: Set[str] = {
    "_internal",
    "_debug",
    "_trace",
    "_stack",
    "_supabase_client",
    "_db_connection",
    "_raw_error",
    "_full_traceback",
    "internal_id",
    "debug_info",
}

# Fields that contain sensitive data and should be redacted
SENSITIVE_FIELDS: Set[str] = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "api-key",
    "authorization",
    "auth_token",
    "access_token",
    "refresh_token",
    "private_key",
    "secret_key",
    "credentials",
    "credit_card",
    "card_number",
    "cvv",
    "ssn",
    "social_security",
}

# =============================================================================
# Sensitive Data Patterns
# =============================================================================

# Patterns for detecting and redacting sensitive data in strings
# NOTE: Order matters! More specific patterns should come BEFORE generic ones.
SENSITIVE_PATTERNS = [
    # Specific API key formats (MUST come first before generic token pattern)
    (r'sk-ant-[a-zA-Z0-9_\-]+', '***ANTHROPIC_KEY***'),
    (r'sk-[a-zA-Z0-9_\-]{20,}', '***OPENAI_KEY***'),
    (r'ghp_[a-zA-Z0-9]{20,}', '***GITHUB_TOKEN***'),
    (r'gho_[a-zA-Z0-9]{20,}', '***GITHUB_OAUTH***'),
    (r'github_pat_[a-zA-Z0-9_]{20,}', '***GITHUB_PAT***'),
    (r'xoxb-[a-zA-Z0-9\-]+', '***SLACK_TOKEN***'),
    (r'xoxp-[a-zA-Z0-9\-]+', '***SLACK_TOKEN***'),

    # JWTs (common format) - before generic patterns
    (r'eyJ[a-zA-Z0-9_\-]{50,}\.eyJ[a-zA-Z0-9_\-]+\.[a-zA-Z0-9_\-]+', '***JWT_TOKEN***'),
    (r'eyJ[a-zA-Z0-9_\-]{50,}', '***JWT_PARTIAL***'),

    # AWS credentials
    (r'AKIA[0-9A-Z]{16}', '***AWS_ACCESS_KEY***'),
    (r'aws_secret_access_key\s*=\s*[^\s]+', 'aws_secret_access_key=***REDACTED***'),

    # Connection strings
    (r'(postgres|mysql|mongodb|redis)://[^\s"\']+', r'\1://***CONNECTION_STRING***'),
    (r'(DATABASE_URL|REDIS_URL|MONGODB_URI)\s*=\s*[^\s]+', r'\1=***REDACTED***'),

    # Google credentials
    (r'"client_secret"\s*:\s*"[^"]+"', '"client_secret": "***REDACTED***"'),
    (r'"refresh_token"\s*:\s*"[^"]+"', '"refresh_token": "***REDACTED***"'),

    # Generic API key/token patterns (AFTER specific patterns)
    (r'(api[_-]?key|apikey)["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{10,})', r'\1=***REDACTED***'),
    (r'(bearer\s+)([a-zA-Z0-9_\-\.]{20,})', r'\1***REDACTED***'),
    # Generic token/secret/password - only match assignment patterns, not standalone words
    (r'((?:^|[^a-zA-Z])(?:token|secret|password|credential))["\']?\s*[:=]\s*["\']?([a-zA-Z0-9_\-]{8,})', r'\1=***REDACTED***'),
]

# PII Patterns (optional - can be enabled/disabled)
PII_PATTERNS = [
    # Email addresses
    (r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '***EMAIL***'),

    # Phone numbers (US format)
    (r'\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b', '***PHONE***'),

    # SSN
    (r'\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b', '***SSN***'),

    # Credit card numbers (basic pattern)
    (r'\b(?:\d{4}[-.\s]?){3}\d{4}\b', '***CARD_NUMBER***'),
]

# Path patterns to sanitize (remove internal file paths)
PATH_PATTERNS = [
    # Windows paths
    (r'[A-Za-z]:\\(?:[^\\/:*?"<>|\r\n]+\\)*[^\\/:*?"<>|\r\n]*', '***PATH***'),
    # Unix paths (be careful not to match URLs)
    (r'(?<![a-zA-Z0-9])\/(?:home|Users|var|tmp|etc|opt|usr)\/[^\s:]+', '***PATH***'),
    # Python traceback file paths
    (r'File "([^"]+)", line \d+', 'File "***PATH***", line ***'),
]

# =============================================================================
# Core Sanitization Functions
# =============================================================================

def redact_sensitive_strings(text: str, include_pii: bool = False) -> str:
    """
    Redact sensitive data from a string.

    Args:
        text: The string to sanitize
        include_pii: If True, also redact PII (emails, phones, etc.)

    Returns:
        Sanitized string with sensitive data redacted
    """
    if not text or not isinstance(text, str):
        return text

    result = text

    # Apply sensitive patterns
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Apply PII patterns if requested
    if include_pii:
        for pattern, replacement in PII_PATTERNS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    return result


def sanitize_path(text: str) -> str:
    """
    Remove internal file paths from text (e.g., error messages).

    Args:
        text: Text that may contain file paths

    Returns:
        Text with paths sanitized
    """
    if not text or not isinstance(text, str):
        return text

    result = text
    for pattern, replacement in PATH_PATTERNS:
        result = re.sub(pattern, replacement, result)

    return result


def sanitize_error_message(error: Union[str, Exception], max_length: int = MAX_ERROR_MESSAGE_LENGTH) -> str:
    """
    Sanitize an error message for safe external display.

    Removes:
    - Internal file paths
    - Stack traces
    - Sensitive credentials
    - Excessive detail

    Args:
        error: Error string or exception
        max_length: Maximum length of output

    Returns:
        Sanitized error message
    """
    if isinstance(error, Exception):
        error_text = str(error)
    else:
        error_text = str(error) if error else ""

    # Remove stack traces
    error_text = re.sub(r'Traceback \(most recent call last\):.*?(?=\n[A-Z]|\Z)', '', error_text, flags=re.DOTALL)

    # Remove file paths
    error_text = sanitize_path(error_text)

    # Redact sensitive data
    error_text = redact_sensitive_strings(error_text)

    # Remove excessive whitespace
    error_text = re.sub(r'\s+', ' ', error_text).strip()

    # Truncate if too long
    if len(error_text) > max_length:
        error_text = error_text[:max_length - 3] + "..."

    return error_text


def filter_internal_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Remove internal-only fields from a dictionary.

    Args:
        data: Dictionary that may contain internal fields

    Returns:
        Dictionary with internal fields removed
    """
    if not isinstance(data, dict):
        return data

    return {
        key: filter_internal_fields(value) if isinstance(value, dict) else value
        for key, value in data.items()
        if key not in INTERNAL_ONLY_FIELDS and not key.startswith('_')
    }


def redact_sensitive_fields(data: Any, redact_pii: bool = False) -> Any:
    """
    Recursively redact sensitive fields in a data structure.

    Args:
        data: Data structure (dict, list, or primitive)
        redact_pii: If True, also redact PII in string values

    Returns:
        Data with sensitive fields redacted
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = key.lower()

            # Check if key indicates sensitive data
            if any(sensitive in key_lower for sensitive in SENSITIVE_FIELDS):
                result[key] = "***REDACTED***"
            elif isinstance(value, str):
                result[key] = redact_sensitive_strings(value, include_pii=redact_pii)
            elif isinstance(value, (dict, list)):
                result[key] = redact_sensitive_fields(value, redact_pii=redact_pii)
            else:
                result[key] = value
        return result

    elif isinstance(data, list):
        return [redact_sensitive_fields(item, redact_pii=redact_pii) for item in data]

    elif isinstance(data, str):
        return redact_sensitive_strings(data, include_pii=redact_pii)

    else:
        return data


def escape_html(text: str) -> str:
    """
    Escape HTML special characters to prevent XSS.

    Args:
        text: Text that may contain HTML

    Returns:
        HTML-escaped text
    """
    if not text or not isinstance(text, str):
        return text

    return html.escape(text)


def truncate_response(data: Any, max_size: int = MAX_RESPONSE_SIZE) -> Any:
    """
    Truncate response data to prevent oversized responses.

    Args:
        data: Response data
        max_size: Maximum size in characters

    Returns:
        Truncated data if necessary
    """
    import json

    if data is None:
        return data

    try:
        data_str = json.dumps(data) if not isinstance(data, str) else data
    except (TypeError, ValueError):
        data_str = str(data)

    if len(data_str) <= max_size:
        return data

    # For strings, truncate directly
    if isinstance(data, str):
        return data[:max_size - 50] + f"... [TRUNCATED - {len(data)} chars total]"

    # For dicts/lists, try to preserve structure but truncate values
    if isinstance(data, dict):
        truncated = {}
        current_size = 0

        for key, value in data.items():
            value_str = json.dumps(value) if not isinstance(value, str) else value
            value_size = len(value_str)

            if current_size + value_size > max_size - 100:
                truncated[key] = f"[TRUNCATED - {value_size} chars]" if value_size > 100 else value
            else:
                truncated[key] = value

            current_size += value_size
            if current_size > max_size:
                truncated["_truncation_warning"] = f"Response truncated at {max_size} chars"
                break

        return truncated

    return {"_truncated": True, "_original_size": len(data_str)}


# =============================================================================
# High-Level Sanitization Functions
# =============================================================================

def sanitize_api_response(
    response: Dict[str, Any],
    redact_credentials: bool = True,
    redact_pii: bool = False,
    filter_internal: bool = True,
    max_size: int = MAX_RESPONSE_SIZE,
) -> Dict[str, Any]:
    """
    Comprehensive API response sanitization.

    This is the main entry point for sanitizing API responses before
    they are returned to clients.

    Args:
        response: The API response dictionary
        redact_credentials: Redact API keys, tokens, passwords
        redact_pii: Redact PII (emails, phones, SSNs)
        filter_internal: Remove internal-only fields
        max_size: Maximum response size

    Returns:
        Sanitized response safe for external consumption

    Example:
        >>> raw_response = {"data": {"api_key": "sk-123456"}, "_debug": "internal"}
        >>> safe_response = sanitize_api_response(raw_response)
        >>> print(safe_response)
        {"data": {"api_key": "***REDACTED***"}}
    """
    if not isinstance(response, dict):
        return response

    result = response.copy()

    # Step 1: Filter internal fields
    if filter_internal:
        result = filter_internal_fields(result)

    # Step 2: Redact sensitive data
    if redact_credentials:
        result = redact_sensitive_fields(result, redact_pii=redact_pii)

    # Step 3: Sanitize error messages if present
    if "error" in result and result["error"]:
        result["error"] = sanitize_error_message(result["error"])

    if "detail" in result and isinstance(result["detail"], str):
        result["detail"] = sanitize_error_message(result["detail"])

    # Step 4: Truncate if too large
    result = truncate_response(result, max_size=max_size)

    return result


def sanitize_agent_output(
    output: str,
    redact_credentials: bool = True,
    redact_pii: bool = False,
    escape_for_html: bool = False,
    max_length: int = 10000,
) -> str:
    """
    Sanitize agent/LLM output text.

    Use this for sanitizing the "response" field from agent runs.

    Args:
        output: The agent's text output
        redact_credentials: Redact API keys, tokens, etc.
        redact_pii: Redact PII (emails, phones)
        escape_for_html: Escape HTML special characters
        max_length: Maximum output length

    Returns:
        Sanitized output string
    """
    if not output or not isinstance(output, str):
        return output

    result = output

    # Redact sensitive data
    if redact_credentials:
        result = redact_sensitive_strings(result, include_pii=redact_pii)

    # Escape HTML if needed
    if escape_for_html:
        result = escape_html(result)

    # Truncate if too long
    if len(result) > max_length:
        result = result[:max_length - 50] + f"... [TRUNCATED - {len(output)} chars total]"

    return result


def sanitize_tool_output(
    output: Any,
    tool_name: str,
    redact_credentials: bool = True,
) -> Any:
    """
    Sanitize tool execution output.

    Different tools may expose different sensitive data,
    so this provides tool-aware sanitization.

    Args:
        output: Tool output (dict, list, or string)
        tool_name: Name of the tool that produced this output
        redact_credentials: Redact credentials in output

    Returns:
        Sanitized tool output
    """
    if output is None:
        return output

    # Convert to dict if string JSON
    if isinstance(output, str):
        try:
            import json
            output = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return redact_sensitive_strings(output) if redact_credentials else output

    # Apply standard sanitization
    result = redact_sensitive_fields(output, redact_pii=False) if redact_credentials else output

    # Tool-specific sanitization
    if tool_name == "github_issues":
        # GitHub may return access tokens in some responses
        if isinstance(result, dict):
            for key in ["token", "installation_token", "access_token"]:
                if key in result:
                    result[key] = "***GITHUB_TOKEN***"

    elif tool_name == "run_python_sandbox":
        # Sandbox output may contain printed secrets
        if isinstance(result, dict) and "output" in result:
            result["output"] = redact_sensitive_strings(str(result["output"]))

    return result


# =============================================================================
# Logging Sanitization
# =============================================================================

def sanitize_for_logging(data: Any, max_length: int = 1000) -> str:
    """
    Sanitize data for safe logging.

    More aggressive than API sanitization - designed to prevent
    any sensitive data from appearing in logs.

    Args:
        data: Data to log
        max_length: Maximum log entry length

    Returns:
        String safe for logging
    """
    import json

    # Convert to string
    if isinstance(data, dict):
        # Redact all sensitive fields
        sanitized = redact_sensitive_fields(data, redact_pii=True)
        # Filter internal fields
        sanitized = filter_internal_fields(sanitized)
        try:
            data_str = json.dumps(sanitized)
        except (TypeError, ValueError):
            data_str = str(sanitized)
    elif isinstance(data, str):
        data_str = redact_sensitive_strings(data, include_pii=True)
    else:
        data_str = str(data)

    # Sanitize paths
    data_str = sanitize_path(data_str)

    # Truncate
    if len(data_str) > max_length:
        data_str = data_str[:max_length - 20] + f"... [{len(data_str)} chars]"

    return data_str
