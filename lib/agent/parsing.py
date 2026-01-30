"""
File Parsing Module - Context Engine File Ingestion
====================================================

This module handles parsing various file types for the Context Engine.
Converts binary files (PDF, CSV, Excel, Images) into text for ingestion.

Supported Formats:
- PDF: Extracts text using pypdf
- CSV: Converts rows into readable summaries using pandas
- Excel: Converts sheets/rows into readable summaries using pandas
- Images: Uses Claude 3.5 Sonnet vision to describe image content
- Plain Text: Direct passthrough

Owner: @backend-architect-sabine
"""

import base64
import io
import logging
import os
from typing import Optional, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Vision model for image processing
VISION_MODEL = "claude-sonnet-4-20250514"

# Maximum text length to extract (prevent memory issues with huge files)
MAX_EXTRACTED_TEXT_LENGTH = 100_000  # ~100KB of text

# =============================================================================
# MIME Type Detection
# =============================================================================

SUPPORTED_MIME_TYPES = {
    # PDF
    "application/pdf": "pdf",
    # CSV
    "text/csv": "csv",
    # Excel
    "application/vnd.ms-excel": "excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "excel",
    # Images
    "image/jpeg": "image",
    "image/png": "image",
    "image/gif": "image",
    "image/webp": "image",
    # Plain text
    "text/plain": "text",
    # JSON
    "application/json": "json",
}


def get_file_type(mime_type: str) -> Optional[str]:
    """
    Get the file type category from MIME type.

    Args:
        mime_type: MIME type string (e.g., "application/pdf")

    Returns:
        File type category ("pdf", "csv", "excel", "image", "text", "json")
        or None if unsupported
    """
    return SUPPORTED_MIME_TYPES.get(mime_type.lower())


def is_supported_mime_type(mime_type: str) -> bool:
    """Check if the MIME type is supported for parsing."""
    return mime_type.lower() in SUPPORTED_MIME_TYPES


# =============================================================================
# PDF Parser
# =============================================================================

async def parse_pdf(file_content: bytes, filename: str = "document.pdf") -> Tuple[str, dict]:
    """
    Extract text from a PDF file.

    Args:
        file_content: Raw PDF bytes
        filename: Original filename for logging

    Returns:
        Tuple of (extracted_text, metadata_dict)
    """
    try:
        from pypdf import PdfReader

        logger.info(f"📄 Parsing PDF: {filename}")

        # Create PDF reader from bytes
        pdf_stream = io.BytesIO(file_content)
        reader = PdfReader(pdf_stream)

        # Extract text from all pages
        text_parts = []
        total_pages = len(reader.pages)

        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

        extracted_text = "\n\n".join(text_parts)

        # Truncate if too long
        if len(extracted_text) > MAX_EXTRACTED_TEXT_LENGTH:
            logger.warning(
                f"PDF text truncated from {len(extracted_text)} to {MAX_EXTRACTED_TEXT_LENGTH} chars")
            extracted_text = extracted_text[:MAX_EXTRACTED_TEXT_LENGTH] + \
                "\n\n[... Text truncated due to length ...]"

        metadata = {
            "parser": "pypdf",
            "total_pages": total_pages,
            "characters_extracted": len(extracted_text),
            "filename": filename
        }

        logger.info(
            f"✓ Extracted {len(extracted_text)} chars from {total_pages} pages")
        return extracted_text, metadata

    except Exception as e:
        logger.error(f"Failed to parse PDF {filename}: {e}", exc_info=True)
        raise ValueError(f"PDF parsing failed: {str(e)}")


# =============================================================================
# CSV/Excel Parser
# =============================================================================

async def parse_csv(file_content: bytes, filename: str = "data.csv") -> Tuple[str, dict]:
    """
    Convert CSV data into a readable text summary.

    Args:
        file_content: Raw CSV bytes
        filename: Original filename for logging

    Returns:
        Tuple of (extracted_text, metadata_dict)
    """
    try:
        import pandas as pd

        logger.info(f"📊 Parsing CSV: {filename}")

        # Read CSV from bytes
        csv_stream = io.BytesIO(file_content)
        df = pd.read_csv(csv_stream)

        # Generate summary
        text_parts = []

        # Header info
        text_parts.append(f"CSV Data Summary: {filename}")
        text_parts.append(f"Columns: {', '.join(df.columns.tolist())}")
        text_parts.append(f"Total Rows: {len(df)}")
        text_parts.append("")

        # Column statistics
        text_parts.append("Column Details:")
        for col in df.columns:
            dtype = str(df[col].dtype)
            non_null = df[col].count()
            unique = df[col].nunique()
            text_parts.append(f"  - {col}: {dtype}, {non_null} non-null, {unique} unique values")

        text_parts.append("")

        # Sample rows (first 20)
        text_parts.append("Sample Data (first 20 rows):")
        sample_df = df.head(20)
        for idx, row in sample_df.iterrows():
            row_text = " | ".join([f"{col}: {val}" for col, val in row.items()])
            text_parts.append(f"  Row {idx + 1}: {row_text}")

        # If more rows, add note
        if len(df) > 20:
            text_parts.append(f"  ... and {len(df) - 20} more rows")

        extracted_text = "\n".join(text_parts)

        # Truncate if too long
        if len(extracted_text) > MAX_EXTRACTED_TEXT_LENGTH:
            extracted_text = extracted_text[:MAX_EXTRACTED_TEXT_LENGTH] + \
                "\n\n[... Text truncated due to length ...]"

        metadata = {
            "parser": "pandas",
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "columns": df.columns.tolist(),
            "filename": filename
        }

        logger.info(
            f"✓ Parsed CSV with {len(df)} rows, {len(df.columns)} columns")
        return extracted_text, metadata

    except Exception as e:
        logger.error(f"Failed to parse CSV {filename}: {e}", exc_info=True)
        raise ValueError(f"CSV parsing failed: {str(e)}")


async def parse_excel(file_content: bytes, filename: str = "data.xlsx") -> Tuple[str, dict]:
    """
    Convert Excel data into a readable text summary.

    Args:
        file_content: Raw Excel bytes
        filename: Original filename for logging

    Returns:
        Tuple of (extracted_text, metadata_dict)
    """
    try:
        import pandas as pd

        logger.info(f"📊 Parsing Excel: {filename}")

        # Read Excel from bytes
        excel_stream = io.BytesIO(file_content)
        excel_file = pd.ExcelFile(excel_stream, engine='openpyxl')

        text_parts = []
        text_parts.append(f"Excel Workbook Summary: {filename}")
        text_parts.append(f"Sheets: {', '.join(excel_file.sheet_names)}")
        text_parts.append("")

        total_rows = 0
        all_columns = []

        # Process each sheet
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            total_rows += len(df)
            all_columns.extend(df.columns.tolist())

            text_parts.append(f"=== Sheet: {sheet_name} ===")
            text_parts.append(f"Columns: {', '.join(df.columns.tolist())}")
            text_parts.append(f"Rows: {len(df)}")
            text_parts.append("")

            # Sample rows (first 10 per sheet)
            text_parts.append("Sample Data:")
            sample_df = df.head(10)
            for idx, row in sample_df.iterrows():
                row_text = " | ".join([f"{col}: {val}" for col, val in row.items()])
                text_parts.append(f"  Row {idx + 1}: {row_text}")

            if len(df) > 10:
                text_parts.append(f"  ... and {len(df) - 10} more rows")

            text_parts.append("")

        extracted_text = "\n".join(text_parts)

        # Truncate if too long
        if len(extracted_text) > MAX_EXTRACTED_TEXT_LENGTH:
            extracted_text = extracted_text[:MAX_EXTRACTED_TEXT_LENGTH] + \
                "\n\n[... Text truncated due to length ...]"

        metadata = {
            "parser": "pandas+openpyxl",
            "total_sheets": len(excel_file.sheet_names),
            "sheet_names": excel_file.sheet_names,
            "total_rows": total_rows,
            "filename": filename
        }

        logger.info(
            f"✓ Parsed Excel with {len(excel_file.sheet_names)} sheets, {total_rows} total rows")
        return extracted_text, metadata

    except Exception as e:
        logger.error(f"Failed to parse Excel {filename}: {e}", exc_info=True)
        raise ValueError(f"Excel parsing failed: {str(e)}")


# =============================================================================
# Image Parser (Claude Vision)
# =============================================================================

async def parse_image(file_content: bytes, filename: str = "image.jpg", mime_type: str = "image/jpeg") -> Tuple[str, dict]:
    """
    Generate a detailed description of an image using Claude 3.5 Sonnet vision.

    Args:
        file_content: Raw image bytes
        filename: Original filename for logging
        mime_type: MIME type of the image

    Returns:
        Tuple of (extracted_text, metadata_dict)
    """
    try:
        logger.info(f"🖼️ Parsing image with Claude Vision: {filename}")

        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set for image parsing")

        # Encode image as base64
        image_base64 = base64.b64encode(file_content).decode("utf-8")

        # Map MIME types for Claude
        media_type_map = {
            "image/jpeg": "image/jpeg",
            "image/png": "image/png",
            "image/gif": "image/gif",
            "image/webp": "image/webp",
        }
        media_type = media_type_map.get(mime_type.lower(), "image/jpeg")

        # Create Claude client
        llm = ChatAnthropic(
            model=VISION_MODEL,
            temperature=0.0,
            anthropic_api_key=ANTHROPIC_API_KEY,
        )

        # Create vision message
        message = HumanMessage(
            content=[
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_base64,
                    },
                },
                {
                    "type": "text",
                    "text": """Analyze this image and provide a detailed description for knowledge indexing.
Include:
1. Main subject/content of the image
2. Key visual elements (objects, people, text, colors, composition)
3. Any text visible in the image (OCR)
4. Context or setting
5. Notable details that would help someone search for this image later

Format as a clear, searchable description."""
                },
            ],
        )

        # Get description from Claude
        response = await llm.ainvoke([message])
        extracted_text = response.content

        # Add header
        extracted_text = f"Image Description: {filename}\n\n{extracted_text}"

        metadata = {
            "parser": "claude-vision",
            "model": VISION_MODEL,
            "mime_type": mime_type,
            "file_size_bytes": len(file_content),
            "filename": filename
        }

        logger.info(
            f"✓ Generated {len(extracted_text)} char description for image")
        return extracted_text, metadata

    except Exception as e:
        logger.error(f"Failed to parse image {filename}: {e}", exc_info=True)
        raise ValueError(f"Image parsing failed: {str(e)}")


# =============================================================================
# Text/JSON Parser
# =============================================================================

async def parse_text(file_content: bytes, filename: str = "document.txt") -> Tuple[str, dict]:
    """
    Extract text from a plain text file.

    Args:
        file_content: Raw text bytes
        filename: Original filename for logging

    Returns:
        Tuple of (extracted_text, metadata_dict)
    """
    try:
        logger.info(f"📝 Parsing text file: {filename}")

        # Try UTF-8 first, then fallback to latin-1
        try:
            extracted_text = file_content.decode("utf-8")
        except UnicodeDecodeError:
            extracted_text = file_content.decode("latin-1")

        # Truncate if too long
        original_length = len(extracted_text)
        if len(extracted_text) > MAX_EXTRACTED_TEXT_LENGTH:
            extracted_text = extracted_text[:MAX_EXTRACTED_TEXT_LENGTH] + \
                "\n\n[... Text truncated due to length ...]"

        metadata = {
            "parser": "text",
            "original_length": original_length,
            "characters_extracted": len(extracted_text),
            "filename": filename
        }

        logger.info(f"✓ Extracted {len(extracted_text)} chars from text file")
        return extracted_text, metadata

    except Exception as e:
        logger.error(f"Failed to parse text {filename}: {e}", exc_info=True)
        raise ValueError(f"Text parsing failed: {str(e)}")


async def parse_json(file_content: bytes, filename: str = "data.json") -> Tuple[str, dict]:
    """
    Convert JSON data into a readable text summary.

    Args:
        file_content: Raw JSON bytes
        filename: Original filename for logging

    Returns:
        Tuple of (extracted_text, metadata_dict)
    """
    try:
        import json

        logger.info(f"📋 Parsing JSON: {filename}")

        # Parse JSON
        try:
            text_content = file_content.decode("utf-8")
        except UnicodeDecodeError:
            text_content = file_content.decode("latin-1")

        data = json.loads(text_content)

        # Pretty print for readability
        extracted_text = f"JSON Data: {filename}\n\n"
        extracted_text += json.dumps(data, indent=2, ensure_ascii=False)

        # Truncate if too long
        if len(extracted_text) > MAX_EXTRACTED_TEXT_LENGTH:
            extracted_text = extracted_text[:MAX_EXTRACTED_TEXT_LENGTH] + \
                "\n\n[... JSON truncated due to length ...]"

        # Determine structure
        if isinstance(data, dict):
            structure = f"Object with {len(data)} keys"
            top_keys = list(data.keys())[:10]
        elif isinstance(data, list):
            structure = f"Array with {len(data)} items"
            top_keys = []
        else:
            structure = f"Primitive: {type(data).__name__}"
            top_keys = []

        metadata = {
            "parser": "json",
            "structure": structure,
            "top_level_keys": top_keys,
            "characters_extracted": len(extracted_text),
            "filename": filename
        }

        logger.info(f"✓ Parsed JSON ({structure})")
        return extracted_text, metadata

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filename}: {e}")
        raise ValueError(f"Invalid JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to parse JSON {filename}: {e}", exc_info=True)
        raise ValueError(f"JSON parsing failed: {str(e)}")


# =============================================================================
# Main Parser Dispatcher
# =============================================================================

async def parse_file(
    file_content: bytes,
    mime_type: str,
    filename: str = "unknown"
) -> Tuple[str, dict]:
    """
    Parse a file and extract text content.

    This is the main entry point for file parsing. It dispatches to the
    appropriate parser based on MIME type.

    Args:
        file_content: Raw file bytes
        mime_type: MIME type of the file
        filename: Original filename for logging/metadata

    Returns:
        Tuple of (extracted_text, metadata_dict)

    Raises:
        ValueError: If MIME type is not supported or parsing fails
    """
    file_type = get_file_type(mime_type)

    if file_type is None:
        raise ValueError(
            f"Unsupported MIME type: {mime_type}. "
            f"Supported types: {list(SUPPORTED_MIME_TYPES.keys())}"
        )

    logger.info(f"🔄 Dispatching parser for {file_type}: {filename}")

    # Dispatch to appropriate parser
    parsers = {
        "pdf": parse_pdf,
        "csv": parse_csv,
        "excel": parse_excel,
        "image": lambda content, name: parse_image(content, name, mime_type),
        "text": parse_text,
        "json": parse_json,
    }

    parser_func = parsers.get(file_type)
    if parser_func is None:
        raise ValueError(f"No parser available for file type: {file_type}")

    return await parser_func(file_content, filename)
