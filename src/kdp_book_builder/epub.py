from __future__ import annotations

import html
import io
import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from markdown_it.token import Token

from kdp_book_builder.book import Book, Chapter
from kdp_book_builder.cover import render_ebook_cover
from kdp_book_builder.markdown import (
    IMAGE_SUFFIXES,
    collect_table,
    html_block_to_text,
    inline_to_xhtml,
    resolve_image,
)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}

_STYLESHEET = """\
html, body {
  margin: 0;
  padding: 0;
}
body {
  font-family: Georgia, "Times New Roman", serif;
  color: #25221f;
  line-height: 1.58;
  padding: 0 5%;
}
h1, h2, h3, h4, h5, h6 {
  font-family: Georgia, "Times New Roman", serif;
  color: #1d2c3a;
  line-height: 1.22;
  page-break-after: avoid;
}
h1 {
  font-size: 1.9em;
  margin: 1.15em 0 0.7em;
}
h2 {
  font-size: 1.42em;
  margin: 1.55em 0 0.6em;
}
h3 {
  font-size: 1.16em;
  margin: 1.35em 0 0.45em;
}
h4, h5, h6 {
  font-size: 1em;
  margin: 1.2em 0 0.4em;
}
p {
  margin: 0 0 0.8em;
  text-align: justify;
}
em { font-style: italic; }
strong { font-weight: bold; }
a {
  color: #1a567e;
  text-decoration: underline;
}
blockquote {
  margin: 1.1em 1.2em;
  padding: 0.65em 1em;
  border-left: 3px solid #b79b68;
  background-color: #f6f2ea;
  font-style: italic;
}
blockquote p:last-child { margin-bottom: 0; }
ul, ol {
  margin: 0.5em 0 0.9em 1.5em;
  padding: 0;
}
li { margin: 0 0 0.3em; }
hr {
  border: 0;
  border-top: 1px solid #b8aa91;
  margin: 1.6em auto;
  width: 35%;
}
pre {
  white-space: pre-wrap;
  word-wrap: break-word;
  font-size: 0.8em;
  line-height: 1.42;
  background: #f6f2ea;
  border: 1px solid #ded4c4;
  padding: 0.8em;
  margin: 0.9em 0;
}
code {
  font-family: "Courier New", Courier, monospace;
  font-size: 0.9em;
}
table {
  width: 100%;
  border-collapse: collapse;
  margin: 1em 0;
  font-size: 0.84em;
}
th, td {
  border: 1px solid #cfc5b4;
  padding: 0.4em 0.45em;
  vertical-align: top;
}
th {
  background-color: #f2ede4;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.94em;
}
.align-center { text-align: center; }
.align-right { text-align: right; }
.align-left { text-align: left; }
img {
  max-width: 100%;
  height: auto;
}
p > img { display: block; margin: 0.7em auto; }
.missing-image { color: #6f665b; font-style: italic; }
.chapter-kicker {
  margin-top: 15%;
  margin-bottom: 0.5em;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.72em;
  font-weight: bold;
  letter-spacing: 0.16em;
  color: #8a7147;
  text-align: left;
}
.chapter-title {
  margin-top: 0;
  font-size: 2.15em;
}
.chapter-rule {
  width: 4em;
  margin: 0 0 1.6em;
  border-top: 2px solid #b1894e;
}
.cover-page {
  padding: 0;
  margin: 0;
  text-align: center;
}
.cover-page img {
  width: 100%;
  height: auto;
  margin: 0;
  padding: 0;
}
.title-page {
  text-align: center;
  padding-top: 18%;
}
.title-page .imprint {
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.72em;
  letter-spacing: 0.12em;
  color: #7a684d;
  text-align: center;
}
.title-page .book-title {
  font-size: 2.55em;
  margin: 1.1em 0 0.35em;
}
.title-page .book-subtitle {
  font-style: italic;
  font-size: 1.15em;
  color: #4f4941;
  text-align: center;
}
.title-page .book-author {
  margin-top: 3em;
  font-family: Arial, Helvetica, sans-serif;
  letter-spacing: 0.08em;
  text-align: center;
}
.title-page .edition {
  margin-top: 2.2em;
  font-size: 0.85em;
  color: #6f665b;
  text-align: center;
}
.copyright-page {
  padding-top: 12%;
  font-family: Arial, Helvetica, sans-serif;
  font-size: 0.85em;
  line-height: 1.55;
}
.copyright-page p {
  text-align: left;
}
.copyright-page .book-title {
  font-family: Georgia, "Times New Roman", serif;
  font-size: 1.2em;
  margin-bottom: 1.4em;
  text-align: center;
}
.nav-page {
  padding-top: 5%;
}
.nav-page h1 {
  margin-top: 1em;
}
.nav-page ol {
  list-style-type: none;
  margin-left: 0;
}
.nav-page li {
  margin: 0.62em 0;
}
.nav-page li ol {
  margin-top: 0.4em;
  margin-left: 1.15em;
  font-size: 0.92em;
}
"""


@dataclass(frozen=True)
class EpubBuildResult:
    data: bytes
    cover_image: bytes
    chapter_count: int
    image_count: int
    identifier: str
    warnings: list[str]


@dataclass(frozen=True)
class _EpubImage:
    image_id: str
    href: str
    media_type: str
    data: bytes


@dataclass
class _ImageRegistry:
    images: list[_EpubImage] = field(default_factory=list)
    _by_path: dict[Path, _EpubImage] = field(default_factory=dict)

    def add(self, path: Path) -> _EpubImage:
        resolved = path.resolve()
        existing = self._by_path.get(resolved)
        if existing is not None:
            return existing
        suffix = path.suffix.lower()
        media_type = _IMAGE_TYPES.get(suffix)
        if media_type is None or suffix not in IMAGE_SUFFIXES:
            raise ValueError(f"Unsupported image type: {suffix}")
        index = len(self.images) + 1
        image = _EpubImage(
            image_id=f"content-image-{index:03d}",
            href=f"images/image-{index:03d}{suffix}",
            media_type=media_type,
            data=path.read_bytes(),
        )
        self.images.append(image)
        self._by_path[resolved] = image
        return image


def build_epub(book: Book) -> EpubBuildResult:
    warnings: list[str] = []
    cover_image, cover_warnings = render_ebook_cover(book)
    warnings.extend(cover_warnings)
    images = _ImageRegistry()
    chapter_targets = {
        chapter.source.resolve(): f"chapter-{chapter.number:02d}.xhtml"
        for chapter in book.chapters
    }

    chapter_documents: list[tuple[Chapter, str]] = []
    for chapter in book.chapters:
        renderer = _ChapterRenderer(
            book,
            chapter,
            images=images,
            chapter_targets=chapter_targets,
            warnings=warnings,
        )
        body = renderer.render()
        document = _xhtml_page(
            book,
            title=f"{chapter.title} — {book.title}",
            body=f'<div class="chapter">\n{body}\n</div>',
        )
        chapter_documents.append((chapter, document))

    nav_body = _navigation_body(book)
    nav_document = _xhtml_page(
        book,
        title=f"Contents — {book.title}",
        body=nav_body,
        body_class="nav-page",
        stylesheet_href="styles/book.css",
    )
    cover_document = _xhtml_page(
        book,
        title=f"Cover — {book.title}",
        body=(
            '<div class="cover">'
            f'<img src="../images/cover.jpg" alt="{_esc(f"Cover of {book.title}", quote=True)}" />'
            "</div>"
        ),
        body_class="cover-page",
    )
    title_document = _xhtml_page(
        book,
        title=book.title,
        body=_title_page_body(book),
        body_class="title-page",
    )
    copyright_document = _xhtml_page(
        book,
        title=f"Copyright — {book.title}",
        body=_copyright_page_body(book),
        body_class="copyright-page",
    )

    identifier = _identifier(book)
    opf = _content_opf(
        book,
        identifier=identifier,
        images=images.images,
        chapter_documents=chapter_documents,
    )
    container = _container_xml()
    chapter_files = [
        (f"OEBPS/text/chapter-{chapter.number:02d}.xhtml", document)
        for chapter, document in chapter_documents
    ]
    files: list[tuple[str, bytes]] = [
        ("META-INF/container.xml", container.encode("utf-8")),
        ("OEBPS/content.opf", opf.encode("utf-8")),
        ("OEBPS/nav.xhtml", nav_document.encode("utf-8")),
        ("OEBPS/styles/book.css", _STYLESHEET.encode("utf-8")),
        ("OEBPS/images/cover.jpg", cover_image),
        ("OEBPS/text/cover.xhtml", cover_document.encode("utf-8")),
        ("OEBPS/text/titlepage.xhtml", title_document.encode("utf-8")),
        ("OEBPS/text/copyright.xhtml", copyright_document.encode("utf-8")),
    ]
    files.extend((name, document.encode("utf-8")) for name, document in chapter_files)
    for image in images.images:
        files.append((f"OEBPS/{image.href}", image.data))

    data = _write_epub(files)
    return EpubBuildResult(
        data=data,
        cover_image=cover_image,
        chapter_count=len(book.chapters),
        image_count=len(images.images),
        identifier=identifier,
        warnings=_dedupe(warnings),
    )


class _ChapterRenderer:
    def __init__(
        self,
        book: Book,
        chapter: Chapter,
        *,
        images: _ImageRegistry,
        chapter_targets: dict[Path, str],
        warnings: list[str],
    ) -> None:
        self.book = book
        self.chapter = chapter
        self.images = images
        self.chapter_targets = chapter_targets
        self.warnings = warnings

    def render(self) -> str:
        chapter = self.chapter
        parts = [
            f'<p class="chapter-kicker">CHAPTER {chapter.number}</p>',
            f'<h1 class="chapter-title" id="chapter-{chapter.number:02d}-title">'
            f"{_esc(chapter.title)}</h1>",
            '<hr class="chapter-rule" />',
        ]
        parts.append(self._render_tokens())
        return "\n".join(part for part in parts if part)

    def _render_tokens(self) -> str:
        tokens = self.chapter.body_tokens
        inline_content_kinds = {
            "paragraph_close",
            "heading_close",
            "thead_open",
            "thead_close",
            "tbody_open",
            "tbody_close",
            "inline",
        }
        output: list[str] = []
        i = 0
        while i < len(tokens):
            token = tokens[i]
            kind = token.type

            if kind == "heading_open":
                level = int(token.tag[1])
                inline = tokens[i + 1] if i + 1 < len(tokens) else None
                rendered = self._inline(inline)
                if rendered:
                    anchor = token.meta.get("kbb_anchor")
                    id_attr = (
                        f' id="{_esc(str(anchor), quote=True)}"'
                        if anchor
                        else ""
                    )
                    output.append(f"<h{level}{id_attr}>{rendered}</h{level}>")
                i += 3
                continue

            if kind == "paragraph_open":
                inline = tokens[i + 1] if i + 1 < len(tokens) else None
                rendered = self._inline(inline)
                if rendered:
                    if token.hidden:
                        output.append(rendered)
                    else:
                        output.append(f"<p>{rendered}</p>")
                i += 3
                continue

            if kind == "bullet_list_open":
                output.append("<ul>")
                i += 1
                continue
            if kind == "ordered_list_open":
                start = token.attrGet("start")
                if start and str(start) not in {"", "1"} and str(start).isdigit():
                    output.append(f'<ol start="{start}">')
                else:
                    output.append("<ol>")
                i += 1
                continue
            if kind == "bullet_list_close":
                output.append("</ul>")
                i += 1
                continue
            if kind == "ordered_list_close":
                output.append("</ol>")
                i += 1
                continue
            if kind == "list_item_open":
                output.append("<li>")
                i += 1
                continue
            if kind == "list_item_close":
                output.append("</li>")
                i += 1
                continue

            if kind == "blockquote_open":
                output.append("<blockquote>")
                i += 1
                continue
            if kind == "blockquote_close":
                output.append("</blockquote>")
                i += 1
                continue

            if kind in {"fence", "code_block"}:
                code = token.content.replace("\t", "    ").rstrip("\n")
                if code:
                    output.append(f"<pre><code>{_esc(code)}</code></pre>")
                i += 1
                continue

            if kind == "hr":
                output.append("<hr />")
                i += 1
                continue

            if kind == "table_open":
                rows, end = collect_table(tokens, i)
                table = self._table(rows)
                if table:
                    output.append(table)
                i = end + 1
                continue

            if kind == "html_block":
                text = html_block_to_text(token.content)
                if text:
                    self.warnings.append(
                        f"{self.chapter.relative_source}: raw HTML was converted to "
                        "plain text for the ebook; use Markdown for reliable formatting."
                    )
                    output.append(f"<p>{_esc(text)}</p>")
                i += 1
                continue

            if kind in inline_content_kinds:
                i += 1
                continue

            # Tables and token types not understood here have already emitted their
            # content, or are structural only. Skipping keeps the document valid.
            i += 1
        return "\n".join(output)

    def _inline(self, token: Token | None) -> str:
        return inline_to_xhtml(
            token,
            warnings=self.warnings,
            source=self.chapter.relative_source,
            image_renderer=self._render_image,
            link_resolver=self._resolve_link,
        )

    def _render_image(self, source: str, alt: str) -> str | None:
        asset = resolve_image(source, self.chapter.source, self.book.root)
        display_alt = alt.strip() or asset.alt or "Image"
        if asset.problem or asset.path is None:
            self.warnings.append(
                f"{self.chapter.relative_source}: image {source!r} skipped "
                f"({asset.problem})."
            )
            return None
        try:
            image = self.images.add(asset.path)
        except OSError:
            self.warnings.append(
                f"{self.chapter.relative_source}: image {source!r} could not be read."
            )
            return None
        except ValueError:
            self.warnings.append(
                f"{self.chapter.relative_source}: image {source!r} has an unsupported "
                "file type."
            )
            return None
        if asset.path.suffix.lower() == ".svg":
            self.warnings.append(
                f"{self.chapter.relative_source}: {asset.path.name} is an SVG. It is "
                "kept in the EPUB, but a 300 DPI PNG or JPEG is safer for Kindle."
            )
        href = f"../{image.href}"
        return (
            f'<img src="{_esc(href, quote=True)}" '
            f'alt="{_esc(display_alt, quote=True)}" />'
        )

    def _resolve_link(self, href: str) -> str | None:
        if href.startswith("#") or href.lower().startswith(
            ("http://", "https://", "mailto:")
        ):
            return href
        parsed = urlsplit(href)
        if parsed.scheme or parsed.netloc or not parsed.path:
            return href if parsed.scheme in {"http", "https", "mailto"} else None
        raw_path = unquote(parsed.path)
        candidate = (self.chapter.source.parent / raw_path).resolve()
        target = self.chapter_targets.get(candidate)
        if target is None:
            chapter_relative = (self.book.root / raw_path).resolve()
            target = self.chapter_targets.get(chapter_relative)
        if target is None:
            return None
        fragment = f"#{parsed.fragment}" if parsed.fragment else ""
        return f"{target}{fragment}"

    def _table(self, rows: list[list[tuple[Token, bool, str]]]) -> str:
        if not rows:
            return ""
        column_count = max(len(row) for row in rows)
        output = ['<table class="data-table">']
        in_head = True
        for row in rows:
            header_row = bool(row and row[0][1])
            if header_row and in_head:
                output.append("<thead>")
            if not header_row and in_head:
                output.append("</thead>")
                output.append("<tbody>")
                in_head = False
            output.append("<tr>")
            for index in range(column_count):
                if index < len(row):
                    inline, is_header, align = row[index]
                    rendered = self._inline(inline)
                else:
                    rendered, is_header, align = "", False, "left"
                tag = "th" if is_header else "td"
                scope = ' scope="col"' if is_header else ""
                css_class = f' class="align-{align}"' if align != "left" else ""
                output.append(f"<{tag}{scope}{css_class}>{rendered}</{tag}>")
            output.append("</tr>")
        if in_head:
            output.append("</thead>")
        else:
            output.append("</tbody>")
        output.append("</table>")
        return "\n".join(output)


def _title_page_body(book: Book) -> str:
    parts = ['<div class="title-page-inner">']
    if book.publisher:
        parts.append(f'<p class="imprint">{_esc(book.publisher.upper())}</p>')
    parts.append(f'<h1 class="book-title">{_esc(book.title)}</h1>')
    if book.subtitle:
        parts.append(f'<p class="book-subtitle">{_esc(book.subtitle)}</p>')
    parts.append(f'<p class="book-author">{_esc(book.author.upper())}</p>')
    if book.edition:
        parts.append(f'<p class="edition">{_esc(book.edition)}</p>')
    parts.append("</div>")
    return "\n".join(parts)


def _copyright_page_body(book: Book) -> str:
    parts = [f'<p class="book-title">{_esc(book.title)}</p>']
    parts.append(f"<p>Copyright © {book.copyright_year} {_esc(book.copyright_holder)}</p>")
    parts.append("<p>All rights reserved.</p>")
    if book.edition:
        parts.append(f"<p>{_esc(book.edition)}</p>")
    if book.publisher:
        parts.append(f"<p>Published by {_esc(book.publisher)}</p>")
    if book.isbn:
        parts.append(f"<p>ISBN {_esc(book.isbn)}</p>")
    parts.append(
        "<p>No part of this publication may be reproduced, distributed, or "
        "transmitted in any form or by any means without prior written permission "
        "from the copyright holder, except for brief quotations in reviews or "
        "other uses permitted by law.</p>"
    )
    if book.disclaimer:
        parts.append(f"<p>{_esc(book.disclaimer)}</p>")
    return "\n".join(parts)


def _navigation_body(book: Book) -> str:
    parts = [
        '<nav epub:type="toc" id="toc">',
        "<h1>Contents</h1>",
        "<ol>",
    ]
    for chapter in book.chapters:
        target = f"text/chapter-{chapter.number:02d}.xhtml"
        parts.append(
            f'<li><a href="{target}#chapter-{chapter.number:02d}-title">'
            f"{chapter.number}. {_esc(chapter.title)}</a>"
        )
        sections = [section for section in chapter.sections if section.level == 2]
        if sections:
            parts.append("<ol>")
            for section in sections:
                parts.append(
                    f'<li><a href="{target}#{_esc(section.anchor, quote=True)}">'
                    f"{_esc(section.title)}</a></li>"
                )
            parts.append("</ol>")
        parts.append("</li>")
    parts.extend(["</ol>", "</nav>"])
    return "\n".join(parts)


def _content_opf(
    book: Book,
    *,
    identifier: str,
    images: list[_EpubImage],
    chapter_documents: list[tuple[Chapter, str]],
) -> str:
    metadata = [
        f'<dc:identifier id="pub-id">{_esc(identifier)}</dc:identifier>',
        f'<dc:title id="main-title">{_esc(book.title)}</dc:title>',
        '<meta refines="#main-title" property="title-type">main</meta>',
        f'<dc:creator id="creator">{_esc(book.author)}</dc:creator>',
        '<meta refines="#creator" property="role" scheme="marc:relators">aut</meta>',
        f"<dc:language>{_esc(book.language)}</dc:language>",
        f'<meta property="dcterms:modified">{_timestamp()}</meta>',
    ]
    if book.subtitle:
        metadata.extend(
            [
                f'<dc:title id="subtitle">{_esc(book.subtitle)}</dc:title>',
                '<meta refines="#subtitle" property="title-type">subtitle</meta>',
            ]
        )
    if book.publisher:
        metadata.append(f"<dc:publisher>{_esc(book.publisher)}</dc:publisher>")
    if book.description:
        metadata.append(f"<dc:description>{_esc(book.description)}</dc:description>")
    for keyword in book.keywords:
        metadata.append(f"<dc:subject>{_esc(keyword)}</dc:subject>")
    metadata.append(
        f"<dc:rights>Copyright © {book.copyright_year} "
        f"{_esc(book.copyright_holder)}. All rights reserved.</dc:rights>"
    )

    manifest = [
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
        '<item id="book-css" href="styles/book.css" media-type="text/css"/>',
        '<item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
        '<item id="cover-page" href="text/cover.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="title-page" href="text/titlepage.xhtml" media-type="application/xhtml+xml"/>',
        '<item id="copyright-page" href="text/copyright.xhtml" media-type="application/xhtml+xml"/>',
    ]
    spine = [
        '<itemref idref="cover-page"/>',
        '<itemref idref="title-page"/>',
        '<itemref idref="copyright-page"/>',
        '<itemref idref="nav"/>',
    ]
    for chapter, _ in chapter_documents:
        item_id = f"chapter-{chapter.number:02d}"
        manifest.append(
            f'<item id="{item_id}" href="text/chapter-{chapter.number:02d}.xhtml" '
            'media-type="application/xhtml+xml"/>'
        )
        spine.append(f'<itemref idref="{item_id}"/>')
    for image in images:
        manifest.append(
            f'<item id="{image.image_id}" href="{_esc(image.href, quote=True)}" '
            f'media-type="{image.media_type}"/>'
        )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="pub-id" xml:lang="{_esc(book.language, quote=True)}">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    {chr(10).join("    " + item for item in metadata)}
  </metadata>
  <manifest>
    {chr(10).join("    " + item for item in manifest)}
  </manifest>
  <spine>
    {chr(10).join("    " + item for item in spine)}
  </spine>
</package>
"""


def _container_xml() -> str:
    return """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _xhtml_page(
    book: Book,
    *,
    title: str,
    body: str,
    body_class: str | None = None,
    stylesheet_href: str = "../styles/book.css",
) -> str:
    class_attr = f' class="{body_class}"' if body_class else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="{_esc(book.language, quote=True)}" lang="{_esc(book.language, quote=True)}">
<head>
  <meta charset="utf-8" />
  <title>{_esc(title)}</title>
  <link rel="stylesheet" type="text/css" href="{_esc(stylesheet_href, quote=True)}" />
</head>
<body{class_attr}>
{body}
</body>
</html>
"""


def _identifier(book: Book) -> str:
    if book.isbn:
        return f"urn:isbn:{book.isbn}"
    seed = f"kdp-book-builder:{book.slug}:{book.author.casefold()}:{book.edition or ''}"
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, seed)}"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_epub(files: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        mimetype = zipfile.ZipInfo("mimetype")
        mimetype.compress_type = zipfile.ZIP_STORED
        mimetype.external_attr = 0o644 << 16
        archive.writestr(mimetype, "application/epub+zip")
        for name, content in files:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    return buffer.getvalue()


def _esc(value: object, *, quote: bool = False) -> str:
    cleaned = _CONTROL_CHARS.sub("", str(value))
    return html.escape(cleaned, quote=quote)


def _dedupe(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            result.append(message)
    return result
