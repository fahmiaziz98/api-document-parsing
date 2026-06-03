import uuid
from typing import Any

from src.models.enums import ErrorCodeEnum


class AppException(Exception):
    """Base exception class for API errors with unified response format."""

    def __init__(
        self,
        code: ErrorCodeEnum,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.request_id = request_id or str(uuid.uuid4())
        super().__init__(self.message)


class ValidationError(AppException):
    """Raised when request validation fails (422)."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.VALIDATION_ERROR,
            message=message,
            status_code=422,
            details=details,
            request_id=request_id,
        )


class UnsupportedFileError(AppException):
    """Raised when file type is not supported (422)."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.UNSUPPORTED_FILE,
            message=message,
            status_code=422,
            details=details,
            request_id=request_id,
        )


class AuthError(AppException):
    """Raised when authentication fails (401)."""

    def __init__(
        self,
        message: str = "Unauthorized",
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.AUTH_FAILED,
            message=message,
            status_code=401,
            details=details,
            request_id=request_id,
        )


class JobNotFoundError(AppException):
    """Raised when job is not found or expired (404)."""

    def __init__(
        self,
        job_id: str,
        message: str = "Job not found or expired",
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.JOB_NOT_FOUND,
            message=message,
            status_code=404,
            details=details or {"job_id": job_id},
            request_id=request_id,
        )


class JobExpiredError(AppException):
    """Raised when job has expired (404)."""

    def __init__(
        self,
        job_id: str,
        message: str = "Job expired (>7 days)",
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.JOB_EXPIRED,
            message=message,
            status_code=404,
            details={"job_id": job_id},
            request_id=request_id,
        )


class JobStillRunningError(AppException):
    """Raised when job is still processing (202)."""

    def __init__(
        self,
        job_id: str,
        message: str = "Job still processing",
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.JOB_STILL_RUNNING,
            message=message,
            status_code=202,
            details={"job_id": job_id},
            request_id=request_id,
        )


class ParsingFailedError(AppException):
    """Raised when parsing fails in Modal worker (500)."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.PARSING_FAILED,
            message=message,
            status_code=500,
            details=details,
            request_id=request_id,
        )


class InternalError(AppException):
    """Raised for unexpected internal errors (500)."""

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ):
        super().__init__(
            code=ErrorCodeEnum.INTERNAL_ERROR,
            message=message,
            status_code=500,
            details=details,
            request_id=request_id,
        )
