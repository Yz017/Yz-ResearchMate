from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from charset_normalizer import from_bytes

from researchmate.services.documents import ParsedPage, normalize_text

_MAX_HTML_BYTES = 10 * 1024 * 1024
_META_CHARSET_RE = re.compile(rb"<meta[^>]+charset=['\"]?\s*([A-Za-z0-9._:-]+)", re.I)
_META_HTTP_EQUIV_RE = re.compile(
    rb"<meta[^>]+http-equiv=['\"]content-type['\"][^>]*content=['\"][^'\"]*charset="
    rb"([A-Za-z0-9._:-]+)",
    re.I,
)
_XML_ENCODING_RE = re.compile(rb'^<\?xml[^>]+encoding=["\']([A-Za-z0-9._:-]+)["\']', re.I)
_BLOCK_TAGS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6"}
_SKIP_TAGS = {"script", "style", "nav", "footer", "header"}


def extract_pages(path: str | Path) -> list[ParsedPage]:
    html_path = Path(path)
    if not html_path.exists():
        msg = f"document not found: {html_path}"
        raise FileNotFoundError(msg)
    raw = html_path.read_bytes()
    if len(raw) > _MAX_HTML_BYTES:
        msg = f"HTML file is too large to ingest safely: {html_path}"
        raise ValueError(msg)

    text = _decode_html(raw)
    soup = BeautifulSoup(text, "lxml")
    for node in soup.find_all(list(_SKIP_TAGS)):
        node.decompose()

    lines = _collect_lines(soup.body or soup)
    content = "\n\n".join(line for line in lines if normalize_text(line))
    if not normalize_text(content):
        msg = f"No extractable text found in {html_path}"
        raise ValueError(msg)
    return [ParsedPage(page_number=1, text=content)]


def _decode_html(raw: bytes) -> str:
    for pattern in (_META_CHARSET_RE, _META_HTTP_EQUIV_RE, _XML_ENCODING_RE):
        match = pattern.search(raw[:4096])
        if not match:
            continue
        encoding = match.group(1).decode("ascii", errors="ignore").strip()
        if not encoding:
            continue
        try:
            return raw.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            continue
    try:
        match = from_bytes(raw).best()
    except Exception:
        match = None
    if match is not None:
        try:
            return str(match)
        except Exception:
            pass
    return raw.decode("utf-8", errors="replace")


def _collect_lines(node: object) -> list[str]:
    lines: list[str] = []
    for child in getattr(node, "children", []) or []:
        name = str(getattr(child, "name", "")).lower()
        if not name:
            text = normalize_text(str(getattr(child, "string", "")))
            if text:
                lines.append(text)
            continue
        if name in _SKIP_TAGS:
            continue
        if name in _BLOCK_TAGS:
            text = normalize_text(child.get_text(" ", strip=True))
            if not text:
                continue
            if name.startswith("h") and len(name) == 2 and name[1].isdigit():
                lines.append(f"{'#' * int(name[1])} {text}")
            elif name == "li":
                lines.append(f"- {text}")
            else:
                lines.append(text)
            continue
        lines.extend(_collect_lines(child))
    return lines
