from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from researchmate.config import Settings
from researchmate.services.documents import ParsedPage
from researchmate.services.parsers import base
from researchmate.services.parsers import pdf as pdf_parser


def _settings(
    *,
    ingest_ocr_enabled: bool = True,
    ocr_max_pages: int = 10,
) -> Settings:
    return Settings(
        RESEARCH_AGENT_TOKEN=SecretStr("x" * 32),
        INGEST_OCR_ENABLED=ingest_ocr_enabled,
        OCR_MIN_CHARS=10,
        OCR_GOOD_CHARS=25,
        OCR_LANGUAGES="eng",
        OCR_DPI=150,
        OCR_MAX_PAGES=ocr_max_pages,
    )


def _touch_pdf(path: Path) -> Path:
    path.write_bytes(b"%PDF-1.4\n")
    return path


def test_ocr_fallback_replaces_appends_and_skips_by_text_length(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    def fake_ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
        calls.append(page_number)
        return {
            1: "low OCR replacement text",
            2: "OCR supplement text",
        }[page_number]

    monkeypatch.setattr(pdf_parser, "_ocr_page", fake_ocr_page)
    pages = [
        ParsedPage(page_number=1, text="tiny"),
        ParsedPage(page_number=2, text="middle text"),
        ParsedPage(page_number=3, text="This page already has enough extracted text."),
    ]

    result = pdf_parser._apply_ocr_fallback(pages, tmp_path / "sample.pdf", _settings())

    assert calls == [1, 2]
    assert result[0] == ParsedPage(page_number=1, text="low OCR replacement text", ocr=True)
    assert result[1].ocr is True
    assert result[1].text == "middle text\n\nOCR supplement text"
    assert result[2] == pages[2]


def test_ocr_fallback_stops_after_max_pages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[int] = []

    def fake_ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
        calls.append(page_number)
        return f"ocr page {page_number}"

    monkeypatch.setattr(pdf_parser, "_ocr_page", fake_ocr_page)
    pages = [
        ParsedPage(page_number=1, text=""),
        ParsedPage(page_number=2, text=""),
    ]

    result = pdf_parser._apply_ocr_fallback(
        pages,
        tmp_path / "sample.pdf",
        _settings(ocr_max_pages=1),
    )

    assert calls == [1]
    assert result[0].ocr is True
    assert result[1] == pages[1]


def test_extract_pages_reraises_ocr_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_extract(path: Path) -> list[ParsedPage]:
        return [ParsedPage(page_number=1, text="")]

    def fake_ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
        raise pdf_parser.OcrDependencyError("install OCR runtime")

    monkeypatch.setattr(pdf_parser, "_extract_with_pdfplumber", fake_extract)
    monkeypatch.setattr(pdf_parser, "_extract_with_pypdf", fake_extract)
    monkeypatch.setattr(pdf_parser, "_ocr_page", fake_ocr_page)

    with pytest.raises(pdf_parser.OcrDependencyError, match="install OCR runtime"):
        pdf_parser.extract_pages(_touch_pdf(tmp_path / "scan.pdf"), settings=_settings())


def test_extract_pages_keeps_going_when_one_page_ocr_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_extract(path: Path) -> list[ParsedPage]:
        return [
            ParsedPage(page_number=1, text=""),
            ParsedPage(page_number=2, text=""),
        ]

    def fake_ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
        if page_number == 1:
            raise RuntimeError("bad page")
        return "second page OCR text"

    monkeypatch.setattr(pdf_parser, "_extract_with_pdfplumber", fake_extract)
    monkeypatch.setattr(pdf_parser, "_extract_with_pypdf", fake_extract)
    monkeypatch.setattr(pdf_parser, "_ocr_page", fake_ocr_page)

    pages = pdf_parser.extract_pages(_touch_pdf(tmp_path / "scan.pdf"), settings=_settings())

    assert pages == [ParsedPage(page_number=2, text="second page OCR text", ocr=True)]


def test_extract_pages_raises_when_ocr_produces_no_text(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    def fake_extract(path: Path) -> list[ParsedPage]:
        return [ParsedPage(page_number=1, text="")]

    def fake_ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
        return "   "

    monkeypatch.setattr(pdf_parser, "_extract_with_pdfplumber", fake_extract)
    monkeypatch.setattr(pdf_parser, "_extract_with_pypdf", fake_extract)
    monkeypatch.setattr(pdf_parser, "_ocr_page", fake_ocr_page)

    with pytest.raises(pdf_parser.PdfParseError, match="OCR produced no usable text"):
        pdf_parser.extract_pages(_touch_pdf(tmp_path / "scan.pdf"), settings=_settings())


def test_extract_pages_does_not_call_ocr_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called = False

    def fake_extract(path: Path) -> list[ParsedPage]:
        return [ParsedPage(page_number=1, text="")]

    def fake_ocr_page(pdf_path: Path, page_number: int, settings: Settings) -> str:
        nonlocal called
        called = True
        return "unexpected"

    monkeypatch.setattr(pdf_parser, "_extract_with_pdfplumber", fake_extract)
    monkeypatch.setattr(pdf_parser, "_extract_with_pypdf", fake_extract)
    monkeypatch.setattr(pdf_parser, "_ocr_page", fake_ocr_page)

    with pytest.raises(pdf_parser.PdfParseError, match="Scanned PDFs need OCR before ingest"):
        pdf_parser.extract_pages(
            _touch_pdf(tmp_path / "scan.pdf"),
            settings=_settings(ingest_ocr_enabled=False),
        )

    assert called is False


def test_ocr_flag_is_passed_to_chunk_metadata(tmp_path: Path) -> None:
    chunks = base.build_chunks_from_pages(
        [ParsedPage(page_number=3, text="Methods\nOCR derived body text.", ocr=True)],
        path=tmp_path / "paper.pdf",
        paper_id="paper",
        title="Paper",
        target_tokens=64,
        max_tokens=96,
    )

    assert chunks
    assert chunks[0].ocr is True
    assert chunks[0].metadata()["ocr"] is True
