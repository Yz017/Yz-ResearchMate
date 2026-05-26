from __future__ import annotations

import importlib
from pathlib import Path

from researchmate.services.documents import ParsedPage, normalize_text


class PdfParseError(RuntimeError):
    """Raised when no usable text can be extracted from a PDF."""


def extract_pages(path: str | Path) -> list[ParsedPage]:
    pdf_path = Path(path)
    if not pdf_path.exists():
        msg = f"PDF not found: {pdf_path}"
        raise FileNotFoundError(msg)
    if pdf_path.suffix.lower() != ".pdf":
        msg = f"Expected a .pdf file: {pdf_path}"
        raise ValueError(msg)

    pages = _extract_with_pdfplumber(pdf_path)
    if not any(page.text.strip() for page in pages):
        pages = _extract_with_pypdf(pdf_path)
    pages = [ParsedPage(page.page_number, page.text.strip()) for page in pages]
    pages = [page for page in pages if normalize_text(page.text)]
    if not pages:
        msg = f"No extractable text found in {pdf_path}. Scanned PDFs need OCR before ingest."
        raise PdfParseError(msg)
    return pages


def _extract_with_pdfplumber(path: Path) -> list[ParsedPage]:
    try:
        pdfplumber = importlib.import_module("pdfplumber")
        pages: list[ParsedPage] = []
        with pdfplumber.open(str(path)) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
                pages.append(ParsedPage(page_number=index, text=text))
        return pages
    except Exception:
        return []


def _extract_with_pypdf(path: Path) -> list[ParsedPage]:
    pypdf = importlib.import_module("pypdf")
    reader = pypdf.PdfReader(str(path))
    pages: list[ParsedPage] = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        pages.append(ParsedPage(page_number=index, text=text))
    return pages


extract_pdf_pages = extract_pages
