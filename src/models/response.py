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
    """Enumeration of extracted document element types."""

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


class ElementMetadata(BaseModel):
    """Metadata detailing the origin and bounding box of an extracted element."""

    source: str = Field(..., description="Original filename of the document.")
    company: str = Field(..., description="Company name associated with the document.")
    year: int = Field(..., description="Reporting year of the document.")
    doc_ref: str = Field(..., description="Internal document reference ID from the parser.")
    page: int = Field(
        ..., description="Primary page number where the element is found (1-indexed)."
    )
    pages: list[int] = Field(..., description="List of all page numbers spanned by the element.")
    bbox: dict[str, float] | None = Field(
        None, description="Bounding box coordinates (l, t, r, b) of the element."
    )


class Element(BaseModel):
    """A single extracted logical element from the document (e.g., text block, table, figure)."""

    element_type: ElementTypeEnum = Field(
        ..., description="The semantic classification of the element."
    )
    label: str = Field(..., description="Original parser label (e.g., DocItemLabel value).")
    content: str = Field(..., description="Extracted text content or table representation.")
    table_markdown: str | None = Field(
        None, description="Markdown format of the table, if the element is a table."
    )
    full_content: str | None = Field(
        None, description="Aggregated full content for the page this element is on (injected)."
    )
    metadata: ElementMetadata = Field(
        ..., description="Metadata and positioning info for the element."
    )


class ParseResult(BaseModel):
    """Response model containing all parsed elements and final job status."""

    job_id: str = Field(..., description="Unique identifier for the Modal job.")
    status: JobStatusEnum = Field(
        default=JobStatusEnum.DONE, description="Final status of the job."
    )
    element_count: int = Field(..., description="Total number of elements extracted.")
    elements: list[Element] = Field(..., description="List of extracted elements.")
