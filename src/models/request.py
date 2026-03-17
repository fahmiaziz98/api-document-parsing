from pydantic import BaseModel, Field, model_validator


class PdfParseRequest(BaseModel):
    """Request model for parsing a PDF file."""

    company: str = Field(..., description="Company name, e.g. 'ANTAM'")
    year: int = Field(..., description="Report year, e.g. 2024")
    start_page: int | None = Field(None, ge=1, description="Start page (1-indexed, inclusive)")
    end_page: int | None = Field(None, ge=1, description="End page (1-indexed, inclusive)")
    enable_rotate: bool = Field(False, description="Auto-rotate pages before parsing")
    enable_crop: bool = Field(False, description="Auto-crop whitespace before parsing")

    @model_validator(mode="after")
    def validate_page_range(self) -> "PdfParseRequest":
        if self.start_page and self.end_page:
            if self.start_page > self.end_page:
                raise ValueError("start_page must be <= end_page")
        return self


class ImageParseRequest(BaseModel):
    """Request model for parsing an image file."""

    company: str = Field(..., description="Company name, e.g. 'ANTAM'")
    year: int = Field(..., description="Report year, e.g. 2024")
    enable_rotate: bool = Field(False, description="Auto-rotate image before parsing")
    enable_crop: bool = Field(False, description="Auto-crop whitespace before parsing")
