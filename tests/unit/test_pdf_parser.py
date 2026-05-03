from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from researchmate.services.pdf_parser import parse_pdf_to_chunks


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_text_pdf(path: Path, lines: list[str]) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    commands = ["BT", "/F1 12 Tf", "72 720 Td"]
    for index, line in enumerate(lines):
        if index:
            commands.append("0 -18 Td")
        commands.append(f"({_escape_pdf_text(line)}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("utf-8"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as file:
        writer.write(file)


def test_parse_pdf_to_chunks_extracts_text_and_metadata(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample_rag.pdf"
    _write_text_pdf(
        pdf_path,
        [
            "ResearchMate Sample Paper",
            "Methods",
            "The method uses retrieval augmented generation with grounded citation answers.",
            "Results show the assistant can cite local PDF pages during question answering.",
        ],
    )

    chunks = parse_pdf_to_chunks(
        pdf_path,
        paper_id="paper_X",
        title="ResearchMate Sample Paper",
        target_tokens=64,
        max_tokens=96,
    )

    assert chunks
    assert chunks[0].paper_id == "paper_X"
    assert chunks[0].page == 1
    assert chunks[0].citation == "[source: paper_X, p.1]"
    joined = " ".join(chunk.text for chunk in chunks).lower()
    assert "retrieval augmented generation" in joined
    assert "grounded citation" in joined
