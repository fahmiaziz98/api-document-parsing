import modal
from fastapi import Depends, HTTPException, status
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRouter
from loguru import logger

from src.models.response import PdfParseResult
from src.services.parser_service import (
    _build_pdf_result,
    _get_call_result,
    read_jsonl_from_volume,
)
from src.utils.auth import verify_api_key

router = APIRouter()


@router.get("/jobs/{job_id}/status", dependencies=[Depends(verify_api_key)])
async def get_status(job_id: str):
    """
    Poll the status of a submitted PDF job.
    Lightweight — returns job_id, status, output_path, error only.

    Args:
        job_id (str): Job ID from /parse/pdf

    Returns:
        JSONResponse: Lightweight status response
    """
    from src.models.enums import JobStatusEnum

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


@router.get(
    "/jobs/{job_id}/result",
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
    from src.models.enums import JobStatusEnum

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


@router.get(
    "/jobs/{job_id}/download",
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
    from pathlib import Path

    from src.models.enums import JobStatusEnum

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

    try:
        elements = await read_jsonl_from_volume(output_filename)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

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
