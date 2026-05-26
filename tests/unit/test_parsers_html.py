from __future__ import annotations

from pathlib import Path

import pytest

from researchmate.services.parsers import html as html_parser
from researchmate.services.parsers import parse_document_to_chunks


def test_html_strips_script_style_and_tracks_sections(tmp_path: Path) -> None:
    path = tmp_path / "sample.html"
    path.write_text(
        """
        <html><body>
          <header>Navigation</header>
          <h1>Methods</h1>
          <p>Visible method text.</p>
          <script>secretScript()</script>
          <style>.hidden { color: red; }</style>
          <h3>Results</h3>
          <ul><li>Visible result item.</li></ul>
        </body></html>
        """,
        encoding="utf-8",
    )

    chunks = parse_document_to_chunks(path, paper_id="html_note", target_tokens=16, max_tokens=64)
    text = " ".join(chunk.text for chunk in chunks)

    assert "Visible method text" in text
    assert "Visible result item" in text
    assert "secretScript" not in text
    assert "hidden" not in text
    assert {chunk.section for chunk in chunks} == {"Methods", "Results"}


def test_html_large_file_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "large.html"
    path.write_text("<html><body><p>too large</p></body></html>", encoding="utf-8")
    monkeypatch.setattr(html_parser, "_MAX_HTML_BYTES", 1)

    with pytest.raises(ValueError, match="too large"):
        parse_document_to_chunks(path)
