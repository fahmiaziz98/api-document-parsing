import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from src.api import health
from src.api.v1 import router as v1_router
from src.models.response import ErrorDetail, ErrorResponse
from src.utils.errors import AppException

web_app = FastAPI(
    title="Document Parsing",
    version="0.1.5",
    docs_url="/docs",
)


@web_app.middleware("http")
async def add_request_id(request: Request, call_next):
    """
    Add request_id to every request for tracing.

    Generates a UUID and injects it into request state,
    then includes in response header X-Request-ID.
    """
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    logger.info(
        f"{request.method} {request.url.path}",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        },
    )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Exception handlers
@web_app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle custom AppException with unified error response."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    error_response = ErrorResponse(
        error=ErrorDetail(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=error_response.model_dump())


@web_app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle FastAPI validation errors with unified error response."""
    from src.models.enums import ErrorCodeEnum

    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    details = {
        "validation_errors": [
            {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
    }
    error_response = ErrorResponse(
        error=ErrorDetail(
            code=ErrorCodeEnum.VALIDATION_ERROR,
            message="Request validation failed",
            details=details,
            request_id=request_id,
        )
    )
    return JSONResponse(status_code=422, content=error_response.model_dump())


# Include routers
web_app.include_router(health.router)
web_app.include_router(v1_router.v1_router)

__all__ = ["web_app"]
