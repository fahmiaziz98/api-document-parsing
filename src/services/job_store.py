import json
from pathlib import Path
from typing import Any

import modal

results_volume = modal.Volume.from_name("parser-results", create_if_missing=True)
VOLUME_MOUNT = "/results"


def save_job_metadata(
    job_id: str,
    filename: str,
    extension: str,
    submitted_at: str,
    completed_at: str,
    duration_seconds: float,
    total_pages: int,
    start_page: int | None,
    end_page: int | None,
    element_count: int,
    output_path: str,
    user_metadata: dict[str, Any],
) -> None:
    """
    Save job metadata to Modal Volume as JSON.

    Creates {job_id}.meta.json alongside {job_id}.jsonl in /results.

    Args:
        job_id: Unique job identifier (Modal FunctionCall ID)
        filename: Original uploaded filename (e.g., "report.pdf")
        extension: File extension (e.g., ".pdf")
        submitted_at: ISO 8601 timestamp when job was submitted
        completed_at: ISO 8601 timestamp when job completed
        duration_seconds: Total parsing duration in seconds
        total_pages: Total pages in document
        start_page: Starting page if range specified, else None
        end_page: Ending page if range specified, else None
        element_count: Number of elements parsed
        output_path: Filename of JSONL output (e.g., "report_20260603_010234.jsonl")
        user_metadata: Arbitrary key-value metadata supplied by user
    """
    metadata = {
        "job_id": job_id,
        "filename": filename,
        "extension": extension,
        "submitted_at": submitted_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "total_pages": total_pages,
        "start_page": start_page,
        "end_page": end_page,
        "element_count": element_count,
        "output_path": output_path,
        "user_metadata": user_metadata,
    }

    # Store in jobs/ subdirectory for organization
    jobs_dir = Path(VOLUME_MOUNT) / "jobs"
    jobs_dir.mkdir(exist_ok=True)

    meta_path = jobs_dir / f"{job_id}.meta.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)

    results_volume.commit()


def read_job_metadata(job_id: str) -> dict[str, Any] | None:
    """
    Read job metadata from Modal Volume.

    Args:
        job_id: Unique job identifier

    Returns:
        dict if metadata exists, None if not found or error occurs
    """
    try:
        jobs_dir = Path(VOLUME_MOUNT) / "jobs"
        meta_path = jobs_dir / f"{job_id}.meta.json"

        if not meta_path.exists():
            return None

        with open(meta_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
