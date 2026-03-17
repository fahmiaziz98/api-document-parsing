from collections import defaultdict

from docling_core.types.doc.labels import DocItemLabel
from loguru import logger

from src.models.response import ElementTypeEnum


def _extract_bbox(prov: list) -> dict[str, float] | None:
    """Helper to extract the bounding box from provisioning data safely."""
    for p in prov or []:
        if p.bbox:
            return {
                "l": round(p.bbox.l, 2),
                "t": round(p.bbox.t, 2),
                "r": round(p.bbox.r, 2),
                "b": round(p.bbox.b, 2),
            }
    return None


def _extract_pages(prov: list) -> tuple[int, list[int]]:
    """Helper to extract the starting page and all spanning pages from provisioning data."""
    pages = []
    page = 0
    for p in prov or []:
        pages.append(p.page_no)
        if not page:
            page = p.page_no
    return page, sorted(set(pages))


def _process_text_element(label, text: str, base_meta: dict) -> dict:
    """Formats a standard text or heading element."""
    element_type = (
        ElementTypeEnum.HEADING if label == DocItemLabel.SECTION_HEADER else ElementTypeEnum.TEXT
    )
    return {
        "element_type": element_type,
        "label": label.value,
        "content": text,
        "table_markdown": None,
        "metadata": base_meta,
    }


def _process_table_element(doc, ref: str, text: str, base_meta: dict) -> dict:
    """Formats a table element, extracting markdown if possible."""
    table_md = None
    tbl = {t.self_ref: t for t in doc.tables}.get(ref)
    if tbl:
        try:
            df = tbl.export_to_dataframe(doc=doc)
            table_md = df.to_markdown(index=False) if df is not None else None
        except Exception as e:
            logger.warning(f"Table export failed {ref}: {e}")

    return {
        "element_type": ElementTypeEnum.TABLE,
        "label": "table",
        "content": table_md or text,
        "table_markdown": table_md,
        "metadata": base_meta,
    }


def _process_picture_element(item, text: str, base_meta: dict) -> dict:
    """Formats a picture element, prioritizing annotation text for description."""
    desc = next(
        (a.text for a in (getattr(item, "annotations", []) or []) if getattr(a, "text", "")),
        text,
    )
    return {
        "element_type": ElementTypeEnum.FIGURE,
        "label": "picture",
        "content": desc,
        "table_markdown": None,
        "metadata": base_meta,
    }


def export_raw_elements(doc, company: str, year: int, source: str) -> list[dict]:
    """
    Export raw elements extracted by Docling into a structured dictionary format.
    Iterates over all parsed document items, extracting text, tables, and images.
    """
    records = []

    for item, _ in doc.iterate_items():
        label = getattr(item, "label", None)
        text = getattr(item, "text", "") or ""
        ref = getattr(item, "self_ref", "")
        prov = getattr(item, "prov", [])

        page, pages = _extract_pages(prov)
        bbox = _extract_bbox(prov)

        base_meta = {
            "source": source,
            "company": company,
            "year": year,
            "doc_ref": ref,
            "page": page,
            "pages": pages,
            "bbox": bbox,
        }

        if label in (
            DocItemLabel.TEXT,
            DocItemLabel.PARAGRAPH,
            DocItemLabel.SECTION_HEADER,
            DocItemLabel.TITLE,
            DocItemLabel.CAPTION,
            DocItemLabel.FOOTNOTE,
        ):
            records.append(_process_text_element(label, text, base_meta))

        elif label == DocItemLabel.TABLE:
            records.append(_process_table_element(doc, ref, text, base_meta))

        elif label == DocItemLabel.PICTURE:
            records.append(_process_picture_element(item, text, base_meta))

    page_contents: dict[int, list[str]] = defaultdict(list)
    for r in records:
        p = r["metadata"]["page"]
        c = r["content"]
        if p and c and c.strip():
            page_contents[p].append(c.strip())

    for r in records:
        p = r["metadata"]["page"]
        r["full_content"] = "\n\n".join(page_contents.get(p, []))

    logger.info(f"Exported {len(records)} elements from doc ({len(page_contents)} pages)")
    return records
