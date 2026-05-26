from __future__ import annotations

from pathlib import Path

from charset_normalizer import from_path

from researchmate.services.documents import ParsedPage, normalize_text


def read_text(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.exists():
        msg = f"document not found: {file_path}"
        raise FileNotFoundError(msg)

    raw = file_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    try:
        match = from_path(file_path).best()
    except Exception:
        match = None
    if match is not None:
        try:
            return str(match)
        except Exception:
            pass
    return file_path.read_text(encoding="utf-8", errors="replace")


def extract_pages(path: str | Path) -> list[ParsedPage]:
    text = read_text(path)
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    content = "\n\n".join(line for line in lines if line)
    if not normalize_text(content):
        msg = f"No extractable text found in {Path(path)}"
        raise ValueError(msg)
    return [ParsedPage(page_number=1, text=content)]
