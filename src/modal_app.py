import json
import tempfile
from pathlib import Path

import fitz
import modal
from loguru import logger

app = modal.App("annual-report-parser")

results_volume = modal.Volume.from_name("parser-results", create_if_missing=True)
model_volume = modal.Volume.from_name("docling-models", create_if_missing=True)

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

GPU_CONFIG = "A10G"


@app.function(
    image=image,
    gpu=GPU_CONFIG,
    timeout=1800,
    secrets=[modal.Secret.from_name("parser-secret")],
    volumes={
        "/results": results_volume,
        "/root/.cache": model_volume,
    },
)
def parse_pdf(
    file_bytes: bytes,
    filename: str,
    company: str,
    year: int,
    start_page: int | None = None,
    end_page: int | None = None,
    enable_rotate: bool = False,
    enable_crop: bool = False,
) -> dict:
    """
    Modal function to parse a PDF file, performing layout analysis, OCR, and table extraction.

    Args:
        file_bytes (bytes): File bytes
        filename (str): File name
        company (str): Company name
        year (int): Year
        start_page (int | None): Start page
        end_page (int | None): End page
        enable_rotate (bool): Enable rotation
        enable_crop (bool): Enable crop

    Returns:
        dict: Job result

    Raises:
        Exception: If the job fails
    """
    from src.core.exporter import export_raw_elements
    from src.core.parser import build_pdf_converter
    from src.core.preprocess import preprocess_pdf
    from src.models.response import JobStatusEnum
    from src.utils.logging import setup_logging

    try:
        setup_logging()

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
                    dpi=200,
                )

            converter = build_pdf_converter()

            if start_page or end_page:
                pdf_doc = fitz.open(str(input_path))
                total_pages = len(pdf_doc)
                pdf_doc.close()

                resolved_start = start_page or 1
                resolved_end = end_page or total_pages

                resolved_start = max(1, resolved_start)
                resolved_end = min(total_pages, resolved_end)

                page_range = (resolved_start, resolved_end)
                logger.info(f"Docling page range: {page_range} / {total_pages} pages")
            else:
                page_range = None
                logger.info("Docling page range: full document")

            convert_kwargs = dict(source=str(input_path), raises_on_error=False)
            if page_range is not None:
                convert_kwargs["page_range"] = page_range

            result = converter.convert(**convert_kwargs)

            doc = result.document

            logger.info(
                f"PDF parsed: texts={len(doc.texts)} "
                f"tables={len(doc.tables)} "
                f"pictures={len(doc.pictures)}"
            )

            elements = export_raw_elements(doc, company, year, filename)
            output_filename = _save_jsonl(elements, company, year, filename)

            return {
                "status": JobStatusEnum.DONE,
                "element_count": len(elements),
                "output_path": output_filename,
                "elements": elements,
            }
    except Exception as e:
        logger.error("parse_pdf failed catastrophically", exc_info=True)
        return {"status": JobStatusEnum.ERROR, "error": str(e)}


@app.function(
    image=image,
    gpu=GPU_CONFIG,
    timeout=600,
    secrets=[modal.Secret.from_name("parser-secret")],
    volumes={
        "/results": results_volume,
        "/root/.cache": model_volume,
    },
)
def parse_image(
    file_bytes: bytes,
    filename: str,
    company: str,
    year: int,
    enable_rotate: bool = False,
    enable_crop: bool = False,
) -> dict:
    """
    Modal function to parse a single image using Docling's visual extraction logic.

    Args:
        file_bytes (bytes): File bytes
        filename (str): File name
        company (str): Company name
        year (int): Year
        enable_rotate (bool): Enable rotation
        enable_crop (bool): Enable crop

    Returns:
        dict: Job result

    Raises:
        Exception: If the job fails
    """
    from src.core.exporter import export_raw_elements
    from src.core.parser import build_image_converter
    from src.core.preprocess import preprocess_image
    from src.models.response import JobStatusEnum
    from src.utils.logging import setup_logging

    try:
        setup_logging()

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
                        f"Rotation applied: {rotation_result.angle.name} "
                        f"confidence={rotation_result.confidence:.2f}"
                    )

            converter = build_image_converter()
            result = converter.convert(str(input_path), raises_on_error=False)
            doc = result.document

            logger.info(
                f"Image parsed: texts={len(doc.texts)} "
                f"tables={len(doc.tables)} "
                f"pictures={len(doc.pictures)}"
            )

            elements = export_raw_elements(doc, company, year, filename)
            output_filename = _save_jsonl(elements, company, year, filename)

            return {
                "status": JobStatusEnum.DONE,
                "element_count": len(elements),
                "output_path": output_filename,
                "elements": elements,
            }
    except Exception as e:
        logger.error("parse_image failed catastrophically", exc_info=True)
        return {"status": JobStatusEnum.ERROR, "error": str(e)}


def _save_jsonl(elements: list[dict], company: str, year: int, filename: str) -> str:
    """
    Save elements to a JSONL file

    Args:
        elements (list[dict]): List of elements
        company (str): Company name
        year (int): Year
        filename (str): File name

    Returns:
        str: Output file name
    """
    output_filename = f"{company}_{year}_{Path(filename).stem}.jsonl"
    output_path = Path(VOLUME_MOUNT) / output_filename
    with open(output_path, "w", encoding="utf-8") as f:
        for el in elements:
            f.write(json.dumps(el, ensure_ascii=False) + "\n")
    results_volume.commit()
    logger.info(f"Saved {len(elements)} elements → {output_path}")
    return output_filename
