from enum import StrEnum


class JobStatusEnum(StrEnum):
    """Enumeration of possible job parsing statuses."""

    SUBMITTED = "submitted"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"
    EXPIRED = "expired"


class ElementTypeEnum(StrEnum):
    """Enumeration of possible element types in a parsed document — used internally by exporter."""

    TEXT = "text"
    HEADING = "heading"
    TABLE = "table"
    FIGURE = "figure"


class ErrorCodeEnum(StrEnum):
    """Unified error codes for API responses."""

    VALIDATION_ERROR = "VALIDATION_ERROR"  # 422 — input tidak valid
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"  # 422 — ekstensi tidak didukung
    AUTH_FAILED = "AUTH_FAILED"  # 401
    JOB_NOT_FOUND = "JOB_NOT_FOUND"  # 404
    JOB_EXPIRED = "JOB_EXPIRED"  # 404
    JOB_STILL_RUNNING = "JOB_STILL_RUNNING"  # 202
    PARSING_FAILED = "PARSING_FAILED"  # 500 — error dari Modal worker
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 500 — unexpected
