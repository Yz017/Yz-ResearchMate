from __future__ import annotations

SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".pdf", ".txt", ".md", ".markdown", ".docx", ".html", ".htm"}
)


class UnsupportedFormatError(ValueError):
    """Raised when a document suffix has no registered parser."""


def parse_document_to_chunks(*args: object, **kwargs: object):
    from researchmate.services.parsers.dispatch import parse_document_to_chunks as _parse

    return _parse(*args, **kwargs)

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "UnsupportedFormatError",
    "parse_document_to_chunks",
]
