from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence
from urllib.parse import unquote, urlparse

from markdown_it import MarkdownIt
from markdown_it.token import Token

from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.fonts import MONO
from kdp_book_builder.util import is_relative_to, slugify

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".svg"}
PDF_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif"}
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SAFE_SCHEMES = {"http", "https", "mailto"}

markdown = MarkdownIt(
    "default",
    {
        "html": True,
        "typographer": True,
        "breaks": False,
    },
).enable("strikethrough")


@dataclass(frozen=True)
class Section:
    title: str
    level: int
    anchor: str
    line: int | None


@dataclass
class ParsedChapter:
    title: str
    source: Path
    relative_source: str
    tokens: list[Token]
    body_tokens: list[Token]
    sections: list[Section] = field(default_factory=list)
    title_anchor: str = "chapter-title"


@dataclass(frozen=True)
class ImageAsset:
    source: str
    path: Path | None
    alt: str
    problem: str | None


def parse_chapter_text(
    text: str, source: Path, relative_source: str
) -> ParsedChapter:
    text = text.lstrip("\ufeff")
    if not text.strip():
        raise BookBuilderError(
            f"{relative_source} is empty. Start each chapter with a single '# Title' heading."
        )
    tokens = markdown.parse(text)
    if not tokens or tokens[0].type != "heading_open" or tokens[0].tag != "h1":
        line = tokens[0].map[0] + 1 if tokens and tokens[0].map else 1
        raise BookBuilderError(
            f"{relative_source}:{line}: each chapter must start with a single "
            "'# Chapter title' heading."
        )
    inline = tokens[1] if len(tokens) > 1 else None
    if inline is None or inline.type != "inline":
        raise BookBuilderError(f"{relative_source}: the chapter title heading is empty.")
    title = inline_plain_text(inline)
    if not title:
        raise BookBuilderError(f"{relative_source}: the chapter title heading is empty.")
    if len(tokens) < 3 or tokens[2].type != "heading_close":
        raise BookBuilderError(
            f"{relative_source}: the chapter title heading is not formatted correctly."
        )

    body = tokens[3:]
    used_anchors = {"chapter-title"}
    sections: list[Section] = []
    for token in body:
        if token.type != "heading_open":
            continue
        level = int(token.tag[1])
        if level == 1:
            line_no = token.map[0] + 1 if token.map else None
            location = f":{line_no}" if line_no else ""
            raise BookBuilderError(
                f"{relative_source}{location}: use only one level-one heading per "
                "chapter. Use '##' for sections inside the chapter."
            )
        if level not in (2, 3):
            continue
        heading_inline = _next_inline(body, token)
        heading = inline_plain_text(heading_inline) if heading_inline else ""
        if not heading:
            continue
        anchor = _unique_anchor(heading, used_anchors)
        token.meta["kbb_anchor"] = anchor
        line_no = token.map[0] + 1 if token.map else None
        sections.append(Section(heading, level, anchor, line_no))

    return ParsedChapter(
        title=title,
        source=source,
        relative_source=relative_source,
        tokens=tokens,
        body_tokens=body,
        sections=sections,
    )


def inline_plain_text(inline: Token | None) -> str:
    if inline is None:
        return ""
    pieces: list[str] = []
    for child in inline.children or []:
        if child.type in {"text", "code_inline"}:
            pieces.append(child.content)
        elif child.type == "image":
            pieces.append(child.content or "image")
        elif child.type in {"softbreak", "hardbreak"}:
            pieces.append(" ")
    return _clean_spaces("".join(pieces))


def inline_to_pdf(
    inline: Token | None,
    *,
    warnings: list[str],
    source: str,
    image_label: str = "Image",
) -> str:
    """Render a markdown-it inline token as ReportLab paragraph markup."""
    if inline is None:
        return ""
    pieces: list[str] = []
    open_links: list[bool] = []
    for child in inline.children or []:
        kind = child.type
        if kind == "text":
            pieces.append(_escape_text(child.content))
        elif kind == "softbreak":
            pieces.append(" ")
        elif kind == "hardbreak":
            pieces.append("<br/>")
        elif kind == "code_inline":
            pieces.append(
                f'<font name="{MONO}" color="#4C463D">'
                f"{_escape_text(child.content)}</font>"
            )
        elif kind == "strong_open":
            pieces.append("<b>")
        elif kind == "strong_close":
            pieces.append("</b>")
        elif kind == "em_open":
            pieces.append("<i>")
        elif kind == "em_close":
            pieces.append("</i>")
        elif kind == "s_open":
            pieces.append("<strike>")
        elif kind == "s_close":
            pieces.append("</strike>")
        elif kind == "link_open":
            href = child.attrGet("href") or ""
            safe = safe_href(href)
            open_links.append(bool(safe))
            if safe:
                pieces.append(f'<a href="{html.escape(safe, quote=True)}">')
            else:
                warnings.append(
                    f"{source}: ignored an unsafe or unsupported link: {href!r}"
                )
        elif kind == "link_close":
            if open_links and open_links.pop():
                pieces.append("</a>")
        elif kind == "image":
            alt = child.content or child.attrGet("alt") or image_label
            warnings.append(
                f"{source}: inline images mixed with text are shown as their alt "
                f"text ('{alt}'). Put an image on its own line to print it."
            )
            pieces.append(f"<i>[{_escape_text(alt)}]</i>")
        elif kind == "html_inline":
            if child.content.strip():
                warnings.append(
                    f"{source}: raw HTML ({child.content[:40]!r}) was ignored."
                )
        # Unknown inline token types are intentionally ignored.
    return "".join(pieces)


def inline_to_xhtml(
    inline: Token | None,
    *,
    warnings: list[str],
    source: str,
    image_renderer: Callable[[str, str], str | None] | None = None,
    link_resolver: Callable[[str], str | None] | None = None,
) -> str:
    """Render a markdown-it inline token as well-formed XHTML.

    ``link_resolver`` may return a replacement href, the original href, or
    ``None`` to keep the link text but remove the link.
    """
    if inline is None:
        return ""
    pieces: list[str] = []
    open_links: list[bool] = []
    for child in inline.children or []:
        kind = child.type
        if kind == "text":
            pieces.append(_escape_text(child.content))
        elif kind == "softbreak":
            pieces.append("\n")
        elif kind == "hardbreak":
            pieces.append("<br />")
        elif kind == "code_inline":
            pieces.append(f"<code>{_escape_text(child.content)}</code>")
        elif kind == "strong_open":
            pieces.append("<strong>")
        elif kind == "strong_close":
            pieces.append("</strong>")
        elif kind == "em_open":
            pieces.append("<em>")
        elif kind == "em_close":
            pieces.append("</em>")
        elif kind == "s_open":
            pieces.append("<del>")
        elif kind == "s_close":
            pieces.append("</del>")
        elif kind == "link_open":
            href = child.attrGet("href") or ""
            safe = safe_href(href)
            if safe and link_resolver is not None:
                safe = link_resolver(safe)
            open_links.append(bool(safe))
            if safe:
                pieces.append(f'<a href="{html.escape(safe, quote=True)}">')
            else:
                warnings.append(
                    f"{source}: removed an unsafe or unsupported link: {href!r}"
                )
        elif kind == "link_close":
            if open_links and open_links.pop():
                pieces.append("</a>")
        elif kind == "image":
            alt = child.content or child.attrGet("alt") or "image"
            rendered = (
                image_renderer(child.attrGet("src") or "", alt)
                if image_renderer
                else None
            )
            if rendered:
                pieces.append(rendered)
            else:
                pieces.append(f"<span class=\"missing-image\">[{_escape_text(alt)}]</span>")
        elif kind == "html_inline":
            if child.content.strip():
                warnings.append(
                    f"{source}: raw HTML ({child.content[:40]!r}) was ignored."
                )
        # Unknown inline token types are intentionally ignored.
    return "".join(pieces)


def resolve_image(source: str, chapter_path: Path, book_root: Path) -> ImageAsset:
    alt_fallback = Path(unquote(source)).stem.replace("-", " ").replace("_", " ")
    if not source.strip():
        return ImageAsset(source, None, alt_fallback, "the image path is empty")
    parsed = urlparse(source)
    if parsed.scheme or parsed.netloc or source.startswith("//"):
        return ImageAsset(
            source,
            None,
            alt_fallback,
            "remote and embedded images are not supported; save the image inside the book folder",
        )
    raw_path = unquote(parsed.path)
    if not raw_path:
        return ImageAsset(source, None, alt_fallback, "the image path is empty")
    candidate = Path(raw_path)
    if candidate.is_absolute():
        path = candidate
    else:
        path = (chapter_path.parent / candidate).resolve()
        if not path.is_file():
            path = (book_root / candidate).resolve()
    if not is_relative_to(path, book_root):
        return ImageAsset(
            source,
            None,
            alt_fallback,
            "the image is outside the book folder",
        )
    if not path.is_file():
        return ImageAsset(source, None, alt_fallback, "the image file was not found")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        supported = ", ".join(sorted(IMAGE_SUFFIXES))
        return ImageAsset(
            source,
            None,
            alt_fallback,
            f"unsupported image type {path.suffix!r}; use {supported}",
        )
    return ImageAsset(source, path, alt_fallback, None)


def safe_href(href: str) -> str | None:
    href = href.strip()
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.scheme and parsed.scheme.lower() not in _SAFE_SCHEMES:
        return None
    return href


def table_align(token: Token) -> str:
    style = token.attrGet("style") or ""
    if "right" in style:
        return "right"
    if "center" in style:
        return "center"
    return "left"


def collect_table(tokens: Sequence[Token], start: int) -> tuple[list[list[tuple[Token, bool, str]]], int]:
    """Collect a markdown-it table into rows of (inline token, is_header, align)."""
    rows: list[list[tuple[Token, bool, str]]] = []
    current_row: list[tuple[Token, bool, str]] | None = None
    is_header = False
    i = start + 1
    while i < len(tokens) and tokens[i].type != "table_close":
        token = tokens[i]
        if token.type == "thead_open":
            is_header = True
        elif token.type == "thead_close":
            is_header = False
        elif token.type == "tr_open":
            current_row = []
        elif token.type in {"th_open", "td_open"}:
            inline_token = tokens[i + 1] if i + 1 < len(tokens) else None
            if current_row is not None and inline_token and inline_token.type == "inline":
                current_row.append((inline_token, token.type == "th_open", table_align(token)))
        elif token.type == "tr_close" and current_row is not None:
            rows.append(current_row)
            current_row = None
        i += 1
    return rows, i


def html_block_to_text(content: str) -> str:
    without_comments = re.sub(r"<!--.*?-->", "", content, flags=re.DOTALL)
    without_tags = re.sub(r"<[^>]+>", " ", without_comments)
    text = _clean_spaces(html.unescape(without_tags))
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def _next_inline(tokens: Sequence[Token], heading_open: Token) -> Token | None:
    try:
        index = tokens.index(heading_open)
    except ValueError:
        return None
    if index + 1 < len(tokens) and tokens[index + 1].type == "inline":
        return tokens[index + 1]
    return None


def _unique_anchor(title: str, used: set[str]) -> str:
    base = slugify(title, fallback="section")
    candidate = base
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def _escape_text(value: str) -> str:
    return html.escape(_CONTROL_CHARS.sub("", value), quote=False)


def _clean_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
