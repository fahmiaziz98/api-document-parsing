import hashlib
from collections import defaultdict

from docling_core.types.doc.labels import DocItemLabel
from loguru import logger

from src.models.response import ElementTypeEnum


def _make_element_id(source: str, doc_ref: str, element_type: str, content: str) -> str:
    """
    Generate a deterministic SHA-256 id for an element.

    The hash is computed from the stable tuple (source, doc_ref, element_type, content)
    so the same document content always produces the same id, enabling deduplication.

    Args:
        source: Original filename of the document.
        doc_ref: Internal document reference string from the parser.
        element_type: Semantic type of the element (text, heading, table, figure).
        content: Extracted text or table markdown content.

    Returns:
        Hex-encoded SHA-256 digest (64 characters).
    """
    raw = f"{source}|{doc_ref}|{element_type}|{content}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def export_raw_elements(doc, metadata: dict, source: str) -> list[dict]:
    """
    Export raw elements extracted by Docling into a structured dictionary format.
    Iterates over all parsed document items, extracting text, tables, and images.

    Args:
        doc: Docling document object
        metadata: Arbitrary user-supplied metadata dict (e.g. company, year, label, type…)
        source: Original filename of the document
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
            "doc_ref": ref,
            "page": page,
            "pages": pages,
            "bbox": bbox,
            **metadata,  # spread all user-supplied metadata fields
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
        # Inject a deterministic id as the first field of each element.
        element_id = _make_element_id(
            source=r["metadata"]["source"],
            doc_ref=r["metadata"]["doc_ref"],
            element_type=r["element_type"],
            content=r["content"],
        )
        r["id"] = element_id
        # Re-order so id comes first for readability.
        ordered = {"id": r.pop("id"), **r}
        records[records.index(r)] = ordered

    logger.info(f"Exported {len(records)} elements from doc ({len(page_contents)} pages)")
    return records
