import json
import tempfile
import time
from datetime import datetime
from pathlib import Path

import fitz
import modal
from loguru import logger

app = modal.App("api-document-parsing")
GPU_CONFIG = "A10G"

results_volume = modal.Volume.from_name("parser-results", create_if_missing=True)
model_volume = modal.Volume.from_name("docling-models", create_if_missing=True)
VOLUME_MOUNT = "/results"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender-dev")
    .pip_install(
        "docling==2.96.1",
        "docling-surya==0.1.0",
        "openai>=1.0.0,<2.0.0",
        "fastapi>=0.115.0,<1.0.0",
        "python-multipart>=0.0.9,<1.0.0",
        "loguru>=0.7.0,<1.0.0",
        "pandas>=2.0.0,<3.0.0",
        "tabulate>=0.9.0,<1.0.0",
        "scipy>=1.11.0,<2.0.0",
        "opencv-python-headless>=4.8.0,<5.0.0",
        "numpy>=1.26.0,<3.0.0",
        "pymupdf>=1.24.0,<2.0.0",
        "transformers>=4.55.0,<5.0.0",
    )
    .add_local_dir("src", remote_path="/root/src")
)


@app.cls(
    image=image,
    gpu=GPU_CONFIG,
    timeout=1800,
    secrets=[modal.Secret.from_name("parser-secret")],
    volumes={
        "/results": results_volume,
        "/root/model-cache": model_volume,
    },
    env={
        "HF_HOME": "/root/model-cache/huggingface",
        "DOCLING_CACHE_DIR": "/root/model-cache/docling-models",
        "TORCH_HOME": "/root/model-cache/torch",
        "DETECTOR_BATCH_SIZE": "36",
        "RECOGNITION_BATCH_SIZE": "512",
        "ORDER_BATCH_SIZE": "32",
    },
    scaledown_window=15 * 60,
)
@modal.concurrent(max_inputs=5, target_inputs=2)
class DocumentParser:
    """Single class for PDF and image parsing."""

    @modal.enter()
    def load(self):
        from src.core.parser import build_image_converter, build_pdf_converter
        from src.utils.logging import setup_logging

        setup_logging()
        logger.info("DocumentParser container starting — loading models...")

        try:
            self.pdf_converter = build_pdf_converter()
            logger.info("PDF converter loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load PDF converter: {e}", exc_info=True)
            raise

        try:
            self.image_converter = build_image_converter()
            logger.info("Image converter loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load image converter: {e}", exc_info=True)
            raise

        logger.info("DocumentParser models loaded and ready")

    def _finish_parse(self, doc, metadata: dict, filename: str) -> dict:
        """
        Shared post-conversion step: export elements, persist to JSONL, return result dict.

        Args:
            doc: Docling document object produced by a converter.
            metadata: Arbitrary user-supplied metadata dict.
            filename: Original uploaded filename.

        Returns:
            dict: Result payload with status, element_count, output_path, and elements.
        """
        from src.core.exporter import export_raw_elements
        from src.models.response import JobStatusEnum

        elements = export_raw_elements(doc, metadata, filename)
        output_filename = _save_jsonl(elements, filename)
        logger.info(
            f"Parsed: texts={len(doc.texts)} tables={len(doc.tables)} pictures={len(doc.pictures)}"
        )
        return {
            "status": JobStatusEnum.DONE,
            "element_count": len(elements),
            "output_path": output_filename,
            "elements": elements,
        }

    @modal.method()
    def parse_pdf(
        self,
        file_bytes: bytes,
        filename: str,
        metadata: dict,
        start_page: int | None = None,
        end_page: int | None = None,
        enable_rotate: bool = False,
        enable_crop: bool = False,
    ) -> dict:
        """
        Parse a PDF file.

        Args:
            file_bytes: Bytes of the PDF file
            filename: Original uploaded filename
            metadata: Arbitrary user-supplied metadata (e.g. company, year…)
            start_page: Start page (1-indexed, None = from beginning)
            end_page: End page (1-indexed, None = to end)
            enable_rotate: Enable auto-rotation
            enable_crop: Enable content cropping

        Returns:
            dict: Job status, elements, and metadata for building PdfParseResult
        """
        from src.core.preprocess import preprocess_pdf
        from src.models.response import JobStatusEnum

        t_start = time.monotonic()

        try:
            with tempfile.TemporaryDirectory() as tmp:
                input_path = Path(tmp) / filename
                input_path.write_bytes(file_bytes)

                if enable_rotate or enable_crop:
                    processed_path = Path(tmp) / f"processed_{filename}"
                    input_path = preprocess_pdf(
                        input_path=input_path,
                        output_path=processed_path,
                        start_page=start_page,
                        end_page=end_page,
                        enable_rotate=enable_rotate,
                        enable_crop=enable_crop,
                        dpi=72,
                    )

                pdf_doc = fitz.open(str(input_path))
                total_pages = len(pdf_doc)
                pdf_doc.close()

                if start_page or end_page:
                    resolved_start = max(1, start_page or 1)
                    resolved_end = min(total_pages, end_page or total_pages)
                    page_range = (resolved_start, resolved_end)
                    logger.info(f"Page range: {page_range} / {total_pages}")
                else:
                    resolved_start = 1
                    resolved_end = total_pages
                    page_range = None
                    logger.info("Page range: full document")

                convert_kwargs = dict(source=str(input_path), raises_on_error=False)
                if page_range is not None:
                    convert_kwargs["page_range"] = page_range

                result = self.pdf_converter.convert(**convert_kwargs)
                parsed = self._finish_parse(result.document, metadata, filename)

                duration = time.monotonic() - t_start
                return {
                    **parsed,
                    "filename": filename,
                    "duration_seconds": round(duration, 2),
                    "user_metadata": metadata,
                    "total_pages": total_pages,
                    "start_page": resolved_start,
                    "end_page": resolved_end,
                }

        except Exception as e:
            logger.error("parse_pdf failed", exc_info=True)
            return {"status": JobStatusEnum.ERROR, "error": str(e)}

    @modal.method()
    def parse_image(
        self,
        file_bytes: bytes,
        filename: str,
        metadata: dict,
        enable_rotate: bool = False,
        enable_crop: bool = False,
    ) -> dict:
        """
        Parse an image file.

        Args:
            file_bytes: Bytes of the image file
            filename: Original uploaded filename
            metadata: Arbitrary user-supplied metadata (e.g. company, year…)
            enable_rotate: Enable auto-rotation
            enable_crop: Enable content cropping

        Returns:
            dict: Job status and elements
        """
        from src.core.preprocess import preprocess_image
        from src.models.response import JobStatusEnum

        try:
            with tempfile.TemporaryDirectory() as tmp:
                input_path = Path(tmp) / filename
                input_path.write_bytes(file_bytes)

                if enable_rotate or enable_crop:
                    processed_path = Path(tmp) / f"processed_{filename}"
                    _, rotation_result = preprocess_image(
                        image_path=input_path,
                        enable_rotate=enable_rotate,
                        enable_crop=enable_crop,
                        output_path=processed_path,
                    )
                    input_path = processed_path
                    if rotation_result:
                        logger.info(
                            f"Rotation: {rotation_result.angle.name} "
                            f"confidence={rotation_result.confidence:.2f}"
                        )

                result = self.image_converter.convert(str(input_path), raises_on_error=False)
                return self._finish_parse(result.document, metadata, filename)

        except Exception as e:
            logger.error("parse_image failed", exc_info=True)
            return {"status": JobStatusEnum.ERROR, "error": str(e)}


def _save_jsonl(elements: list[dict], filename: str) -> str:
    """
    Save elements to a JSONL file on Modal Volume.

    Output filename: ``{stem}_{YYYYMMDD_HHMMSS}.jsonl``
    Example: ``report.pdf`` → ``report_20260318_082054.jsonl``

    Args:
        elements: List of elements to save
        filename: Original uploaded filename

    Returns:
        Output filename (relative, not full path)
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_filename = f"{Path(filename).stem}_{timestamp}.jsonl"
    output_path = Path(VOLUME_MOUNT) / output_filename
    with open(output_path, "w", encoding="utf-8") as f:
        for el in elements:
            f.write(json.dumps(el, ensure_ascii=False) + "\n")
    results_volume.commit()
    logger.info(f"Saved {len(elements)} elements → {output_path}")
    return output_filename
