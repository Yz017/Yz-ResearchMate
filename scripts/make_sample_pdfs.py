from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

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

IMAGE_SAMPLE_LINES = [
    "ResearchMate OCR Image Page",
    "This sentence is rasterized into an image.",
    "OCR ingest should recover these words from page 1.",
]


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


def write_image_pdf(path: Path, lines: list[str]) -> None:
    image = _render_text_image(lines)
    width, height = image.size

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    image_stream = DecodedStreamObject()
    image_stream.set_data(image.tobytes())
    image_stream.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(width),
            NameObject("/Height"): NumberObject(height),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    image_ref = writer._add_object(image_stream)
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/XObject"): DictionaryObject({NameObject("/Im1"): image_ref})}
    )

    target_width = 468
    target_height = int(target_width * height / width)
    commands = [f"q {target_width} 0 0 {target_height} 72 520 cm /Im1 Do Q"]
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("utf-8"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as file:
        writer.write(file)


def _render_text_image(lines: list[str]) -> Any:
    image_module = importlib.import_module("PIL.Image")
    image_draw = importlib.import_module("PIL.ImageDraw")
    image_font = importlib.import_module("PIL.ImageFont")

    image = image_module.new("RGB", (1200, 420), "white")
    draw = image_draw.Draw(image)
    try:
        title_font = image_font.truetype("DejaVuSans.ttf", 52)
        body_font = image_font.truetype("DejaVuSans.ttf", 38)
    except OSError:
        title_font = image_font.load_default()
        body_font = image_font.load_default()

    y = 58
    for index, line in enumerate(lines):
        font = title_font if index == 0 else body_font
        draw.text((72, y), line, fill="black", font=font)
        y += 86 if index == 0 else 64
    return image


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, lines in SAMPLES.items():
        path = OUTPUT_DIR / filename
        write_text_pdf(path, lines)
        print(path)
    image_path = OUTPUT_DIR / "ocr_image_page.pdf"
    write_image_pdf(image_path, IMAGE_SAMPLE_LINES)
    print(image_path)


if __name__ == "__main__":
    main()
