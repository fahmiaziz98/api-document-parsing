from enum import StrEnum

from pydantic import BaseModel, Field


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


class JobSubmitted(BaseModel):
    """Response model indicating a parsing job has been successfully submitted to the queue."""

    job_id: str = Field(..., description="Unique identifier for the submitted Modal job.")
    status: JobStatusEnum = Field(
        default=JobStatusEnum.SUBMITTED, description="Current status of the job."
    )
    message: str = Field(
        default="Job submitted. Poll /status/{job_id} for results.",
        description="Helper message for next steps.",
    )


class JobStatus(BaseModel):
    """Response model representing the current status and output path for a job."""

    job_id: str = Field(..., description="Unique identifier for the Modal job.")
    status: JobStatusEnum = Field(..., description="Current status of the job.")
    element_count: int | None = Field(None, description="Number of elements parsed, if finished.")
    output_path: str | None = Field(
        None, description="Path or filename where the JSONL results are saved."
    )
    error: str | None = Field(None, description="Error message if the job failed.")


class PageContent(BaseModel):
    """Content extracted from a single page."""

    page: int = Field(..., description="Page number (1-indexed).")
    content: str = Field(..., description="Aggregated text content for this page.")


class PageTableMarkdown(BaseModel):
    """Table markdown extracted from a single page."""

    page: int = Field(..., description="Page number (1-indexed).")
    content: str = Field(..., description="Markdown representation of the table.")


class ImageMetadata(BaseModel):
    """Metadata for a parsed image file."""

    filename: str = Field(..., description="Original uploaded filename.")
    extension: str = Field(..., description="File extension, e.g. '.jpg'.")
    duration_seconds: float = Field(..., description="Parsing duration in seconds.")


class PdfMetadata(BaseModel):
    """Metadata for a parsed PDF file."""

    filename: str = Field(..., description="Original uploaded filename.")
    extension: str = Field(..., description="File extension, e.g. '.pdf'.")
    duration_seconds: float = Field(..., description="Parsing duration in seconds.")
    page_range: dict[str, int] = Field(
        ..., description="Parsed page range, e.g. {'start': 1, 'end': 10}."
    )


class ImageParseResult(BaseModel):
    """
    Response model for parsed image files.

    Images are always single-page, so full_content and table_markdown
    are flat strings rather than per-page lists.
    """

    job_id: str = Field(..., description="Unique identifier for the Modal job.")
    status: JobStatusEnum = Field(
        default=JobStatusEnum.DONE, description="Final status of the job."
    )
    page_count: int = Field(default=1, description="Always 1 for image inputs.")
    metadata: ImageMetadata = Field(..., description="File and parsing metadata.")
    full_content: str | None = Field(None, description="All extracted text from the image.")
    table_markdown: str | None = Field(
        None, description="Markdown table if a table was detected, otherwise null."
    )


class PdfParseResult(BaseModel):
    """
    Response model for parsed PDF files.

    PDFs can be multi-page, so full_content and table_markdown
    are per-page lists. table_markdown is an empty list if no tables found.
    """

    job_id: str = Field(..., description="Unique identifier for the Modal job.")
    status: JobStatusEnum = Field(
        default=JobStatusEnum.DONE, description="Final status of the job."
    )
    page_count: int = Field(..., description="Total number of pages parsed.")
    metadata: PdfMetadata = Field(..., description="File and parsing metadata.")
    full_content: list[PageContent] = Field(
        default_factory=list,
        description="Aggregated text content per page.",
    )
    table_markdown: list[PageTableMarkdown] = Field(
        default_factory=list,
        description="Markdown tables per page. Empty list if no tables found.",
    )
