import json

from fastapi import HTTPException, UploadFile, status

# File extension constants
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# File size limits (bytes)
MAX_PDF_SIZE = 100 * 1024 * 1024  # 100 MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


def _parse_metadata(metadata_str: str) -> dict:
    """
    Parse JSON metadata string into a dictionary.

    Args:
        metadata_str: JSON string of metadata

    Returns:
        dict: Parsed metadata

    Raises:
        HTTPException: If metadata is not valid JSON or not a dict
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
    Validate that the file extension is in the allowed set.

    Args:
        filename: Uploaded filename
        allowed: Set of allowed extensions (e.g., {".pdf"})

    Raises:
        HTTPException: If extension is not allowed
    """
    suffix = "." + (filename or "").rsplit(".", 1)[-1].lower()
    if suffix not in allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file: {suffix}. Allowed: {allowed}",
        )


def _validate_page_range(start: int | None, end: int | None) -> None:
    """
    Validate that start_page <= end_page if both are provided.

    Args:
        start: Start page number (1-indexed)
        end: End page number (1-indexed)

    Raises:
        HTTPException: If start_page > end_page
    """
    if start and end and start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_page must be <= end_page",
        )


def optional_int(value: str | None = None) -> int | None:
    """
    Convert a string to an optional integer.

    Args:
        value: String to convert or None

    Returns:
        int | None: Converted integer or None if input is empty/None

    Raises:
        HTTPException: If value is not a valid integer
    """
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
    """
    Read uploaded file bytes.

    Args:
        file: FastAPI UploadFile object

    Returns:
        bytes: File content

    Raises:
        HTTPException: If file reading fails
    """
    try:
        return await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to read file: {e}"
        ) from e


def _validate_file_size(file_bytes: bytes, filename: str, max_size: int) -> None:
    """
    Validate that uploaded file does not exceed size limit.

    Args:
        file_bytes: File content bytes
        filename: Uploaded filename
        max_size: Maximum allowed size in bytes

    Raises:
        HTTPException: If file exceeds limit
    """
    file_size = len(file_bytes)
    if file_size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"File '{filename}' exceeds maximum size of {max_mb:.0f}MB (got {file_size / (1024 * 1024):.1f}MB)",
        )
