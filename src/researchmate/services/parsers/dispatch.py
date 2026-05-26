from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from researchmate.services.documents import KnowledgeChunk, ParsedPage
from researchmate.services.parsers import SUPPORTED_EXTENSIONS, UnsupportedFormatError, base, pdf
from researchmate.services.parsers import docx as docx_parser
from researchmate.services.parsers import html as html_parser
from researchmate.services.parsers import markdown as markdown_parser
from researchmate.services.parsers import txt as txt_parser

Extractor = Callable[[str | Path], list[ParsedPage]]

_EXTRACTORS: dict[str, Extractor] = {
    ".pdf": pdf.extract_pages,
    ".txt": txt_parser.extract_pages,
    ".md": markdown_parser.extract_pages,
    ".markdown": markdown_parser.extract_pages,
    ".docx": docx_parser.extract_pages,
    ".html": html_parser.extract_pages,
    ".htm": html_parser.extract_pages,
}


def parse_document_to_chunks(
    path: str | Path,
    *,
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
    suffix = document_path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        msg = f"Unsupported document format '{suffix or '<none>'}'; supported: {supported}"
        raise UnsupportedFormatError(msg)

    extractor = _EXTRACTORS[suffix]
    pages = extractor(document_path)
    return base.build_chunks_from_pages(
        pages,
        path=document_path,
        paper_id=paper_id,
        title=title,
        oss_key=oss_key,
        user_id=user_id,
        tags=tags,
        ingested_at=ingested_at,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
    )
