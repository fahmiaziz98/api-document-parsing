import json
import os

import modal
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from src.modal_app import results_volume
from src.models.response import JobStatusEnum, JobSubmitted
from src.utils.auth import verify_api_key

web_app = FastAPI(
    title="Document Parsing",
    version="0.1.0",
    docs_url="/docs",
)

PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tiff", ".bmp"}


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


@web_app.get("/health")
async def health():
    """
    Health check endpoint

    Returns:
        JSONResponse: JSON response with status
    """
    return {"status": "ok"}


@web_app.post(
    "/parse/pdf",
    response_model=JobSubmitted,
    status_code=202,
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
    Checks authorization and validates file extensions before dispatching.

    Args:
        file (UploadFile): File to parse
        metadata (str): JSON string of arbitrary key-value metadata
            e.g. '{"company": "Acme", "year": 2024, "label": "annual-report"}'
        start_page (str | None): Start page
        end_page (str | None): End page
        enable_rotate (bool): Enable rotation
        enable_crop (bool): Enable crop

    Returns:
        JSONResponse: JSON response with job status

    Raises:
        HTTPException: If the file extension is not allowed or metadata is invalid JSON
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
        message=f"PDF parsing started. Poll GET /status/{call.object_id}",
    )


@web_app.post(
    "/parse/image",
    response_model=JobSubmitted,
    status_code=202,
    dependencies=[Depends(verify_api_key)],
)
async def parse_image_endpoint(
    file: UploadFile = File(...),  # noqa: B008
    metadata: str = Form("{}"),
    enable_rotate: bool = Form(False),
    enable_crop: bool = Form(False),
):
    """
    Submit an Image file to the Modal parsing queue.
    Checks authorization and validates file extensions before dispatching.

    Args:
        file (UploadFile): File to parse
        metadata (str): JSON string of arbitrary key-value metadata
            e.g. '{"company": "Acme", "year": 2024, "label": "invoice"}'
        enable_rotate (bool): Enable rotation
        enable_crop (bool): Enable crop

    Returns:
        JSONResponse: JSON response with job status

    Raises:
        HTTPException: If the file extension is not allowed or metadata is invalid JSON
    """
    metadata_dict = _parse_metadata(metadata)
    _validate_ext(file.filename, IMAGE_EXTS)
    file_bytes = await _read_file(file)

    from src.modal_app import DocumentParser

    call = await DocumentParser().parse_image.spawn.aio(
        file_bytes,
        file.filename,
        metadata_dict,
        enable_rotate,
        enable_crop,
    )
    return JobSubmitted(
        job_id=call.object_id,
        message=f"Image parsing started. Poll GET /status/{call.object_id}",
    )


@web_app.get("/status/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_status(job_id: str):
    """
    Poll the status of a submitted Modal job.
    Returns processing, done, expired, or error depending on the underlying Modal run state.

    Args:
        job_id (str): Job ID

    Returns:
        JSONResponse: JSON response with job status

    Raises:
        TimeoutError: If the job is still running
        HTTPException: If the job is not found or expired
        Exception: If the job fails
    """
    try:
        result = await _get_call_result(job_id, timeout=0)

        status_val = result.get("status", JobStatusEnum.DONE)
        return JSONResponse(
            status_code=200 if status_val == JobStatusEnum.DONE else 500,
            content={
                "job_id": job_id,
                "status": status_val,
                "element_count": result.get("element_count"),
                "output_path": result.get("output_path"),
                "error": result.get("error"),
            },
        )
    except TimeoutError:
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.PROCESSING,
            },
        )
    except modal.exception.NotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.EXPIRED,
                "error": "Job not found or expired (>7 days)",
            },
        )
    except Exception as e:
        logger.error(f"Status check failed for job {job_id}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.ERROR,
                "error": str(e),
            },
        )


@web_app.get("/result/{job_id}", dependencies=[Depends(verify_api_key)])
async def get_result(job_id: str):
    """
    Fetch the full resulting JSON elements for a finalized Modal job.
    Requires the job to be strictly done.

    Args:
        job_id (str): Job ID

    Returns:
        JSONResponse: JSON response with job status and elements

    Raises:
        TimeoutError: If the job is still running
        HTTPException: If the job is not found or expired
        Exception: If the job fails
    """
    try:
        result = await _get_call_result(job_id, timeout=0)

        status_val = result.get("status", JobStatusEnum.DONE)
        if status_val == JobStatusEnum.ERROR:
            return JSONResponse(
                status_code=500,
                content={
                    "job_id": job_id,
                    "status": JobStatusEnum.ERROR,
                    "error": result.get("error"),
                },
            )

        return JSONResponse(
            status_code=200,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.DONE,
                "element_count": result["element_count"],
                "elements": result["elements"],
            },
        )
    except TimeoutError:
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.PROCESSING,
                "message": "Job still running, try again later",
            },
        )
    except Exception as e:
        logger.error(f"Result fetch failed for job {job_id}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@web_app.get("/download/{job_id}", dependencies=[Depends(verify_api_key)])
async def download_result(job_id: str):
    """
    Download the generated JSONL file for a completed parsing job.

    Retrieves the output_path recorded by the Modal worker and streams
    the file from the mounted results volume back to the caller.

    Args:
        job_id (str): Job ID

    Returns:
        FileResponse: The JSONL file as a downloadable attachment

    Raises:
        HTTPException: 202 if still processing; 404 if file not found; 500 on error
    """
    try:
        result = await _get_call_result(job_id, timeout=0)
    except TimeoutError:
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.PROCESSING,
                "message": "Job still running, try again later",
            },
        )
    except modal.exception.NotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.EXPIRED,
                "error": "Job not found or expired (>7 days)",
            },
        )
    except Exception as e:
        logger.error(f"Download fetch failed for job {job_id}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e

    status_val = result.get("status", JobStatusEnum.DONE)
    if status_val == JobStatusEnum.ERROR:
        return JSONResponse(
            status_code=500,
            content={
                "job_id": job_id,
                "status": JobStatusEnum.ERROR,
                "error": result.get("error"),
            },
        )

    output_filename = result.get("output_path")
    if not output_filename:
        raise HTTPException(status_code=404, detail="No output file recorded for this job.")

    # Reload the volume so this container sees files committed by the worker.
    await results_volume.reload.aio()

    file_path = f"/results/{output_filename}"
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=404,
            detail=f"Output file '{output_filename}' not found on volume.",
        )

    return FileResponse(
        path=file_path,
        media_type="application/x-ndjson",
        filename=output_filename,
    )


def _parse_metadata(metadata_str: str) -> dict:
    """
    Parse the metadata JSON string sent as a form field.

    Args:
        metadata_str (str): Raw JSON string from the form field

    Returns:
        dict: Parsed metadata dictionary

    Raises:
        HTTPException: If the value is not valid JSON or not a JSON object
    """
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
    """
    Validate file extension

    Args:
        filename (str): Nama file
        allowed (set[str]): Set of allowed extensions

    Raises:
        HTTPException: If the file extension is not allowed
    """
    suffix = "." + (filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file: {suffix}. Allowed: {allowed}",
        )


def _validate_page_range(start: int | None, end: int | None) -> None:
    """
    Validate page range

    Args:
        start (int | None): Start page
        end (int | None): End page

    Raises:
        HTTPException: If the page range is invalid
    """
    if start and end and start > end:
        raise HTTPException(
            status_code=422,
            detail="start_page must be <= end_page",
        )


def optional_int(value: str | None = None) -> int | None:
    """
    Parse form int — return None if null

    Args:
        value (str | None): Value to parse

    Returns:
        int | None: Parsed integer value

    Raises:
        HTTPException: If the value is invalid
    """
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"Invalid integer value: '{value}'") from None


async def _read_file(file: UploadFile) -> bytes:
    """
    Read file bytes

    Args:
        file (UploadFile): File to read

    Returns:
        bytes: File bytes

    Raises:
        HTTPException: If the file cannot be read
    """
    try:
        return await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}") from e
