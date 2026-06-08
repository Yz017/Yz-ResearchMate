from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from researchmate.services.documents import (
    KnowledgeChunk,
    ParsedPage,
    infer_paper_id,
    normalize_text,
)
from researchmate.services.embeddings import estimate_token_count

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
SECTION_HEADING_RE = re.compile(
    r"^(?:#{1,6}\s+)?(?:\d+(?:\.\d+)*\s+)?(?:abstract|introduction|background|method|methods|"
    r"methodology|experiment|experiments|evaluation|results|discussion|conclusion|"
    r"related work|摘要|引言|方法|实验|结果|讨论|结论|相关工作)\b",
    re.IGNORECASE,
)
MARKED_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$")


def build_chunks_from_pages(
    pages: Sequence[ParsedPage],
    *,
    path: str | Path,
    paper_id: str | None = None,
    title: str | None = None,
    oss_key: str = "",
    user_id: str = "",
    tags: Sequence[str] | None = None,
    ingested_at: str = "",
    target_tokens: int = 768,
    max_tokens: int = 1024,
) -> list[KnowledgeChunk]:
    document_path = Path(path)
    resolved_paper_id = paper_id or infer_paper_id(document_path)
    resolved_title = title or infer_title(list(pages), document_path.stem)
    chunks: list[KnowledgeChunk] = []
    current_section = "unknown"
    for page in pages:
        page_chunks, current_section = chunk_page(
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
                    source_path=str(document_path),
                    oss_key=oss_key,
                    chunk_index=len(chunks),
                    ocr=page.ocr,
                    owner_user_id=user_id,
                    tags=tuple(tags or ()),
                    ingested_at=ingested_at,
                )
            )
    return chunks


def infer_title(pages: list[ParsedPage], fallback: str) -> str:
    if not pages:
        return fallback
    for line in pages[0].text.splitlines():
        stripped = normalize_text(line)
        if stripped:
            return stripped[:200]
    return fallback


def chunk_page(
    page: ParsedPage,
    *,
    current_section: str,
    target_tokens: int,
    max_tokens: int,
) -> tuple[list[tuple[str, str]], str]:
    paragraphs = list(iter_paragraphs(page.text))
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
        detected = detect_section(paragraph)
        if detected:
            if buffer:
                flush()
            section = detected
            continue
        paragraph_tokens = estimate_token_count(paragraph)
        if paragraph_tokens > max_tokens:
            if buffer:
                flush()
            for text in split_long_paragraph(paragraph, max_tokens=max_tokens):
                output.append((text, section))
            continue
        if buffer and buffer_tokens + paragraph_tokens > target_tokens:
            flush()
        buffer.append(paragraph)
        buffer_tokens += paragraph_tokens
    if buffer:
        flush()
    return output, section


def iter_paragraphs(text: str) -> Iterable[str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = PARAGRAPH_SPLIT_RE.split(normalized)
    if len(paragraphs) == 1:
        paragraphs = normalized.split("\n")
    for paragraph in paragraphs:
        paragraph = normalize_text(paragraph)
        if paragraph:
            yield paragraph


def split_long_paragraph(paragraph: str, *, max_tokens: int) -> list[str]:
    sentences = [normalize_text(sentence) for sentence in SENTENCE_SPLIT_RE.split(paragraph)]
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
            chunks.extend(split_by_words(sentence, max_tokens=max_tokens))
            continue
        buffer.append(sentence)
        buffer_tokens += sentence_tokens
    if buffer:
        chunks.append(normalize_text(" ".join(buffer)))
    return chunks


def split_by_words(text: str, *, max_tokens: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    for start in range(0, len(words), max_tokens):
        chunks.append(normalize_text(" ".join(words[start : start + max_tokens])))
    return [chunk for chunk in chunks if chunk]


def detect_section(paragraph: str) -> str | None:
    stripped = paragraph.strip()
    if len(stripped) > 96:
        return None
    marked = MARKED_HEADING_RE.match(stripped)
    if marked:
        title = normalize_text(marked.group(1))
        return title or None
    match = SECTION_HEADING_RE.match(stripped)
    if match:
        remainder = stripped[match.end() :].strip()
        if not remainder or not normalize_text(remainder).strip(":-：.。()[]{}"):
            return stripped
    letters = [char for char in stripped if char.isalpha()]
    if (
        letters
        and all(char.isascii() for char in letters)
        and stripped.isupper()
        and 4 <= len(stripped) <= 64
    ):
        return stripped.title()
    return None
