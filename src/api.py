import json
import os
import time
import uuid
from collections import defaultdict
from pathlib import Path

import modal
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, Response
from loguru import logger

from src.modal_app import results_volume
from src.models.response import (
    ImageMetadata,
    ImageParseResult,
    JobStatusEnum,
    JobSubmitted,
    PageContent,
    PageTableMarkdown,
    PdfMetadata,
    PdfParseResult,
)
from src.utils.auth import verify_api_key

web_app = FastAPI(
    title="Document Parsing",
    version="0.1.5",
    docs_url="/docs",
)

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


async def _get_call_result(job_id: str, timeout: int = 0):
    """
    Get the result of a Modal job

    Args:
        job_id (str): Job ID
        timeout (int): Timeout in seconds

    Returns:
        dict: Job result

    Raises:
        TimeoutError: If the job is still running
        HTTPException: If the job is not found or expired
        Exception: If the job fails
    """
    fc = modal.FunctionCall.from_id(job_id)
    return await fc.get.aio(timeout=timeout)


def _build_image_result(
    job_id: str,
    elements: list[dict],
    filename: str,
    duration_seconds: float,
    user_metadata: dict,
) -> ImageParseResult:
    """
    Transform raw element list from exporter into a flat ImageParseResult.

    Args:
        job_id: UUID for this parse job.
        elements: Raw element dicts from export_raw_elements.
        filename: Original uploaded filename.
        duration_seconds: Parsing duration in seconds.
        user_metadata: User-supplied metadata (company, year, etc).

    Returns:
        ImageParseResult: Flat response model.
    """
    full_content = next(
        (el.get("full_content") for el in elements if el.get("full_content")),
        None,
    )
    table_markdown = next(
        (el.get("table_markdown") for el in elements if el.get("table_markdown")),
        None,
    )
    ext = Path(filename).suffix.lower()

    return ImageParseResult(
        job_id=job_id,
        status=JobStatusEnum.DONE,
        page_count=1,
        metadata=ImageMetadata(
            filename=filename,
            extension=ext,
            duration_seconds=round(duration_seconds, 2),
            **user_metadata,
        ),
        full_content=full_content,
        table_markdown=table_markdown,
    )


def _build_pdf_result(
    job_id: str,
    elements: list[dict],
    filename: str,
    duration_seconds: float,
    user_metadata: dict,
    total_pages: int,
    start_page: int | None,
    end_page: int | None,
) -> PdfParseResult:
    """
    Transform raw element list from exporter into a per-page PdfParseResult.

    Args:
        job_id: UUID for this parse job.
        elements: Raw element dicts from export_raw_elements.
        filename: Original uploaded filename.
        duration_seconds: Parsing duration in seconds.
        user_metadata: User-supplied metadata (company, year, etc).
        total_pages: Actual total pages from Modal worker.
        start_page: User-requested start page (None = from beginning).
        end_page: User-requested end page (None = to end).

    Returns:
        PdfParseResult: Per-page response model.
    """
    seen_pages: set[int] = set()
    full_content_pages: list[PageContent] = []
    tables_by_page: defaultdict[int, list[str]] = defaultdict(list)

    for el in elements:
        page = el.get("metadata", {}).get("page") or 0
        if not page:
            continue

        fc = el.get("full_content")
        if fc and page not in seen_pages:
            full_content_pages.append(PageContent(page=page, content=fc))
            seen_pages.add(page)

        tm = el.get("table_markdown")
        if tm:
            tables_by_page[page].append(tm)

    full_content_pages.sort(key=lambda x: x.page)

    table_markdown_pages: list[PageTableMarkdown] = [
        PageTableMarkdown(page=page, content="\n\n".join(tables))
        for page, tables in sorted(tables_by_page.items())
    ]

    page_count = total_pages or (max(seen_pages) if seen_pages else 0)
    ext = Path(filename).suffix.lower()

    return PdfParseResult(
        job_id=job_id,
        status=JobStatusEnum.DONE,
        page_count=page_count,
        metadata=PdfMetadata(
            filename=filename,
            extension=ext,
            duration_seconds=round(duration_seconds, 2),
            page_range={
                "start": start_page or 1,
                "end": end_page or total_pages,
            },
            **user_metadata,
        ),
        full_content=full_content_pages,
        table_markdown=table_markdown_pages,
    )


@web_app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}


@web_app.post(
    "/parse/pdf",
    response_model=JobSubmitted,
    status_code=status.HTTP_200_OK,
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
    _validate_page_range(_start, _end)
    file_bytes = await _read_file(file)

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
        message=f"PDF parsing started. Poll GET /result/{call.object_id}",
    )


@web_app.post(
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


@web_app.get("/status/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_status(job_id: str):
    """
    Poll the status of a submitted PDF job.
    Lightweight — returns job_id, status, output_path, error only.

    Args:
        job_id (str): Job ID from /parse/pdf

    Returns:
        JSONResponse: Lightweight status response
    """
    try:
        result = await _get_call_result(job_id, timeout=0)

        status_val = result.get("status", JobStatusEnum.DONE)
        return JSONResponse(
            status_code=status.HTTP_200_OK
            if status_val == JobStatusEnum.DONE
            else status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "job_id": job_id,
                "status": status_val,
                "output_path": result.get("output_path"),
                "error": result.get("error"),
            },
        )
    except TimeoutError:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={"job_id": job_id, "status": JobStatusEnum.PROCESSING},
        )
    except modal.exception.NotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.EXPIRED,
                "error": "Job not found or expired (>7 days)",
            },
        )
    except Exception as e:
        logger.error(f"Status check failed for job {job_id}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"job_id": job_id, "status": JobStatusEnum.ERROR, "error": str(e)},
        )


@web_app.get(
    "/result/{job_id}",
    response_model=PdfParseResult,
    dependencies=[Depends(verify_api_key)],
)
async def get_result(job_id: str):
    """
    Fetch the full parsed result for a finalized PDF job.

    Returns PdfParseResult with per-page full_content, table_markdown, and metadata.
    Still processing → 202. Error → 500. Not found → 404.

    Args:
        job_id (str): Job ID from /parse/pdf

    Returns:
        PdfParseResult: Per-page content, tables, and metadata
    """
    try:
        result = await _get_call_result(job_id, timeout=0)
    except TimeoutError:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.PROCESSING,
                "message": "Job still running, try again later",
            },
        )
    except modal.exception.NotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.EXPIRED,
                "error": "Job not found or expired (>7 days)",
            },
        )
    except Exception as e:
        logger.error(f"Result fetch failed for job {job_id}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    status_val = result.get("status", JobStatusEnum.DONE)
    if status_val == JobStatusEnum.ERROR:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"job_id": job_id, "status": JobStatusEnum.ERROR, "error": result.get("error")},
        )

    return _build_pdf_result(
        job_id=job_id,
        elements=result.get("elements", []),
        filename=result.get("filename", ""),
        duration_seconds=result.get("duration_seconds", 0.0),
        user_metadata=result.get("user_metadata", {}),
        total_pages=result.get("total_pages", 0),
        start_page=result.get("start_page"),
        end_page=result.get("end_page"),
    )


@web_app.get(
    "/download/{job_id}",
    response_model=PdfParseResult,
    dependencies=[Depends(verify_api_key)],
)
async def download_result(job_id: str):
    """
    Download the parsed result for a completed PDF job as a JSON file.

    Reads the JSONL from Modal Volume, transforms to PdfParseResult,
    and returns as a downloadable .json file named after the original PDF.

    Args:
        job_id (str): Job ID from /parse/pdf

    Returns:
        Response: Downloadable JSON file with PdfParseResult content
    """
    try:
        result = await _get_call_result(job_id, timeout=0)
    except TimeoutError:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.PROCESSING,
                "message": "Job still running, try again later",
            },
        )
    except modal.exception.NotFoundError:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.EXPIRED,
                "error": "Job not found or expired (>7 days)",
            },
        )
    except Exception as e:
        logger.error(f"Download fetch failed for job {job_id}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)) from e

    status_val = result.get("status", JobStatusEnum.DONE)
    if status_val == JobStatusEnum.ERROR:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"job_id": job_id, "status": JobStatusEnum.ERROR, "error": result.get("error")},
        )

    output_filename = result.get("output_path")
    if not output_filename:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No output file recorded for this job."
        )

    await results_volume.reload.aio()

    file_path = f"/results/{output_filename}"
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Output file '{output_filename}' not found on volume.",
        )

    # Read JSONL and transform to PdfParseResult
    elements = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                elements.append(json.loads(line))

    pdf_result = _build_pdf_result(
        job_id=job_id,
        elements=elements,
        filename=result.get("filename", ""),
        duration_seconds=result.get("duration_seconds", 0.0),
        user_metadata=result.get("user_metadata", {}),
        total_pages=result.get("total_pages", 0),
        start_page=result.get("start_page"),
        end_page=result.get("end_page"),
    )

    # Strip timestamp suffix from JSONL filename to get original name
    original_name = Path(output_filename).stem.rsplit("_", 2)[0]
    return Response(
        content=pdf_result.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={original_name}.json"},
    )


def _parse_metadata(metadata_str: str) -> dict:
    try:
        parsed = json.loads(metadata_str)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"metadata must be a valid JSON string: {e}",
        ) from e
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="metadata must be a JSON object (key-value pairs)",
        )
    return parsed


def _validate_ext(filename: str, allowed: set[str]) -> None:
    suffix = "." + (filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file: {suffix}. Allowed: {allowed}",
        )


def _validate_page_range(start: int | None, end: int | None) -> None:
    if start and end and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_page must be <= end_page",
        )


def optional_int(value: str | None = None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid integer value: '{value}'",
        ) from None


async def _read_file(file: UploadFile) -> bytes:

    try:
        return await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to read file: {e}"
        ) from e
