from __future__ import annotations

import importlib
import re
from collections.abc import Iterable
from pathlib import Path

from researchmate.services.documents import (
    KnowledgeChunk,
    ParsedPage,
    infer_paper_id,
    normalize_text,
)
from researchmate.services.embeddings import estimate_token_count

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
_SECTION_HEADING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*\s+)?(?:abstract|introduction|background|method|methods|"
    r"methodology|experiment|experiments|evaluation|results|discussion|conclusion|"
    r"related work|摘要|引言|方法|实验|结果|讨论|结论|相关工作)\b",
    re.IGNORECASE,
)


class PdfParseError(RuntimeError):
    """Raised when no usable text can be extracted from a PDF."""


def extract_pdf_pages(path: str | Path) -> list[ParsedPage]:
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


def parse_pdf_to_chunks(
    path: str | Path,
    *,
    paper_id: str | None = None,
    title: str | None = None,
    oss_key: str = "",
    target_tokens: int = 768,
    max_tokens: int = 1024,
) -> list[KnowledgeChunk]:
    pdf_path = Path(path)
    resolved_paper_id = paper_id or infer_paper_id(pdf_path)
    pages = extract_pdf_pages(pdf_path)
    resolved_title = title or _infer_title(pages, pdf_path.stem)
    chunks: list[KnowledgeChunk] = []
    current_section = "unknown"
    for page in pages:
        page_chunks, current_section = _chunk_page(
            page,
            current_section=current_section,
            target_tokens=target_tokens,
            max_tokens=max_tokens,
        )
        for text, section in page_chunks:
            chunks.append(
                KnowledgeChunk.create(
                    text=text,
                    paper_id=resolved_paper_id,
                    title=resolved_title,
                    page=page.page_number,
                    section=section,
                    source_path=str(pdf_path),
                    oss_key=oss_key,
                    chunk_index=len(chunks),
                )
            )
    return chunks


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


def _infer_title(pages: list[ParsedPage], fallback: str) -> str:
    if not pages:
        return fallback
    for line in pages[0].text.splitlines():
        stripped = normalize_text(line)
        if stripped:
            return stripped[:200]
    return fallback


def _chunk_page(
    page: ParsedPage,
    *,
    current_section: str,
    target_tokens: int,
    max_tokens: int,
) -> tuple[list[tuple[str, str]], str]:
    paragraphs = list(_iter_paragraphs(page.text))
    output: list[tuple[str, str]] = []
    buffer: list[str] = []
    buffer_tokens = 0
    section = current_section

    def flush() -> None:
        nonlocal buffer, buffer_tokens
        text = normalize_text("\n\n".join(buffer))
        if text:
            output.append((text, section))
        buffer = []
        buffer_tokens = 0

    for paragraph in paragraphs:
        detected = _detect_section(paragraph)
        if detected:
            if buffer:
                flush()
            section = detected
            continue
        paragraph_tokens = estimate_token_count(paragraph)
        if paragraph_tokens > max_tokens:
            if buffer:
                flush()
            for text in _split_long_paragraph(paragraph, max_tokens=max_tokens):
                output.append((text, section))
            continue
        if buffer and buffer_tokens + paragraph_tokens > target_tokens:
            flush()
        buffer.append(paragraph)
        buffer_tokens += paragraph_tokens
    if buffer:
        flush()
    return output, section


def _iter_paragraphs(text: str) -> Iterable[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = _PARAGRAPH_SPLIT_RE.split(normalized)
    if len(paragraphs) == 1:
        paragraphs = normalized.split("\n")
    for paragraph in paragraphs:
        paragraph = normalize_text(paragraph)
        if paragraph:
            yield paragraph


def _split_long_paragraph(paragraph: str, *, max_tokens: int) -> list[str]:
    sentences = [normalize_text(sentence) for sentence in _SENTENCE_SPLIT_RE.split(paragraph)]
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_tokens = 0
    for sentence in sentences:
        if not sentence:
            continue
        sentence_tokens = estimate_token_count(sentence)
        if buffer and buffer_tokens + sentence_tokens > max_tokens:
            chunks.append(normalize_text(" ".join(buffer)))
            buffer = []
            buffer_tokens = 0
        if sentence_tokens > max_tokens:
            chunks.extend(_split_by_words(sentence, max_tokens=max_tokens))
            continue
        buffer.append(sentence)
        buffer_tokens += sentence_tokens
    if buffer:
        chunks.append(normalize_text(" ".join(buffer)))
    return chunks


def _split_by_words(text: str, *, max_tokens: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    for start in range(0, len(words), max_tokens):
        chunks.append(normalize_text(" ".join(words[start : start + max_tokens])))
    return [chunk for chunk in chunks if chunk]


def _detect_section(paragraph: str) -> str | None:
    stripped = paragraph.strip()
    if len(stripped) > 96:
        return None
    match = _SECTION_HEADING_RE.match(stripped)
    if match:
        return stripped
    if stripped.isupper() and 4 <= len(stripped) <= 64:
        return stripped.title()
    return None
