import json
import tempfile
from datetime import datetime
from pathlib import Path

import fitz
import modal
from loguru import logger

app = modal.App("annual-report-parser")

results_volume = modal.Volume.from_name("parser-results", create_if_missing=True)
model_volume = modal.Volume.from_name("docling-models", create_if_missing=True)
VOLUME_MOUNT = "/results"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("libgl1", "libglib2.0-0", "libsm6", "libxext6", "libxrender-dev")
    .pip_install(
        "docling",
        "docling-surya",
        "openai",
        "fastapi",
        "python-multipart",
        "loguru",
        "pandas",
        "tabulate",
        "scipy",
        "opencv-python-headless",
        "numpy",
        "pymupdf",
    )
    .add_local_dir("src", remote_path="/root/src")
)


@app.cls(
    image=image,
    gpu="A10G",
    timeout=1800,
    secrets=[modal.Secret.from_name("parser-secret")],
    volumes={
        "/results": results_volume,
        "/root/model-cache": model_volume,
    },
    env={
        # Model cache paths
        "HF_HOME": "/root/model-cache/huggingface",
        "DOCLING_CACHE_DIR": "/root/model-cache/docling-models",
        "TORCH_HOME": "/root/model-cache/torch",
        "DETECTOR_BATCH_SIZE": "36",
        "RECOGNITION_BATCH_SIZE": "512",
        "ORDER_BATCH_SIZE": "32",
    },
    scaledown_window=15 * 60,  # 15 minutes
)
@modal.concurrent(max_inputs=5, target_inputs=2)
class DocumentParser:
    """
    Single class for PDF and image parsing.
    """

    @modal.enter()
    def load(self):
        from src.core.parser import build_image_converter, build_pdf_converter
        from src.utils.logging import setup_logging

        setup_logging()
        logger.info("DocumentParser container starting — loading models...")

        self.pdf_converter = build_pdf_converter()
        self.image_converter = build_image_converter()

        logger.info("DocumentParser models loaded and ready")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _finish_parse(self, doc, metadata: dict, filename: str) -> dict:
        """
        Shared post-conversion step: export elements, persist to JSONL, return result dict.

        Extracted to eliminate the identical tail block that was duplicated in both
        ``parse_pdf`` and ``parse_image``.

        Args:
            doc: Docling document object produced by a converter.
            metadata: Arbitrary user-supplied metadata dict.
            filename: Original uploaded filename (used for export and output naming).

        Returns:
            dict: Result payload with status, element_count, output_path, and elements.
        """
        from src.core.exporter import export_raw_elements
        from src.models.response import JobStatusEnum

        elements = export_raw_elements(doc, metadata, filename)
        output_filename = _save_jsonl(elements, filename)
        logger.info(
            f"Parsed: texts={len(doc.texts)} "
            f"tables={len(doc.tables)} "
            f"pictures={len(doc.pictures)}"
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
        Parse a PDF file containing a corporate annual report.

        Args:
            file_bytes: Bytes of the PDF file
            filename: Filename
            metadata: Arbitrary user-supplied metadata (e.g. company, year, label, type…)
            start_page: Start page
            end_page: End page
            enable_rotate: Enable auto-rotation
            enable_crop: Enable content cropping

        Returns:
            dict: Job status and results
        """
        from src.core.preprocess import preprocess_pdf
        from src.models.response import JobStatusEnum

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

                if start_page or end_page:
                    pdf_doc = fitz.open(str(input_path))
                    total_pages = len(pdf_doc)
                    pdf_doc.close()

                    resolved_start = max(1, start_page or 1)
                    resolved_end = min(total_pages, end_page or total_pages)
                    page_range = (resolved_start, resolved_end)
                    logger.info(f"Page range: {page_range} / {total_pages}")
                else:
                    page_range = None
                    logger.info("Page range: full document")

                convert_kwargs = dict(source=str(input_path), raises_on_error=False)
                if page_range is not None:
                    convert_kwargs["page_range"] = page_range

                result = self.pdf_converter.convert(**convert_kwargs)
                return self._finish_parse(result.document, metadata, filename)

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
        Parse an image file containing a corporate annual report.

        Args:
            file_bytes: Bytes of the image file
            filename: Filename
            metadata: Arbitrary user-supplied metadata (e.g. company, year, label, type…)
            enable_rotate: Enable auto-rotation
            enable_crop: Enable content cropping

        Returns:
            dict: Job status and results
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
    Save elements to a JSONL file.

    The output filename is derived from the original file stem combined with
    the current timestamp: ``{stem}_{YYYYMMDD_HHMMSS}.jsonl``.
    For example, ``data.pdf`` → ``data_20260318_082054.jsonl``.

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
