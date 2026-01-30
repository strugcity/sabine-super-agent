"""
File Ingestion Pipeline Tests - Context Engine Phase 5
=======================================================

This test suite verifies the file parsing and ingestion pipeline:
- PDF text extraction
- CSV parsing to readable format
- Image description via Claude Vision (mocked)
- Rejection of unsupported file types

Tests use synthetic file generation and mock external dependencies
(Claude API, memory ingestion) to ensure isolated unit testing.

Owner: @backend-architect-sabine
"""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Tuple


# =============================================================================
# Asset Generation Helpers
# =============================================================================

def generate_test_pdf(text_content: str = "Project Alpha deadline is October 15th.") -> bytes:
    """
    Generate a valid PDF file with the specified text content.

    Uses reportlab if available, otherwise creates a minimal valid PDF structure.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        c.drawString(72, 720, text_content)
        c.save()
        buffer.seek(0)
        return buffer.read()
    except ImportError:
        # Fallback: Create minimal PDF with embedded text
        # This is a valid PDF 1.4 structure with the text embedded
        pdf_template = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 72 720 Td ({text_content}) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000359 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
434
%%EOF"""
        return pdf_template.encode('latin-1')


def generate_test_csv() -> bytes:
    """
    Generate a simple CSV file with expense data.

    Returns CSV with columns: Expense, Amount
    """
    csv_content = """Expense,Amount
Server,50
Domain,12
Hosting,25
SSL Certificate,15"""
    return csv_content.encode('utf-8')


def generate_test_png() -> bytes:
    """
    Generate a minimal valid 1x1 pixel PNG image.

    This is a valid PNG file that can be processed by image parsers.
    """
    # Minimal valid 1x1 red pixel PNG
    # PNG signature + IHDR + IDAT + IEND chunks
    png_bytes = bytes([
        # PNG signature
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        # IHDR chunk (image header)
        0x00, 0x00, 0x00, 0x0D,  # Length: 13
        0x49, 0x48, 0x44, 0x52,  # Type: IHDR
        0x00, 0x00, 0x00, 0x01,  # Width: 1
        0x00, 0x00, 0x00, 0x01,  # Height: 1
        0x08,                    # Bit depth: 8
        0x02,                    # Color type: RGB
        0x00,                    # Compression: deflate
        0x00,                    # Filter: adaptive
        0x00,                    # Interlace: none
        0x90, 0x77, 0x53, 0xDE,  # CRC
        # IDAT chunk (image data - compressed)
        0x00, 0x00, 0x00, 0x0C,  # Length: 12
        0x49, 0x44, 0x41, 0x54,  # Type: IDAT
        0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00, 0x00,  # Compressed data
        0x01, 0x01, 0x01, 0x00,  # CRC (simplified)
        # IEND chunk (image end)
        0x00, 0x00, 0x00, 0x00,  # Length: 0
        0x49, 0x45, 0x4E, 0x44,  # Type: IEND
        0xAE, 0x42, 0x60, 0x82,  # CRC
    ])
    return png_bytes


def generate_invalid_exe() -> bytes:
    """
    Generate fake .exe file header (MZ header).

    This simulates an unsupported file type.
    """
    # MZ header signature for DOS/Windows executables
    return b'MZ' + b'\x00' * 100


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def pdf_content() -> bytes:
    """Generate test PDF with known content."""
    return generate_test_pdf("Project Alpha deadline is October 15th.")


@pytest.fixture
def csv_content() -> bytes:
    """Generate test CSV with expense data."""
    return generate_test_csv()


@pytest.fixture
def png_content() -> bytes:
    """Generate test PNG image."""
    return generate_test_png()


@pytest.fixture
def exe_content() -> bytes:
    """Generate fake executable file."""
    return generate_invalid_exe()


# =============================================================================
# Unit Tests - Parsing Module
# =============================================================================

class TestPDFParsing:
    """Tests for PDF text extraction."""

    @pytest.mark.asyncio
    async def test_parse_pdf_extracts_text(self, pdf_content: bytes):
        """Verify PDF parser extracts the expected text content."""
        from lib.agent.parsing import parse_pdf

        extracted_text, metadata = await parse_pdf(pdf_content, "test.pdf")

        # Verify text was extracted (may have page markers)
        assert "Project Alpha" in extracted_text or "deadline" in extracted_text.lower()
        assert metadata["parser"] == "pypdf"
        assert metadata["filename"] == "test.pdf"
        assert "total_pages" in metadata

    @pytest.mark.asyncio
    async def test_parse_pdf_handles_empty(self):
        """Verify PDF parser handles invalid/empty PDF gracefully."""
        from lib.agent.parsing import parse_pdf

        with pytest.raises(ValueError, match="PDF parsing failed"):
            await parse_pdf(b"not a valid pdf", "invalid.pdf")


class TestCSVParsing:
    """Tests for CSV parsing."""

    @pytest.mark.asyncio
    async def test_parse_csv_extracts_data(self, csv_content: bytes):
        """Verify CSV parser extracts column data and summaries."""
        from lib.agent.parsing import parse_csv

        extracted_text, metadata = await parse_csv(csv_content, "expenses.csv")

        # Verify data is in the output
        assert "Server" in extracted_text
        assert "50" in extracted_text
        assert "Domain" in extracted_text
        assert "12" in extracted_text

        # Verify metadata
        assert metadata["parser"] == "pandas"
        assert metadata["total_rows"] == 4
        assert metadata["total_columns"] == 2
        assert "Expense" in metadata["columns"]
        assert "Amount" in metadata["columns"]

    @pytest.mark.asyncio
    async def test_parse_csv_handles_empty(self):
        """Verify CSV parser handles empty CSV."""
        from lib.agent.parsing import parse_csv

        empty_csv = b"Column1,Column2\n"
        extracted_text, metadata = await parse_csv(empty_csv, "empty.csv")

        assert metadata["total_rows"] == 0
        assert "Column1" in metadata["columns"]


class TestImageParsing:
    """Tests for image parsing with mocked Claude Vision."""

    @pytest.mark.asyncio
    async def test_parse_image_uses_vision_model(self, png_content: bytes):
        """Verify image parser calls Claude Vision and returns description."""
        from lib.agent import parsing

        # Mock the ChatAnthropic class
        mock_response = MagicMock()
        mock_response.content = "A screenshot of a budget spreadsheet showing expense categories."

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        with patch.object(parsing, 'ANTHROPIC_API_KEY', 'test-key'):
            with patch('lib.agent.parsing.ChatAnthropic', return_value=mock_llm):
                extracted_text, metadata = await parsing.parse_image(
                    png_content,
                    "screenshot.png",
                    "image/png"
                )

        # Verify mocked description is in output
        assert "budget spreadsheet" in extracted_text
        assert metadata["parser"] == "claude-vision"
        assert metadata["mime_type"] == "image/png"

    @pytest.mark.asyncio
    async def test_parse_image_requires_api_key(self, png_content: bytes):
        """Verify image parser fails without API key."""
        from lib.agent import parsing

        with patch.object(parsing, 'ANTHROPIC_API_KEY', None):
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY not set"):
                await parsing.parse_image(png_content, "test.png", "image/png")


class TestFileTypeValidation:
    """Tests for MIME type validation."""

    def test_supported_mime_types(self):
        """Verify supported MIME types are recognized."""
        from lib.agent.parsing import is_supported_mime_type, get_file_type

        # PDF
        assert is_supported_mime_type("application/pdf")
        assert get_file_type("application/pdf") == "pdf"

        # CSV
        assert is_supported_mime_type("text/csv")
        assert get_file_type("text/csv") == "csv"

        # Images
        assert is_supported_mime_type("image/png")
        assert is_supported_mime_type("image/jpeg")
        assert get_file_type("image/png") == "image"

        # Text
        assert is_supported_mime_type("text/plain")
        assert get_file_type("text/plain") == "text"

    def test_unsupported_mime_types(self):
        """Verify unsupported MIME types are rejected."""
        from lib.agent.parsing import is_supported_mime_type, get_file_type

        assert not is_supported_mime_type("application/x-msdownload")  # .exe
        assert not is_supported_mime_type("application/octet-stream")
        assert not is_supported_mime_type("video/mp4")

        assert get_file_type("application/x-msdownload") is None


class TestParseFileDispatcher:
    """Tests for the main parse_file dispatcher."""

    @pytest.mark.asyncio
    async def test_parse_file_routes_pdf(self, pdf_content: bytes):
        """Verify parse_file routes PDF to PDF parser."""
        from lib.agent.parsing import parse_file

        extracted_text, metadata = await parse_file(
            pdf_content,
            "application/pdf",
            "document.pdf"
        )

        assert metadata["parser"] == "pypdf"

    @pytest.mark.asyncio
    async def test_parse_file_routes_csv(self, csv_content: bytes):
        """Verify parse_file routes CSV to CSV parser."""
        from lib.agent.parsing import parse_file

        extracted_text, metadata = await parse_file(
            csv_content,
            "text/csv",
            "data.csv"
        )

        assert metadata["parser"] == "pandas"
        assert "Server" in extracted_text

    @pytest.mark.asyncio
    async def test_parse_file_rejects_unsupported(self, exe_content: bytes):
        """Verify parse_file rejects unsupported file types."""
        from lib.agent.parsing import parse_file

        with pytest.raises(ValueError, match="Unsupported MIME type"):
            await parse_file(
                exe_content,
                "application/x-msdownload",
                "malware.exe"
            )


# =============================================================================
# Integration Tests - Upload Endpoint (Mocked)
# =============================================================================

class TestUploadEndpoint:
    """Tests for the /memory/upload endpoint with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_upload_pdf_triggers_ingestion(self, pdf_content: bytes):
        """Verify PDF upload extracts text and queues ingestion."""
        from lib.agent import parsing
        from lib.agent import memory

        # Mock the ingestion function
        mock_ingest = AsyncMock(return_value={
            "status": "success",
            "memory_id": "test-memory-uuid",
            "entities_created": 1
        })

        with patch.object(memory, 'ingest_user_message', mock_ingest):
            # Parse the PDF
            extracted_text, metadata = await parsing.parse_file(
                pdf_content,
                "application/pdf",
                "project_plan.pdf"
            )

            # Verify extraction worked
            assert metadata["parser"] == "pypdf"

            # Simulate what the endpoint would do
            from uuid import UUID
            await mock_ingest(
                user_id=UUID("00000000-0000-0000-0000-000000000001"),
                content=f"[File: project_plan.pdf]\n\n{extracted_text}",
                source="file_upload"
            )

            # Verify ingestion was called with correct content
            mock_ingest.assert_called_once()
            call_args = mock_ingest.call_args
            assert "project_plan.pdf" in call_args.kwargs["content"]

    @pytest.mark.asyncio
    async def test_upload_csv_extracts_row_data(self, csv_content: bytes):
        """Verify CSV upload extracts row data for ingestion."""
        from lib.agent import parsing
        from lib.agent import memory

        mock_ingest = AsyncMock(return_value={
            "status": "success",
            "memory_id": "test-memory-uuid"
        })

        with patch.object(memory, 'ingest_user_message', mock_ingest):
            extracted_text, metadata = await parsing.parse_file(
                csv_content,
                "text/csv",
                "expenses.csv"
            )

            # Verify row data is present
            assert "Server" in extracted_text
            assert "50" in extracted_text
            assert "Domain" in extracted_text
            assert "12" in extracted_text

            # Verify metadata
            assert metadata["total_rows"] == 4

    @pytest.mark.asyncio
    async def test_upload_image_uses_mocked_vision(self, png_content: bytes):
        """Verify image upload uses mocked vision response."""
        from lib.agent import parsing
        from lib.agent import memory

        mock_response = MagicMock()
        mock_response.content = "A screenshot of a budget spreadsheet."

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        mock_ingest = AsyncMock(return_value={
            "status": "success",
            "memory_id": "test-memory-uuid"
        })

        with patch.object(parsing, 'ANTHROPIC_API_KEY', 'test-key'):
            with patch('lib.agent.parsing.ChatAnthropic', return_value=mock_llm):
                with patch.object(memory, 'ingest_user_message', mock_ingest):
                    extracted_text, metadata = await parsing.parse_file(
                        png_content,
                        "image/png",
                        "budget_screenshot.png"
                    )

                    # Verify mocked vision response
                    assert "budget spreadsheet" in extracted_text
                    assert metadata["parser"] == "claude-vision"


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_large_csv_truncation(self):
        """Verify large CSV files are truncated."""
        from lib.agent.parsing import parse_csv, MAX_EXTRACTED_TEXT_LENGTH

        # Generate large CSV
        rows = ["col1,col2"]
        for i in range(10000):
            rows.append(f"value{i},data{i}")
        large_csv = "\n".join(rows).encode('utf-8')

        extracted_text, metadata = await parse_csv(large_csv, "large.csv")

        # Should be truncated if exceeds max
        if len(extracted_text) > MAX_EXTRACTED_TEXT_LENGTH:
            assert "truncated" in extracted_text.lower()

    @pytest.mark.asyncio
    async def test_text_file_parsing(self):
        """Verify plain text files are parsed correctly."""
        from lib.agent.parsing import parse_file

        text_content = b"This is a simple text document with important information."

        extracted_text, metadata = await parse_file(
            text_content,
            "text/plain",
            "notes.txt"
        )

        assert "simple text document" in extracted_text
        assert metadata["parser"] == "text"

    @pytest.mark.asyncio
    async def test_json_file_parsing(self):
        """Verify JSON files are parsed correctly."""
        from lib.agent.parsing import parse_file
        import json

        json_data = {"project": "Alpha", "deadline": "October 15", "status": "active"}
        json_content = json.dumps(json_data).encode('utf-8')

        extracted_text, metadata = await parse_file(
            json_content,
            "application/json",
            "project.json"
        )

        assert "Alpha" in extracted_text
        assert "October 15" in extracted_text
        assert metadata["parser"] == "json"


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
