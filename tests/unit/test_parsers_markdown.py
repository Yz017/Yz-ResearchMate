from __future__ import annotations

from pathlib import Path

from researchmate.services.parsers import parse_document_to_chunks


def test_markdown_headings_become_sections(tmp_path: Path) -> None:
    path = tmp_path / "paper.md"
    path.write_text(
        "# ResearchMate Notes\n\nIntro text.\n\n## Methods\n\nGrounded citations use chunks.",
        encoding="utf-8",
    )

    chunks = parse_document_to_chunks(path, paper_id="md_note", target_tokens=64)

    assert chunks
    assert chunks[-1].section == "Methods"
    assert chunks[-1].citation == "[source: md_note · Methods]"


def test_markdown_fenced_code_does_not_become_heading(tmp_path: Path) -> None:
    path = tmp_path / "code.md"
    path.write_text(
        "## Methods\n\n```python\n# Results\nprint('x')\n```\n\nBody text.", encoding="utf-8"
    )

    chunks = parse_document_to_chunks(path, paper_id="code_note", target_tokens=64)

    assert chunks
    assert all(chunk.section == "Methods" for chunk in chunks)
    assert "# Results" in " ".join(chunk.text for chunk in chunks)


def test_markdown_preserves_list_and_paragraph_order(tmp_path: Path) -> None:
    path = tmp_path / "order.md"
    path.write_text(
        "## Plan\n\nFirst paragraph.\n\n- item one\n- item two\n\nLast paragraph.", encoding="utf-8"
    )

    text = " ".join(chunk.text for chunk in parse_document_to_chunks(path, target_tokens=64))

    assert text.index("First paragraph") < text.index("item one") < text.index("Last paragraph")
