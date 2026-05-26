from __future__ import annotations

from pathlib import Path

import pytest

from researchmate.services.parsers import parse_document_to_chunks


def test_txt_utf8_chinese_file_parses_to_chunks(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("研究笔记\n\n方法\n这份文档用于测试中文 TXT 入库。", encoding="utf-8")

    chunks = parse_document_to_chunks(path, paper_id="txt_note", target_tokens=64)

    assert chunks
    assert chunks[0].paper_id == "txt_note"
    assert "中文 TXT 入库" in " ".join(chunk.text for chunk in chunks)


def test_txt_gbk_file_decodes_or_falls_back_without_error(tmp_path: Path) -> None:
    path = tmp_path / "gbk.txt"
    path.write_bytes("结果\nGBK 编码文本也应该能被入库。".encode("gbk"))

    chunks = parse_document_to_chunks(path, paper_id="gbk_note", target_tokens=64)

    assert chunks
    assert "GBK" in " ".join(chunk.text for chunk in chunks)


def test_txt_empty_file_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="No extractable text"):
        parse_document_to_chunks(path)
