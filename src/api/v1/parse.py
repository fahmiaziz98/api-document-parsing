import time
import uuid

from fastapi import Depends, File, Form, HTTPException, UploadFile, status
from fastapi.routing import APIRouter
from loguru import logger

from src.models.response import ImageParseResult, JobSubmitted
from src.services.parser_service import _build_image_result
from src.utils.auth import verify_api_key
from src.utils.files import (
    IMAGE_EXTS,
    MAX_IMAGE_SIZE,
    MAX_PDF_SIZE,
    PDF_EXTS,
    _parse_metadata,
    _read_file,
    _validate_ext,
    _validate_file_size,
    _validate_page_range,
    optional_int,
)

router = APIRouter()


@router.post(
    "/parse/pdf",
    response_model=JobSubmitted,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)],
)
async def parse_pdf_endpoint(
    file: UploadFile = File(...),  # noqa: B008
    metadata: str = Form("{}"),
    start_page: str | None = Form(None),
    end_page: str | None = Form(None),
    enable_rotate: bool = Form(False),
    enable_crop: bool = Form(False),
):
    """
    Submit a PDF file to the Modal parsing queue.

    Args:
        file (UploadFile): PDF file to parse
        metadata (str): JSON string of arbitrary key-value metadata
            e.g. '{"company": "Acme", "year": 2024}'
        start_page (str | None): Start page (1-indexed)
        end_page (str | None): End page (1-indexed)
        enable_rotate (bool): Enable auto-rotation
        enable_crop (bool): Enable content cropping

    Returns:
        JobSubmitted: Job ID and polling instructions

    Raises:
        HTTPException: If file validation or metadata is invalid
    """
    metadata_dict = _parse_metadata(metadata)
    _start = optional_int(start_page)
    _end = optional_int(end_page)

    _validate_ext(file.filename, PDF_EXTS)
    file_bytes = await _read_file(file)
    _validate_file_size(file_bytes, file.filename, MAX_PDF_SIZE)
    _validate_page_range(_start, _end)

    logger.info(
        f"PDF parse request: {file.filename} ({len(file_bytes) / (1024 * 1024):.1f}MB)",
        extra={"filename": file.filename, "file_size_bytes": len(file_bytes)},
    )

    from src.modal_app import DocumentParser

    call = await DocumentParser().parse_pdf.spawn.aio(
        file_bytes,
        file.filename,
        metadata_dict,
        _start,
        _end,
        enable_rotate,
        enable_crop,
    )
    return JobSubmitted(
        job_id=call.object_id,
        message=f"PDF parsing started. Poll GET /v1/jobs/{call.object_id}/status",
    )


@router.post(
    "/parse/image",
    response_model=ImageParseResult,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
async def parse_image_endpoint(
    file: UploadFile = File(...),  # noqa: B008
    metadata: str = Form("{}"),
    enable_rotate: bool = Form(False),
    enable_crop: bool = Form(False),
):
    """
    Parse an image file directly and return results immediately.

    Args:
        file (UploadFile): Image file to parse
        metadata (str): JSON string of arbitrary key-value metadata
            e.g. '{"company": "Acme", "year": 2024}'
        enable_rotate (bool): Enable auto-rotation
        enable_crop (bool): Enable content cropping

    Returns:
        ImageParseResult: Flat content, table markdown, and metadata

    Raises:
        HTTPException: If file validation or parsing fails
    """
    metadata_dict = _parse_metadata(metadata)
    _validate_ext(file.filename, IMAGE_EXTS)
    file_bytes = await _read_file(file)
    _validate_file_size(file_bytes, file.filename, MAX_IMAGE_SIZE)

    logger.info(
        f"Image parse request: {file.filename} ({len(file_bytes) / (1024 * 1024):.1f}MB)",
        extra={"filename": file.filename, "file_size_bytes": len(file_bytes)},
    )

    from src.modal_app import DocumentParser

    try:
        t_start = time.monotonic()
        result = await DocumentParser().parse_image.remote.aio(
            file_bytes,
            file.filename,
            metadata_dict,
            enable_rotate,
            enable_crop,
        )
        duration = time.monotonic() - t_start

        from src.models.enums import JobStatusEnum

        status_val = result.get("status", JobStatusEnum.DONE)
        if status_val == JobStatusEnum.ERROR:
            error_msg = result.get("error", "Unknown parsing error")
            logger.error(f"Image parsing failed in Modal: {error_msg}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_msg)

        job_id = str(uuid.uuid4())
        return _build_image_result(
            job_id=job_id,
            elements=result.get("elements", []),
            filename=file.filename,
            duration_seconds=duration,
            user_metadata=metadata_dict,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Image parsing failed", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e
