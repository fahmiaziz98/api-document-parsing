from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from src.vision import AutoRotate, ContentCropper
from src.vision.core.types import RotationResult


def preprocess_image(
    image_path: str | Path,
    enable_rotate: bool = False,
    enable_crop: bool = False,
    output_path: str | Path | None = None,
) -> tuple[np.ndarray, RotationResult | None]:
    """
    Preprocess a single image (rotate and crop).

    Args:
        image_path: Path to the input image file.
        enable_rotate: Whether to enable auto-rotation.
        enable_crop: Whether to enable auto-cropping.
        output_path: Path to save the preprocessed image file.

    Returns:
        Tuple of preprocessed image and rotation result.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Cannot read image: {image_path}")

    rotation_result = None

    try:
        if enable_rotate:
            auto_rotate = AutoRotate()
            img, rotation_result = auto_rotate.auto_rotate(img)
            logger.info(
                f"Rotation: angle={rotation_result.angle.name} "
                f"confidence={rotation_result.confidence:.2f} "
                f"applied={rotation_result.applied_rotation}"
            )

        if enable_crop:
            cropper = ContentCropper()
            img = cropper.crop(img)
            logger.info("Crop applied")
    except Exception as e:
        logger.error(f"Image preprocessing failed for {image_path}: {e}")

    if output_path:
        cv2.imwrite(str(output_path), img)

    return img, rotation_result


def preprocess_pdf(
    input_path: Path,
    output_path: Path,
    start_page: int | None = None,
    end_page: int | None = None,
    enable_rotate: bool = False,
    enable_crop: bool = False,
    dpi: int = 144,
) -> Path:
    """
    Preprocess PDF using PyMuPDF native operations.

    Args:
        input_path: Path to the input PDF file.
        output_path: Path to save the preprocessed PDF file.
        start_page: Start page number (1-indexed).
        end_page: End page number (1-indexed).
        enable_rotate: Whether to enable auto-rotation.
        enable_crop: Whether to enable auto-cropping.
        dpi: DPI for rendering images.

    Returns:
        Path to the preprocessed PDF file.
    """
    if not enable_rotate and not enable_crop:
        return input_path

    import cv2
    import fitz
    import numpy as np

    from src.vision import AutoRotate, ContentCropper

    doc = fitz.open(str(input_path))
    n_pages = len(doc)

    p_start = (start_page - 1) if start_page else 0
    p_end = min((end_page - 1) if end_page else (n_pages - 1), n_pages - 1)

    logger.info(
        f"Preprocessing PDF pages {p_start + 1}–{p_end + 1}/{n_pages} "
        f"(rotate={enable_rotate}, crop={enable_crop})"
    )

    for page_idx in range(p_start, p_end + 1):
        page = doc[page_idx]

        try:
            if enable_rotate:
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, 3
                )
                img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                auto_rotate = AutoRotate()
                _, rotation_result = auto_rotate.auto_rotate(img_bgr)

                if rotation_result and rotation_result.applied_rotation:
                    angle = int(rotation_result.angle)
                    current = page.rotation
                    new_rotation = (current + angle) % 360
                    page.set_rotation(new_rotation)
                    logger.info(
                        f"  Page {page_idx + 1}: rotated {angle}° "
                        f"(confidence={rotation_result.confidence:.2f})"
                    )
                else:
                    logger.info(f"  Page {page_idx + 1}: no rotation needed")

            if enable_crop:
                mat = fitz.Matrix(dpi / 72, dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, 3
                )
                img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

                h_orig, w_orig = img_bgr.shape[:2]
                cropper = ContentCropper()
                img_cropped = cropper.crop(img_bgr)
                h_crop, w_crop = img_cropped.shape[:2]

                area_ratio = (h_crop * w_crop) / (h_orig * w_orig)
                if area_ratio < 0.98:
                    mediabox = page.mediabox
                    scale_x = mediabox.width / w_orig
                    scale_y = mediabox.height / h_orig

                    pad_x = ((w_orig - w_crop) / 2) * scale_x
                    pad_y = ((h_orig - h_crop) / 2) * scale_y

                    cropbox = fitz.Rect(
                        mediabox.x0 + pad_x,
                        mediabox.y0 + pad_y,
                        mediabox.x1 - pad_x,
                        mediabox.y1 - pad_y,
                    )

                    cropbox = cropbox & mediabox  # intersection operator fitz

                    if cropbox.is_valid and cropbox.width > 10 and cropbox.height > 10:
                        page.set_cropbox(cropbox)
                        logger.info(
                            f"  Page {page_idx + 1}: cropbox set (area_ratio={area_ratio:.2f})"
                        )
                    else:
                        logger.warning(f"  Page {page_idx + 1}: invalid cropbox, skipped")
                else:
                    logger.info(f"  Page {page_idx + 1}: crop insignificant, skipped")
        except Exception as e:
            logger.error(f"  Page {page_idx + 1}: Preprocessing failed with error: {e}")

    doc.save(str(output_path), garbage=4, deflate=True)
    doc.close()

    logger.info(f"Preprocessed PDF saved → {output_path}")
    return output_path
