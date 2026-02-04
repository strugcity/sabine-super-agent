"""
Tests for lib/skills/github/handler.py

Currently covers normalise_file_content — the guard that catches
over-escaped content from LLM tool calls before it hits the GitHub API.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# handler.py imports httpx at module level; normalise_file_content is pure
# string ops.  Mock httpx so the module loads without the network dep.
import unittest.mock as _mock
sys.modules.setdefault("httpx", _mock.MagicMock())

from lib.skills.github.handler import normalise_file_content


# =============================================================================
# normalise_file_content
# =============================================================================


def test_over_escaped_newlines_are_restored():
    """Single-line content with literal \\n is normalised to real newlines."""
    escaped = "line1\\nline2\\nline3"
    result = normalise_file_content(escaped)
    assert result == "line1\nline2\nline3"
    print("  [OK] Over-escaped \\n restored to real newlines")


def test_over_escaped_tabs_are_restored():
    """Literal \\t sequences are also normalised when \\n normalisation fires."""
    escaped = "function foo() {\\n\\treturn 1;\\n}"
    result = normalise_file_content(escaped)
    assert result == "function foo() {\n\treturn 1;\n}"
    print("  [OK] Over-escaped \\t restored alongside \\n")


def test_already_correct_newlines_untouched():
    """Content that already has real newlines is left completely alone."""
    correct = "line1\nline2\nline3"
    result = normalise_file_content(correct)
    assert result == correct
    print("  [OK] Correctly-newlined content untouched")


def test_mixed_real_and_literal_newlines_untouched():
    """If real newlines exist alongside literal \\n, do NOT touch it.

    This is the case for e.g. a JSON fixture file that legitimately
    contains the two-character sequence backslash-n as data.
    """
    mixed = 'first line\nsecond line with literal \\n inside'
    result = normalise_file_content(mixed)
    assert result == mixed
    print("  [OK] Mixed real + literal \\n left untouched (JSON fixture case)")


def test_empty_string():
    """Empty content round-trips cleanly."""
    assert normalise_file_content("") == ""
    print("  [OK] Empty string round-trips")


def test_no_newlines_at_all():
    """Single-line content with no \\n or newlines is untouched."""
    single = "just one line, no escapes"
    assert normalise_file_content(single) == single
    print("  [OK] Single line with no escapes untouched")


def test_realistic_tsx_over_escape():
    """Simulate the exact pattern that broke ErrorAlert.tsx on Vercel."""
    escaped_tsx = (
        "/**\\n"
        " * Enhanced Error Alert Component\\n"
        " */\\n"
        "\\n"
        "import React from 'react'\\n"
        "\\n"
        "export function ErrorAlert() {\\n"
        "\\treturn <div>error</div>\\n"
        "}"
    )
    result = normalise_file_content(escaped_tsx)

    # Must now be multi-line
    lines = result.split("\n")
    assert len(lines) == 9, f"Expected 9 lines, got {len(lines)}"

    # First line is the JSDoc open
    assert lines[0] == "/**"
    # Tab-indented return statement
    assert lines[7] == "\treturn <div>error</div>"
    # No literal backslash-n anywhere in output
    assert "\\n" not in result
    print("  [OK] Realistic TSX over-escape normalised correctly")


if __name__ == "__main__":
    print("=" * 60)
    print("Running GitHub Handler Tests")
    print("=" * 60)

    print("\n1. Over-escaped newlines restored...")
    test_over_escaped_newlines_are_restored()

    print("\n2. Over-escaped tabs restored...")
    test_over_escaped_tabs_are_restored()

    print("\n3. Already-correct newlines untouched...")
    test_already_correct_newlines_untouched()

    print("\n4. Mixed real + literal newlines untouched...")
    test_mixed_real_and_literal_newlines_untouched()

    print("\n5. Empty string...")
    test_empty_string()

    print("\n6. No newlines at all...")
    test_no_newlines_at_all()

    print("\n7. Realistic TSX over-escape (ErrorAlert.tsx pattern)...")
    test_realistic_tsx_over_escape()

    print("\n" + "=" * 60)
    print("All GitHub handler tests passed!")
    print("=" * 60)
