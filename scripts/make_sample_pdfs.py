from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "examples" / "pdfs"

SAMPLES = {
    "rag_basics.pdf": [
        "ResearchMate RAG Basics",
        "Methods",
        "A local retrieval augmented generation system first parses PDF pages into chunks.",
        "The retriever combines dense vectors with lexical matching and returns citation metadata.",
        "Results",
        "Grounded answers must cite the source paper id and page number.",
    ],
    "memory_notes.pdf": [
        "ResearchMate Memory Notes",
        "Introduction",
        (
            "A research assistant should remember research direction, advisor "
            "requirements, and writing style."
        ),
        "Methods",
        "Long term memory records should include timestamps and categories for later retrieval.",
    ],
    "weekly_report.pdf": [
        "ResearchMate Weekly Report Example",
        "Abstract",
        (
            "Weekly reports summarize papers read, open questions, experiment progress, "
            "and next tasks."
        ),
        "Conclusion",
        "The writer should synthesize evidence from local notes and cite each supporting source.",
    ],
}


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_text_pdf(path: Path, lines: list[str]) -> None:
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lines in SAMPLES.items():
        path = OUTPUT_DIR / filename
        write_text_pdf(path, lines)
        print(path)


if __name__ == "__main__":
    main()
