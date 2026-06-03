import json
import os
from collections import defaultdict
from pathlib import Path

import modal

from src.modal_app import results_volume
from src.models.response import (
    ImageMetadata,
    ImageParseResult,
    JobStatusEnum,
    PageContent,
    PageTableMarkdown,
    PdfMetadata,
    PdfParseResult,
)


async def _get_call_result(job_id: str, timeout: int = 0):
    """
    Get the result of a Modal job.

    Args:
        job_id (str): Job ID
        timeout (int): Timeout in seconds

    Returns:
        dict: Job result

    Raises:
        TimeoutError: If the job is still running
        modal.exception.NotFoundError: If the job is not found or expired
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
            extra_fields=user_metadata,
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
            extra_fields=user_metadata,
        ),
        full_content=full_content_pages,
        table_markdown=table_markdown_pages,
    )


async def read_jsonl_from_volume(output_filename: str) -> list[dict]:
    """
    Read JSONL file from Modal volume.

    Args:
        output_filename: Filename in /results/ directory

    Returns:
        list[dict]: Parsed elements from JSONL

    Raises:
        FileNotFoundError: If file not found on volume
    """
    await results_volume.reload.aio()

    file_path = f"/results/{output_filename}"
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Output file '{output_filename}' not found on volume.")

    elements = []
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                elements.append(json.loads(line))

    return elements
