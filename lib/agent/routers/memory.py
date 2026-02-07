"""
Memory Router - Context engine and memory endpoints.

Endpoints:
- POST /memory/ingest - Manually trigger memory ingestion
- POST /memory/query - Debug endpoint for context retrieval
- POST /memory/upload - Upload files for knowledge ingestion
- GET  /memory/upload/supported-types - Get supported file types
"""

import logging
import os
from datetime import datetime
from uuid import UUID as UUIDType

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends, UploadFile, File, Form
from pydantic import BaseModel, Field

# Import from server.py
from lib.agent.server import verify_api_key, MemoryIngestRequest, MemoryQueryRequest
from lib.agent.memory import ingest_user_message
from lib.agent.retrieval import retrieve_context
from lib.agent.parsing import parse_file, is_supported_mime_type, SUPPORTED_MIME_TYPES
from supabase import create_client

logger = logging.getLogger(__name__)

# Create router with /memory prefix
router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/ingest")
async def memory_ingest_endpoint(
    request: MemoryIngestRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Manually trigger memory ingestion (for testing/dashboard).

    This endpoint allows explicit ingestion of content into the Context Engine.
    Normally ingestion happens automatically in the background after /invoke.

    Args:
        request: MemoryIngestRequest with user_id, content, and optional source

    Returns:
        {
            "success": bool,
            "message": str,
            "entities_created": int,
            "entities_updated": int,
            "memory_id": str (UUID)
        }
    """
    logger.info(f"Manual memory ingestion for user {request.user_id}")
    logger.info(
        f"Content length: {len(request.content)} chars, Source: {request.source}")

    try:
        result = await ingest_user_message(
            user_id=UUIDType(request.user_id),
            content=request.content,
            source=request.source or "manual"
        )

        logger.info(f"✓ Ingestion complete: {result.get('entities_created', 0)} entities created, "
                    f"{result.get('entities_updated', 0)} updated")

        return {
            "success": True,
            "message": "Memory ingestion completed successfully",
            "entities_created": result.get("entities_created", 0),
            "entities_updated": result.get("entities_updated", 0),
            "memory_id": str(result.get("memory_id")) if result.get("memory_id") else None
        }

    except Exception as e:
        logger.error(f"Memory ingestion failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Memory ingestion failed: {str(e)}"
        )


@router.post("/query")
async def memory_query_endpoint(
    request: MemoryQueryRequest,
    _: bool = Depends(verify_api_key)
):
    """
    Debug endpoint to test context retrieval.

    Returns the formatted context string that would be injected
    into the agent's prompt for a given query.

    Args:
        request: MemoryQueryRequest with user_id, query, and optional thresholds/limits

    Returns:
        {
            "success": bool,
            "context": str (formatted context),
            "context_length": int (characters),
            "metadata": {
                "memories_found": int,
                "entities_found": int,
                "query": str
            }
        }
    """
    logger.info(f"Memory query for user {request.user_id}")
    logger.info(f"Query: {request.query}")

    try:
        context = await retrieve_context(
            user_id=UUIDType(request.user_id),
            query=request.query,
            memory_threshold=request.memory_threshold or 0.7,
            memory_limit=request.memory_limit or 10,
            entity_limit=request.entity_limit or 20
        )

        # Parse the context to extract metadata
        memories_section = context.split("[RELATED ENTITIES]")[
            0] if "[RELATED ENTITIES]" in context else context
        entities_section = context.split("[RELATED ENTITIES]")[
            1] if "[RELATED ENTITIES]" in context else ""

        memories_count = memories_section.count(
            "Memory:") if "Memory:" in memories_section else 0
        entities_count = entities_section.count("•") if entities_section else 0

        logger.info(
            f"✓ Retrieved {memories_count} memories, {entities_count} entities")

        return {
            "success": True,
            "context": context,
            "context_length": len(context),
            "metadata": {
                "memories_found": memories_count,
                "entities_found": entities_count,
                "query": request.query
            }
        }

    except Exception as e:
        logger.error(f"Memory query failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Memory query failed: {str(e)}"
        )


@router.post("/upload")
async def memory_upload_endpoint(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: str = Form(...),
    source: str = Form(default="file_upload"),
    _: bool = Depends(verify_api_key)
):
    """
    Upload a file for knowledge ingestion.

    This endpoint accepts files (PDF, CSV, Excel, Images), parses them to
    extract text content, saves to Supabase Storage, and ingests the
    extracted text into the Context Engine as a background task.

    Supported file types:
    - PDF: Text extraction with pypdf
    - CSV: Row summaries with pandas
    - Excel (.xlsx, .xls): Sheet/row summaries with pandas
    - Images (JPEG, PNG, GIF, WebP): Claude vision description
    - Text/JSON: Direct content extraction

    Args:
        file: The uploaded file (multipart form data)
        user_id: User UUID (form field)
        source: Source identifier (form field, default: "file_upload")

    Returns:
        {
            "success": bool,
            "message": str,
            "file_name": str,
            "file_size": int,
            "mime_type": str,
            "storage_path": str (Supabase Storage path),
            "extracted_text_preview": str (first 500 chars),
            "ingestion_status": "queued" | "started"
        }
    """
    logger.info(f"📤 File upload received: {file.filename}")
    logger.info(f"  MIME type: {file.content_type}")
    logger.info(f"  User ID: {user_id}")

    try:
        # Validate MIME type
        mime_type = file.content_type or "application/octet-stream"
        if not is_supported_mime_type(mime_type):
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {mime_type}. "
                       f"Supported types: {list(SUPPORTED_MIME_TYPES.keys())}"
            )

        # Read file content
        file_content = await file.read()
        file_size = len(file_content)
        filename = file.filename or "unknown_file"

        logger.info(f"  File size: {file_size:,} bytes")

        # Validate file size (50MB max)
        max_size = 52428800  # 50MB
        if file_size > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large: {file_size:,} bytes. Maximum: {max_size:,} bytes"
            )

        # Parse file to extract text
        logger.info(f"🔄 Parsing file...")
        extracted_text, parse_metadata = await parse_file(
            file_content=file_content,
            mime_type=mime_type,
            filename=filename
        )

        logger.info(f"✓ Extracted {len(extracted_text):,} characters")

        # Save to Supabase Storage
        storage_path = None
        try:
            supabase_url = os.getenv("SUPABASE_URL")
            supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

            if supabase_url and supabase_key:
                supabase = create_client(supabase_url, supabase_key)

                # Generate unique storage path
                import uuid
                timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                unique_id = str(uuid.uuid4())[:8]
                safe_filename = "".join(c for c in filename if c.isalnum() or c in "._-")
                storage_path = f"{user_id}/{timestamp}_{unique_id}_{safe_filename}"

                # Upload to storage bucket
                storage_response = supabase.storage.from_("knowledge_base").upload(
                    path=storage_path,
                    file=file_content,
                    file_options={"content-type": mime_type}
                )

                logger.info(f"✓ Saved to storage: {storage_path}")

                # Track in knowledge_files table
                supabase.table("knowledge_files").insert({
                    "file_name": filename,
                    "file_path": storage_path,
                    "file_size": file_size,
                    "mime_type": mime_type,
                    "status": "processing",
                    "extracted_text": extracted_text,
                    "extracted_at": datetime.utcnow().isoformat(),
                    "metadata": parse_metadata
                }).execute()

                logger.info(f"✓ Tracked in knowledge_files table")

        except Exception as storage_error:
            logger.warning(f"Storage upload failed (continuing with ingestion): {storage_error}")
            storage_path = None

        # Queue memory ingestion as background task
        async def ingest_file_content():
            """Background task to ingest extracted file content."""
            try:
                result = await ingest_user_message(
                    user_id=UUIDType(user_id),
                    content=f"[File: {filename}]\n\n{extracted_text}",
                    source=source
                )
                logger.info(f"✓ File content ingested: {result.get('memory_id')}")

                # Update knowledge_files status if we have storage_path
                if storage_path:
                    try:
                        supabase_url = os.getenv("SUPABASE_URL")
                        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                        if supabase_url and supabase_key:
                            supabase = create_client(supabase_url, supabase_key)
                            supabase.table("knowledge_files").update({
                                "status": "completed",
                                "memory_id": str(result.get("memory_id")) if result.get("memory_id") else None
                            }).eq("file_path", storage_path).execute()
                    except Exception as update_error:
                        logger.warning(f"Failed to update knowledge_files status: {update_error}")

            except Exception as ingest_error:
                logger.error(f"File ingestion failed: {ingest_error}")
                # Update status to failed
                if storage_path:
                    try:
                        supabase_url = os.getenv("SUPABASE_URL")
                        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                        if supabase_url and supabase_key:
                            supabase = create_client(supabase_url, supabase_key)
                            supabase.table("knowledge_files").update({
                                "status": "failed",
                                "error_message": str(ingest_error)
                            }).eq("file_path", storage_path).execute()
                    except Exception:
                        pass

        background_tasks.add_task(ingest_file_content)
        logger.info("✓ Queued file content for background ingestion")

        return {
            "success": True,
            "message": "File uploaded and queued for ingestion",
            "file_name": filename,
            "file_size": file_size,
            "mime_type": mime_type,
            "storage_path": storage_path,
            "extracted_text_preview": extracted_text[:500] + "..." if len(extracted_text) > 500 else extracted_text,
            "extracted_text_length": len(extracted_text),
            "parse_metadata": parse_metadata,
            "ingestion_status": "queued"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"File upload failed: {str(e)}"
        )


@router.get("/upload/supported-types")
async def get_supported_upload_types():
    """
    Get list of supported file types for upload.

    Returns the MIME types and their categories for the file upload endpoint.
    """
    return {
        "success": True,
        "supported_types": SUPPORTED_MIME_TYPES,
        "max_file_size_bytes": 52428800,  # 50MB
        "max_file_size_human": "50 MB"
    }
