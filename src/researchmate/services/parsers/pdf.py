from __future__ import annotations

import importlib
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from loguru import logger

from researchmate.config import Settings, get_settings
from researchmate.services.documents import ParsedPage, normalize_text

_OCR_ENV_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on"}
_OCR_SETUP_HINT = (
    "OCR ingest requires optional dependencies and the Tesseract engine. "
    "Run `uv sync --extra ocr`, install Tesseract with chi_sim/eng language data, "
    "and set TESSERACT_CMD if the executable is not on PATH."
)


class PdfParseError(RuntimeError):
    """Raised when no usable text can be extracted from a PDF."""


class OcrDependencyError(RuntimeError):
    """Raised when OCR is enabled but required OCR runtime pieces are unavailable."""


def extract_pages(path: str | Path, *, settings: Settings | None = None) -> list[ParsedPage]:
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
    ocr_settings = _resolve_ocr_settings(settings)
    if ocr_settings is not None:
        pages = _apply_ocr_fallback(pages, pdf_path, ocr_settings)
    pages = [ParsedPage(page.page_number, page.text.strip(), ocr=page.ocr) for page in pages]
    pages = [page for page in pages if normalize_text(page.text)]
    if not pages:
        if ocr_settings is None:
            msg = f"No extractable text found in {pdf_path}. Scanned PDFs need OCR before ingest."
        else:
            msg = f"No extractable text found in {pdf_path}. OCR produced no usable text."
        raise PdfParseError(msg)
    return pages


def _resolve_ocr_settings(settings: Settings | None) -> Settings | None:
    if settings is not None:
        return settings if settings.ingest_ocr_enabled else None
    load_dotenv(override=False)
    enabled = os.getenv("INGEST_OCR_ENABLED", "").strip().lower() in _OCR_ENV_TRUE_VALUES
    if not enabled:
        return None
    return get_settings()


def _apply_ocr_fallback(
    pages: list[ParsedPage],
    pdf_path: Path,
    settings: Settings,
) -> list[ParsedPage]:
    output: list[ParsedPage] = []
    attempted_pages = 0
    max_pages_warning_emitted = False
    for page in pages:
        normalized_text = normalize_text(page.text)
        text_length = len(normalized_text)
        if text_length >= settings.ocr_good_chars:
            output.append(page)
            continue

        if attempted_pages >= settings.ocr_max_pages:
            if not max_pages_warning_emitted:
                logger.warning(
                    "OCR page limit reached for {}: attempted {} pages; remaining pages keep "
                    "parser text only",
                    pdf_path,
                    settings.ocr_max_pages,
                )
                max_pages_warning_emitted = True
            output.append(page)
            continue

        mode = "replace" if text_length < settings.ocr_min_chars else "append"
        attempted_pages += 1
        try:
            ocr_text = _ocr_page(pdf_path, page.page_number, settings)
        except OcrDependencyError:
            raise
        except Exception as exc:
            logger.warning(
                "OCR failed for {} page {}: {}",
                pdf_path,
                page.page_number,
                exc,
            )
            output.append(page)
            continue

        normalized_ocr_text = normalize_text(ocr_text)
        if not normalized_ocr_text:
            logger.warning("OCR returned no text for {} page {}", pdf_path, page.page_number)
            output.append(page)
            continue

        if mode == "replace":
            next_text = normalized_ocr_text
        else:
            next_text = _merge_text(page.text, normalized_ocr_text)
        logger.info("OCR {} applied to {} page {}", mode, pdf_path, page.page_number)
        output.append(ParsedPage(page_number=page.page_number, text=next_text, ocr=True))

    ocr_pages = sum(1 for page in output if page.ocr)
    if ocr_pages:
        logger.info(
            "OCR summary for {}: {}/{} pages used OCR text",
            pdf_path,
            ocr_pages,
            len(output),
        )
    return output


def _merge_text(original: str, ocr_text: str) -> str:
    original_text = original.strip()
    normalized_original = normalize_text(original_text)
    normalized_ocr = normalize_text(ocr_text)
    if not normalized_original:
        return normalized_ocr
    if not normalized_ocr:
        return original_text
    if normalized_ocr in normalized_original:
        return original_text
    if normalized_original in normalized_ocr:
        return normalized_ocr
    return f"{original_text}\n\n{normalized_ocr}"


def _ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
    fitz = _import_fitz()
    pytesseract = _import_pytesseract()
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd
    with fitz.open(str(pdf_path)) as doc:
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=settings.ocr_dpi, colorspace=fitz.csGRAY)
        image = _pixmap_to_pil(pix)
    try:
        text = pytesseract.image_to_string(image, lang=settings.ocr_languages)
    except Exception as exc:
        if _is_tesseract_runtime_error(exc):
            raise OcrDependencyError(_OCR_SETUP_HINT) from exc
        raise
    return normalize_text(str(text))


def _import_fitz() -> Any:
    try:
        return importlib.import_module("fitz")
    except ImportError as exc:
        raise OcrDependencyError(_OCR_SETUP_HINT) from exc


def _import_pytesseract() -> Any:
    try:
        return importlib.import_module("pytesseract")
    except ImportError as exc:
        raise OcrDependencyError(_OCR_SETUP_HINT) from exc


def _pixmap_to_pil(pix: Any) -> Any:
    try:
        image_module = importlib.import_module("PIL.Image")
    except ImportError as exc:
        raise OcrDependencyError(_OCR_SETUP_HINT) from exc
    with BytesIO(pix.tobytes("png")) as buffer:
        image = image_module.open(buffer)
        return image.copy()


def _is_tesseract_runtime_error(exc: Exception) -> bool:
    if exc.__class__.__name__ == "TesseractNotFoundError":
        return True
    message = str(exc)
    return any(
        marker in message
        for marker in (
            "Error opening data file",
            "Failed loading language",
            "Tesseract couldn't load any languages",
        )
    )


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
