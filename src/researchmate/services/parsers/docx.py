from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from researchmate.services.documents import ParsedPage, normalize_text

_DOCX_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W_BODY = f"{{{_DOCX_NS}}}body"
_W_P = f"{{{_DOCX_NS}}}p"
_W_T = f"{{{_DOCX_NS}}}t"
_W_TAB = f"{{{_DOCX_NS}}}tab"
_W_BR = f"{{{_DOCX_NS}}}br"
_W_PPR = f"{{{_DOCX_NS}}}pPr"
_W_PSTYLE = f"{{{_DOCX_NS}}}pStyle"


def extract_pages(path: str | Path) -> list[ParsedPage]:
    docx_path = Path(path)
    if not docx_path.exists():
        msg = f"document not found: {docx_path}"
        raise FileNotFoundError(msg)
    try:
        with ZipFile(docx_path) as archive:
            document_xml = archive.read("word/document.xml")
    except (BadZipFile, KeyError, FileNotFoundError) as exc:
        msg = f"Invalid DOCX file: {docx_path}"
        raise ValueError(msg) from exc

    root = ET.fromstring(document_xml)
    body = root.find(_W_BODY)
    if body is None:
        msg = f"No extractable text found in {docx_path}"
        raise ValueError(msg)

    lines: list[str] = []
    for child in list(body):
        if child.tag != _W_P:
            continue
        text = _paragraph_text(child)
        if not normalize_text(text):
            continue
        heading = _paragraph_heading(child)
        if heading is not None:
            lines.append(f"{'#' * heading[0]} {heading[1]}")
        else:
            lines.append(text)

    content = "\n\n".join(lines)
    if not normalize_text(content):
        msg = f"No extractable text found in {docx_path}"
        raise ValueError(msg)
    return [ParsedPage(page_number=1, text=content)]


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == _W_T and node.text:
            parts.append(node.text)
        elif node.tag == _W_TAB:
            parts.append("\t")
        elif node.tag == _W_BR:
            parts.append("\n")
    return normalize_text("".join(parts))


def _paragraph_heading(paragraph: ET.Element) -> tuple[int, str] | None:
    style = paragraph.find(f"./{_W_PPR}/{_W_PSTYLE}")
    if style is None:
        return None
    style_id = str(style.attrib.get(f"{{{_DOCX_NS}}}val", ""))
    if not style_id.startswith("Heading"):
        return None
    level = _heading_level(style_id)
    text = _paragraph_text(paragraph)
    if not text:
        return None
    return level, text


def _heading_level(style_id: str) -> int:
    digits = "".join(ch for ch in style_id if ch.isdigit())
    if digits:
        try:
            return max(int(digits), 1)
        except ValueError:
            return 1
    return 1
