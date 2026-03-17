import os

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.layout_model_specs import DOCLING_LAYOUT_HERON
from docling.datamodel.pipeline_options import (
    LayoutOptions,
    PictureDescriptionApiOptions,
    TableFormerMode,
    TableStructureOptions,
    ThreadedPdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from docling.pipeline.threaded_standard_pdf_pipeline import ThreadedStandardPdfPipeline
from docling_surya import SuryaOcrOptions
from loguru import logger

PICTURE_DESCRIPTION_PROMPT = """You are analyzing an image from a corporate annual report. Describe it concisely and accurately in 3-5 sentences following this structure:

1. IMAGE TYPE: Identify what type of visual this is (bar chart, line graph, pie chart, organizational chart, photograph, map, diagram, etc.)
2. MAIN CONTENT: What is the primary subject or data being shown? Include the title if visible.
3. KEY DATA POINTS: Extract the most important numbers, percentages, trends, or labels. Include axis labels and units if present.
4. INSIGHT: What is the main takeaway or trend shown?

If the image is a photograph of people, facilities, or operations, describe what is shown and its business context.
If the image contains text only, transcribe the key text.
Do not include phrases like "The image shows" — start directly with the type."""

LAYOUT_BATCH = 64
TABLE_BATCH = 4
OCR_BATCH = 64


def _picture_description_options() -> PictureDescriptionApiOptions | None:
    """Configure Picture Description options using Groq API, gracefully failing if keys are missing."""
    groq_url = os.getenv("GROQ_BASE_URL")
    groq_key = os.getenv("GROQ_API_KEY")

    if not groq_url or not groq_key:
        logger.warning(
            "GROQ_BASE_URL or GROQ_API_KEY not set. Picture description will be disabled."
        )
        return None

    groq_model = os.getenv("GROQ_MODEL_ID", "llama-3.3-70b-versatile")

    return PictureDescriptionApiOptions(
        url=f"{groq_url}/chat/completions",
        params=dict(model=groq_model, seed=42, max_completion_tokens=512),
        headers={
            "Authorization": f"Bearer {groq_key}",
            "Content-Type": "application/json",
        },
        prompt=PICTURE_DESCRIPTION_PROMPT,
        timeout=90,
    )


def build_pdf_converter() -> DocumentConverter:
    """
    Build the full Docling pipeline for PDF parsing.
    Includes SuryaOCR, TableFormer, layout heron, and optional picture description.
    """
    pipeline_options = ThreadedPdfPipelineOptions(
        do_ocr=True,
        ocr_model="suryaocr",
        allow_external_plugins=True,
        ocr_options=SuryaOcrOptions(lang=["en", "id"], force_full_page_ocr=False),
        accelerator_options=AcceleratorOptions(
            device=AcceleratorDevice.CUDA,
            num_threads=8,
        ),
        layout_batch_size=LAYOUT_BATCH,
        table_batch_size=TABLE_BATCH,
        ocr_batch_size=OCR_BATCH,
        enable_remote_services=True,
    )
    pipeline_options.layout_options = LayoutOptions(model_spec=DOCLING_LAYOUT_HERON)
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options = TableStructureOptions(
        mode=TableFormerMode.ACCURATE,
        do_cell_matching=True,
    )

    pic_opts = _picture_description_options()
    if pic_opts:
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = pic_opts
    else:
        pipeline_options.do_picture_description = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_cls=ThreadedStandardPdfPipeline,
                pipeline_options=pipeline_options,
            ),
        }
    )
    logger.info("PDF converter built")
    return converter


def build_image_converter() -> DocumentConverter:
    """
    Build the full Docling pipeline for image parsing.
    Includes SuryaOCR, TableFormer, layout heron, and optional picture description.
    """

    pipeline_options = ThreadedPdfPipelineOptions(
        do_ocr=True,
        ocr_model="suryaocr",
        allow_external_plugins=True,
        ocr_options=SuryaOcrOptions(lang=["en", "id"], force_full_page_ocr=False),
        accelerator_options=AcceleratorOptions(
            device=AcceleratorDevice.CUDA,
            num_threads=8,
        ),
        layout_batch_size=LAYOUT_BATCH,
        table_batch_size=TABLE_BATCH,
        ocr_batch_size=OCR_BATCH,
        enable_remote_services=True,
    )
    pipeline_options.layout_options = LayoutOptions(model_spec=DOCLING_LAYOUT_HERON)
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options = TableStructureOptions(
        mode=TableFormerMode.ACCURATE,
        do_cell_matching=True,
    )

    pic_opts = _picture_description_options()
    if pic_opts:
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = pic_opts
    else:
        pipeline_options.do_picture_description = False

    converter = DocumentConverter(
        format_options={
            InputFormat.IMAGE: ImageFormatOption(
                pipeline_options=pipeline_options,
            ),
        }
    )
    logger.info("Image converter built")
    return converter
