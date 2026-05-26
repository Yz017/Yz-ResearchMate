from __future__ import annotations

# Compatibility shim for older imports while the parser stack moves to parsers/.
from researchmate.services.parsers.dispatch import parse_document_to_chunks as parse_pdf_to_chunks
from researchmate.services.parsers.pdf import PdfParseError
from researchmate.services.parsers.pdf import extract_pages as extract_pdf_pages

__all__ = ["PdfParseError", "extract_pdf_pages", "parse_pdf_to_chunks"]
