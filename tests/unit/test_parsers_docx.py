from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from researchmate.services.parsers import parse_document_to_chunks


def _write_docx(path: Path) -> None:
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading1"/></w:pPr>
      <w:r><w:t>Methods</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>DOCX body text is extracted for chunking.</w:t></w:r>
    </w:p>
    <w:p>
      <w:pPr><w:pStyle w:val="Heading2"/></w:pPr>
      <w:r><w:t>Results</w:t></w:r>
    </w:p>
    <w:p>
      <w:r><w:t>Heading 2 sections are also tracked.</w:t></w:r>
    </w:p>
  </w:body>
</w:document>
"""
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override
    PartName="/word/document.xml"
    ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
  />
</Types>
""",
        )
        archive.writestr("word/document.xml", document_xml)


def test_docx_headings_and_body_parse_to_chunks(tmp_path: Path) -> None:
    path = tmp_path / "sample.docx"
    _write_docx(path)

    chunks = parse_document_to_chunks(path, paper_id="docx_note", target_tokens=16, max_tokens=64)

    assert chunks
    assert {chunk.section for chunk in chunks} == {"Methods", "Results"}
    assert "DOCX body text" in " ".join(chunk.text for chunk in chunks)
