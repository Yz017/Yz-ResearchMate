from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt

from researchmate.services.documents import ParsedPage, normalize_text
from researchmate.services.parsers.txt import read_text


def extract_pages(path: str | Path) -> list[ParsedPage]:
    text = read_text(path)
    if not normalize_text(text):
        msg = f"No extractable text found in {Path(path)}"
        raise ValueError(msg)

    tokens = MarkdownIt().parse(text)
    lines = _tokens_to_lines(tokens)
    content = "\n\n".join(line for line in lines if normalize_text(line))
    if not normalize_text(content):
        msg = f"No extractable text found in {Path(path)}"
        raise ValueError(msg)
    return [ParsedPage(page_number=1, text=content)]


def _tokens_to_lines(tokens: list[object]) -> list[str]:
    lines: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        token_type = getattr(token, "type", "")
        if token_type == "heading_open":
            level = _heading_level(str(getattr(token, "tag", "h1")))
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            heading = normalize_text(str(getattr(inline, "content", ""))) if inline else ""
            if heading:
                lines.append(f"{'#' * level} {heading}")
        elif token_type == "paragraph_open":
            prev = tokens[index - 1] if index > 0 else None
            if str(getattr(prev, "type", "")) == "list_item_open":
                index += 1
                continue
            inline = tokens[index + 1] if index + 1 < len(tokens) else None
            text = normalize_text(str(getattr(inline, "content", ""))) if inline else ""
            if text:
                lines.append(text)
        elif token_type == "inline":
            prev = tokens[index - 1] if index > 0 else None
            prev_type = str(getattr(prev, "type", ""))
            if prev_type not in {"heading_open", "paragraph_open", "item_open"}:
                text = normalize_text(str(getattr(token, "content", "")))
                if text:
                    lines.append(text)
        elif token_type in {"fence", "code_block"}:
            lines.append(_format_code_block(token))
        elif token_type == "list_item_open":
            inline = _next_inline(tokens, index)
            text = normalize_text(str(getattr(inline, "content", ""))) if inline else ""
            if text:
                lines.append(f"- {text}")
        index += 1
    return lines


def _next_inline(tokens: list[object], start: int) -> object | None:
    for token in tokens[start + 1 :]:
        if getattr(token, "type", "") == "inline":
            return token
        if getattr(token, "type", "") in {"list_item_close", "paragraph_close", "heading_close"}:
            continue
    return None


def _heading_level(tag: str) -> int:
    if len(tag) == 2 and tag.startswith("h") and tag[1].isdigit():
        return int(tag[1])
    return 1


def _format_code_block(token: object) -> str:
    info = normalize_text(str(getattr(token, "info", "")))
    content = str(getattr(token, "content", "")).rstrip()
    if content:
        return f"```{info}\n{content}\n```" if info else f"```\n{content}\n```"
    return f"```{info}\n```" if info else "```"
