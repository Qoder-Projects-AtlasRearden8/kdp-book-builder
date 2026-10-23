from __future__ import annotations

import html
import io
import textwrap
from dataclasses import dataclass
from typing import Iterable, Sequence

from PIL import Image as PILImage
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    HRFlowable,
    Image as RLImage,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)
from reportlab.platypus.tableofcontents import TableOfContents

from kdp_book_builder.book import Book, Chapter
from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.fonts import (
    MONO,
    SANS,
    SANS_BOLD,
    SERIF,
    SERIF_BOLD,
    SERIF_ITALIC,
    register_fonts,
)
from kdp_book_builder.layout import (
    Margins,
    automatic_inside_margin_in,
    fmt_inches,
    resolve_margins,
    validate_margins,
    validate_page_count,
)
from kdp_book_builder.markdown import (
    PDF_IMAGE_SUFFIXES,
    collect_table,
    html_block_to_text,
    inline_to_pdf,
    resolve_image,
)

PAPER_INK = colors.HexColor("#2C2823")
MUTED_INK = colors.HexColor("#5E574D")
WARM_META = colors.HexColor("#7A684D")
RULE_INK = colors.HexColor("#B8AA91")
PAPER_TINT = colors.HexColor("#F6F2EA")
QUOTE_TINT = colors.HexColor("#FAF7F1")
TABLE_GRID = colors.HexColor("#CFC5B4")
WHITE = colors.white

PAGE_NUMBER_START = 3


@dataclass(frozen=True)
class ChapterPage:
    number: int
    title: str
    page: int


@dataclass(frozen=True)
class PdfBuildResult:
    data: bytes
    page_count: int
    layout_page_count: int
    padded_pages: int
    margins: Margins
    chapters: list[ChapterPage]
    warnings: list[str]


@dataclass
class _Styles:
    text_width: float
    trim_width: float
    trim_height: float
    body: ParagraphStyle
    quote: ParagraphStyle
    bullet: ParagraphStyle
    code: ParagraphStyle
    h2: ParagraphStyle
    h3: ParagraphStyle
    kicker: ParagraphStyle
    chapter_title: ParagraphStyle
    toc_title: ParagraphStyle
    toc_levels: list[ParagraphStyle]
    caption: ParagraphStyle
    table_cell: ParagraphStyle
    table_header: ParagraphStyle
    copyright_body: ParagraphStyle


class _MirroredTemplate(PageTemplate):
    """A page template that swaps to the correct recto/verso frame."""

    def __init__(
        self,
        recto: Frame,
        verso: Frame,
        on_page: object,
    ) -> None:
        super().__init__(id="mirrored", frames=[recto], onPage=on_page)
        self.recto = recto
        self.verso = verso

    def beforeDrawPage(self, canv: Canvas, doc: BaseDocTemplate) -> None:
        self.frames = [self.recto if doc.page % 2 else self.verso]


class _BookDoc(BaseDocTemplate):
    def __init__(
        self,
        target: io.BytesIO,
        *,
        book: Book,
        margins: Margins,
        styles: _Styles,
    ) -> None:
        self.book_ref = book
        self.margins_ref = margins
        self.styles_ref = styles
        self.chapter_pages: dict[int, int] = {}
        width = float(book.trim.width_in) * inch
        height = float(book.trim.height_in) * inch
        super().__init__(
            target,
            pagesize=(width, height),
            leftMargin=float(margins.outside) * inch,
            rightMargin=float(margins.inside) * inch,
            topMargin=float(margins.top) * inch,
            bottomMargin=float(margins.bottom) * inch,
            title=book.title,
            author=book.author,
            subject=book.subtitle or "",
            creator="kdp-book-builder",
            producer="kdp-book-builder",
            keywords=book.keywords,
            lang=book.language,
            pageCompression=1,
            initialFontName=SERIF,
            initialFontSize=11.3,
            initialLeading=16.7,
        )
        bottom = float(margins.bottom) * inch
        top = float(margins.top) * inch
        inside = float(margins.inside) * inch
        outside = float(margins.outside) * inch
        footer_clearance = 0.5 * inch
        frame_bottom = max(bottom, footer_clearance)
        body_width = width - inside - outside
        body_height = height - top - frame_bottom
        recto = Frame(
            inside,
            frame_bottom,
            body_width,
            body_height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="recto",
        )
        verso = Frame(
            outside,
            frame_bottom,
            body_width,
            body_height,
            leftPadding=0,
            rightPadding=0,
            topPadding=0,
            bottomPadding=0,
            id="verso",
        )

        def decorate_page(canv: Canvas, doc: BaseDocTemplate) -> None:
            if doc.page < PAGE_NUMBER_START:
                return
            canv.saveState()
            canv.setFont(SANS, 8.8)
            canv.setFillColor(MUTED_INK)
            y = max(0.34 * inch, bottom / 2)
            number_inset = max(0.36 * inch, outside * 0.58)
            if doc.page % 2:
                x = width - number_inset
            else:
                x = number_inset
            canv.drawCentredString(x, y, str(doc.page))
            canv.restoreState()

        self.addPageTemplates(
            [_MirroredTemplate(recto=recto, verso=verso, on_page=decorate_page)]
        )

    def beforeDocument(self) -> None:
        self.chapter_pages = {}

    def afterFlowable(self, flowable: Flowable) -> None:
        key = getattr(flowable, "_kdp_key", None)
        if not key:
            return
        level = getattr(flowable, "_kdp_toc_level", None)
        toc_text = getattr(flowable, "_kdp_toc_text", "")
        outline_text = getattr(flowable, "_kdp_outline_text", toc_text)
        self.canv.bookmarkPage(key)
        self.canv.addOutlineEntry(
            outline_text,
            key,
            level=level if level is not None else 0,
            closed=False,
        )
        if level is not None:
            self.notify(
                "TOCEntry",
                (level, html.escape(toc_text, quote=False), self.page, key),
            )
        chapter_number = getattr(flowable, "_kdp_chapter_number", None)
        if chapter_number is not None:
            self.chapter_pages[int(chapter_number)] = self.page


class _TitlePage(Flowable):
    def __init__(self, book: Book) -> None:
        super().__init__()
        self.book = book
        self.width = 0.0
        self.height = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self.width = avail_width
        self.height = max(1.0, avail_height - 0.5)
        return self.width, self.height

    def draw(self) -> None:
        c = self.canv
        book = self.book
        width = self.width
        height = self.height
        center = width / 2
        max_text_width = width * 0.86

        c.saveState()
        c.setFillColor(PAPER_INK)
        if book.publisher:
            c.setFont(SANS_BOLD, 8.2)
            c.setFillColor(WARM_META)
            c.drawCentredString(center, height - 0.55 * inch, book.publisher.upper())
        c.setStrokeColor(RULE_INK)
        c.setLineWidth(0.7)
        c.line(center - 0.75 * inch, height - 0.7 * inch, center + 0.75 * inch, height - 0.7 * inch)

        title_size = 34.0
        if self.width < 330:
            title_size = 29.0
        if self.width > 460:
            title_size = 40.0
        title_lines: list[str] = []
        while title_size >= 20:
            title_lines = _wrap_text(
                book.title, SERIF_BOLD, title_size, max_text_width
            )
            if len(title_lines) <= 4:
                break
            title_size -= 1
        title_leading = title_size * 1.12
        title_block_height = len(title_lines) * title_leading
        title_center_y = height * 0.56
        title_top = title_center_y + title_block_height / 2 - title_size * 0.8

        c.setFont(SERIF_BOLD, title_size)
        c.setFillColor(PAPER_INK)
        y = title_top
        for line in title_lines:
            c.drawCentredString(center, y, line)
            y -= title_leading

        subtitle_y = title_top - len(title_lines) * title_leading - 0.12 * inch
        if book.subtitle:
            c.setFont(SERIF_ITALIC, 14.5)
            c.setFillColor(MUTED_INK)
            subtitle_lines = _wrap_text(
                book.subtitle, SERIF_ITALIC, 14.5, max_text_width * 0.86
            )
            for line in subtitle_lines[:4]:
                c.drawCentredString(center, subtitle_y, line)
                subtitle_y -= 19

        c.setStrokeColor(WARM_META)
        c.setLineWidth(1.0)
        c.line(center - 0.32 * inch, height * 0.34, center + 0.32 * inch, height * 0.34)
        c.setFont(SANS_BOLD, 12.2)
        c.setFillColor(PAPER_INK)
        c.drawCentredString(center, height * 0.34 - 0.3 * inch, book.author.upper())

        bottom = 0.62 * inch
        c.setFont(SANS, 8)
        c.setFillColor(MUTED_INK)
        if book.edition:
            c.drawCentredString(center, bottom, book.edition)
        c.restoreState()


class _CopyrightPage(Flowable):
    def __init__(self, book: Book) -> None:
        super().__init__()
        self.book = book
        self.width = 0.0
        self.height = 0.0

    def wrap(self, avail_width: float, avail_height: float) -> tuple[float, float]:
        self.width = avail_width
        self.height = max(1.0, avail_height - 0.5)
        return self.width, self.height

    def draw(self) -> None:
        book = self.book
        c = self.canv
        width = self.width
        height = self.height
        max_width = width * 0.9
        c.saveState()
        top = height - 0.62 * inch
        c.setFont(SERIF_BOLD, 10)
        c.setFillColor(PAPER_INK)
        for line in _wrap_text(book.title, SERIF_BOLD, 10, max_width):
            c.drawCentredString(width / 2, top, line)
            top -= 15
        top -= 8
        c.setFont(SANS, 8.4)
        c.setFillColor(MUTED_INK)
        copyright_lines = [
            f"Copyright © {book.copyright_year} {book.copyright_holder}",
            "All rights reserved.",
            "",
        ]
        if book.edition:
            copyright_lines.append(book.edition)
        if book.publisher:
            copyright_lines.append(f"Published by {book.publisher}")
        if book.isbn:
            copyright_lines.append(f"ISBN {book.isbn}")
        copyright_lines.extend(
            [
                "",
                "No part of this publication may be reproduced, distributed, or "
                "transmitted in any form or by any means without prior written "
                "permission from the copyright holder, except for brief quotations "
                "in reviews or other uses permitted by law.",
            ]
        )
        if book.disclaimer:
            copyright_lines.extend(["", book.disclaimer])
        for raw_line in copyright_lines:
            if not raw_line:
                top -= 6
                continue
            for line in _wrap_text(raw_line, SANS, 8.4, max_width):
                c.drawCentredString(width / 2, top, line)
                top -= 12.5
        c.restoreState()


def build_interior_pdf(book: Book) -> PdfBuildResult:
    register_fonts()
    warnings: list[str] = []
    inside_is_automatic = book.margins.inside is None
    page_estimate = max(book.paper.min_pages, len(book.chapters) + 3)
    final: PdfBuildResult | None = None

    for _attempt in range(6):
        margins = resolve_margins(
            page_estimate,
            inside=book.margins.inside,
            outside=book.margins.outside,
            top=book.margins.top,
            bottom=book.margins.bottom,
        )
        raw_pdf, chapter_pages, render_warnings = _layout_once(book, margins)
        warnings.extend(render_warnings)
        raw_count = len(PdfReader(io.BytesIO(raw_pdf)).pages)
        target_count = _padded_target(raw_count, book.paper.min_pages)
        validate_page_count(target_count, book.paper, book.trim)
        validate_margins(
            margins,
            target_count,
            book.trim,
            inside_was_automatic=inside_is_automatic,
        )
        if inside_is_automatic:
            wanted = automatic_inside_margin_in(target_count)
            if margins.inside < wanted:
                page_estimate = target_count
                continue
        padded_pdf, added = _pad_pdf(raw_pdf, target_count)
        if added:
            if raw_count < book.paper.min_pages:
                reason = (
                    f"KDP requires at least {book.paper.min_pages} pages for "
                    f"{book.paper.label.lower()}"
                )
            else:
                reason = "print binding works best with an even page count"
            warnings.append(
                f"The interior laid out to {raw_count} pages. Added {added} blank "
                f"page{'s' if added != 1 else ''} at the end because {reason}."
            )
        if book.paper.key == "standard-color" and target_count < 72:
            warnings.append(
                "Standard-color interiors require at least 72 pages; verify your "
                "KDP setup carefully."
            )
        chapter_list = [
            ChapterPage(
                number=chapter.number,
                title=chapter.title,
                page=chapter_pages.get(chapter.number, 0),
            )
            for chapter in book.chapters
        ]
        missing_pages = [chapter.number for chapter in chapter_list if chapter.page <= 0]
        if missing_pages:
            raise BookBuilderError(
                "The table of contents could not locate every chapter. Try building "
                "again; if this repeats, simplify nested lists or tables."
            )
        final = PdfBuildResult(
            data=padded_pdf,
            page_count=len(PdfReader(io.BytesIO(padded_pdf)).pages),
            layout_page_count=raw_count,
            padded_pages=added,
            margins=margins,
            chapters=chapter_list,
            warnings=_dedupe(warnings),
        )
        break

    if final is None:
        raise BookBuilderError(
            "Could not settle the page margins after several layout passes. "
            "Try a slightly larger trim size or simpler chapter formatting."
        )
    return final


def _layout_once(
    book: Book, margins: Margins
) -> tuple[bytes, dict[int, int], list[str]]:
    buffer = io.BytesIO()
    width_pt = float(book.trim.width_in) * inch
    styles = _build_styles(margins, width_pt, float(book.trim.height_in) * inch)
    doc = _BookDoc(buffer, book=book, margins=margins, styles=styles)
    warnings: list[str] = []
    story = _build_story(book, styles, warnings)
    try:
        doc.multiBuild(story, maxPasses=20)
    except IndexError as exc:
        raise BookBuilderError(
            "The table of contents did not settle after 20 layout passes. Try fewer "
            "chapters or shorter headings, then build again."
        ) from exc
    return buffer.getvalue(), dict(doc.chapter_pages), warnings


def _build_styles(margins: Margins, trim_width: float, trim_height: float) -> _Styles:
    text_width = float(trim_width - float(margins.inside + margins.outside) * inch)
    h1_size = 27.0 if text_width < 330 else 30.0
    return _Styles(
        text_width=text_width,
        trim_width=trim_width,
        trim_height=trim_height,
        body=ParagraphStyle(
            "Body",
            fontName=SERIF,
            fontSize=11.3,
            leading=16.7,
            alignment=TA_JUSTIFY,
            textColor=PAPER_INK,
            spaceAfter=6.4,
            splitLongWords=1,
            allowWidows=0,
            allowOrphans=0,
        ),
        quote=ParagraphStyle(
            "Quote",
            fontName=SERIF_ITALIC,
            fontSize=10.6,
            leading=15.6,
            leftIndent=18,
            rightIndent=8,
            textColor=colors.HexColor("#413B33"),
            borderColor=RULE_INK,
            borderWidth=0.6,
            borderPadding=(5, 6, 5, 8),
            backColor=QUOTE_TINT,
            spaceBefore=5,
            spaceAfter=11,
        ),
        bullet=ParagraphStyle(
            "Bullet",
            parent=None,
            fontName=SERIF,
            fontSize=10.9,
            leading=15.6,
            alignment=TA_LEFT,
            textColor=PAPER_INK,
            spaceAfter=3.5,
        ),
        code=ParagraphStyle(
            "Code",
            fontName=MONO,
            fontSize=8.2,
            leading=11.4,
            textColor=colors.HexColor("#302C27"),
            backColor=PAPER_TINT,
            borderColor=RULE_INK,
            borderWidth=0.5,
            borderPadding=(7, 8, 7, 8),
            leftIndent=0,
            rightIndent=0,
            spaceBefore=5,
            spaceAfter=10,
        ),
        h2=ParagraphStyle(
            "H2",
            fontName=SERIF_BOLD,
            fontSize=16.2,
            leading=20.5,
            textColor=PAPER_INK,
            spaceBefore=18,
            spaceAfter=7,
            keepWithNext=1,
        ),
        h3=ParagraphStyle(
            "H3",
            fontName=SERIF_BOLD,
            fontSize=12.2,
            leading=16.2,
            textColor=PAPER_INK,
            spaceBefore=13,
            spaceAfter=4.5,
            keepWithNext=1,
        ),
        kicker=ParagraphStyle(
            "ChapterKicker",
            fontName=SANS_BOLD,
            fontSize=8.5,
            leading=12,
            textColor=WARM_META,
            spaceAfter=7,
            keepWithNext=1,
        ),
        chapter_title=ParagraphStyle(
            "ChapterTitle",
            fontName=SERIF_BOLD,
            fontSize=h1_size,
            leading=h1_size * 1.16,
            textColor=PAPER_INK,
            spaceAfter=0,
        ),
        toc_title=ParagraphStyle(
            "ContentsTitle",
            fontName=SERIF_BOLD,
            fontSize=25,
            leading=30,
            textColor=PAPER_INK,
            spaceAfter=18,
        ),
        toc_levels=[
            ParagraphStyle(
                "TOC0",
                fontName=SANS,
                fontSize=10.2,
                leading=15,
                textColor=PAPER_INK,
                spaceBefore=7,
                leftIndent=0,
                rightIndent=0,
            ),
            ParagraphStyle(
                "TOC1",
                fontName=SANS,
                fontSize=9.2,
                leading=13.5,
                textColor=MUTED_INK,
                spaceBefore=2,
                leftIndent=20,
                rightIndent=0,
            ),
        ],
        caption=ParagraphStyle(
            "Caption",
            fontName=SERIF_ITALIC,
            fontSize=8.8,
            leading=12,
            textColor=MUTED_INK,
            alignment=TA_CENTER,
            spaceBefore=4,
            spaceAfter=11,
        ),
        table_cell=ParagraphStyle(
            "TableCell",
            fontName=SERIF,
            fontSize=8.8,
            leading=11.8,
            textColor=PAPER_INK,
        ),
        table_header=ParagraphStyle(
            "TableHeader",
            fontName=SANS_BOLD,
            fontSize=8.5,
            leading=11.4,
            textColor=PAPER_INK,
        ),
        copyright_body=ParagraphStyle(
            "CopyrightBody",
            fontName=SANS,
            fontSize=8.4,
            leading=12.5,
            textColor=MUTED_INK,
        ),
    )


def _build_story(book: Book, styles: _Styles, warnings: list[str]) -> list[Flowable]:
    story: list[Flowable] = []
    story.append(_TitlePage(book))
    story.append(PageBreak())
    story.append(_CopyrightPage(book))
    story.append(PageBreak())

    story.append(Paragraph("Contents", styles.toc_title))
    story.append(
        HRFlowable(
            width="100%",
            thickness=0.7,
            color=RULE_INK,
            spaceBefore=0,
            spaceAfter=12,
        )
    )
    toc = TableOfContents(
        levelStyles=styles.toc_levels,
        dotsMinLevel=0,
        rightColumnWidth=38,
        tableStyle=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("FONTNAME", (0, 0), (-1, -1), SERIF),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
            ]
        ),
    )
    story.append(toc)
    story.append(PageBreak())

    for chapter_index, chapter in enumerate(book.chapters):
        if chapter_index:
            story.append(PageBreak())
        _append_chapter(story, chapter, book, styles, warnings)
    return story


def _append_chapter(
    story: list[Flowable],
    chapter: Chapter,
    book: Book,
    styles: _Styles,
    warnings: list[str],
) -> None:
    kicker = Paragraph(f"CHAPTER {chapter.number}", styles.kicker)
    title = Paragraph(html.escape(chapter.title, quote=False), styles.chapter_title)
    key = f"chapter-{chapter.number:02d}"
    title._kdp_key = key
    title._kdp_toc_level = 0
    title._kdp_toc_text = f"{chapter.number}. {chapter.title}"
    title._kdp_outline_text = chapter.title
    title._kdp_chapter_number = chapter.number
    story.append(kicker)
    story.append(title)
    story.append(
        HRFlowable(
            width=0.55 * inch,
            thickness=1.1,
            color=WARM_META,
            hAlign="LEFT",
            spaceBefore=13,
            spaceAfter=17,
        )
    )
    _render_blocks(story, chapter, book, styles, warnings)


def _render_blocks(
    story: list[Flowable],
    chapter: Chapter,
    book: Book,
    styles: _Styles,
    warnings: list[str],
) -> None:
    tokens = chapter.body_tokens
    list_stack: list[dict[str, object]] = []
    quote_depth = 0
    i = 0
    while i < len(tokens):
        token = tokens[i]
        kind = token.type

        if kind == "heading_open":
            level = int(token.tag[1])
            inline_token = tokens[i + 1] if i + 1 < len(tokens) else None
            text = inline_to_pdf(
                inline_token,
                warnings=warnings,
                source=chapter.relative_source,
            )
            if not text:
                i += 3
                continue
            style = styles.h2 if level == 2 else styles.h3
            heading = Paragraph(text, style)
            if level == 2 and token.meta.get("kbb_anchor"):
                anchor = str(token.meta["kbb_anchor"])
                heading_key = f"chapter-{chapter.number:02d}-{anchor}"
                plain = _plain_heading(inline_token)
                heading._kdp_key = heading_key
                heading._kdp_toc_level = 1
                heading._kdp_toc_text = plain
                heading._kdp_outline_text = plain
            story.append(heading)
            i += 3
            continue

        if kind == "paragraph_open":
            inline_token = tokens[i + 1] if i + 1 < len(tokens) else None
            image_tokens = _standalone_images(inline_token)
            if image_tokens is not None:
                for image_token in image_tokens:
                    _append_image(
                        story,
                        image_token.attrGet("src") or "",
                        image_token.content or image_token.attrGet("alt") or "Image",
                        chapter,
                        book,
                        styles,
                        warnings,
                    )
                i += 3
                continue
            if inline_token is not None:
                rendered = inline_to_pdf(
                    inline_token,
                    warnings=warnings,
                    source=chapter.relative_source,
                )
                if rendered:
                    if quote_depth > 0:
                        story.append(Paragraph(rendered, styles.quote))
                    else:
                        paragraph, bullet_text = _paragraph_in_list(
                            list_stack, styles
                        )
                        if list_stack:
                            story.append(Paragraph(rendered, paragraph, bulletText=bullet_text))
                        else:
                            story.append(Paragraph(rendered, styles.body))
            i += 3
            continue

        if kind == "bullet_list_open":
            list_stack.append(
                {"ordered": False, "counter": 0, "first_para": False}
            )
            i += 1
            continue
        if kind == "ordered_list_open":
            start_value = token.attrGet("start") or "1"
            try:
                counter = int(start_value) - 1
            except ValueError:
                counter = 0
            list_stack.append(
                {"ordered": True, "counter": counter, "first_para": False}
            )
            i += 1
            continue
        if kind in {"bullet_list_close", "ordered_list_close"}:
            if list_stack:
                list_stack.pop()
            i += 1
            continue
        if kind == "list_item_open":
            if list_stack:
                list_stack[-1]["counter"] = int(list_stack[-1]["counter"]) + 1
                list_stack[-1]["first_para"] = True
            i += 1
            continue
        if kind == "list_item_close":
            i += 1
            continue
        if kind == "blockquote_open":
            quote_depth += 1
            i += 1
            continue
        if kind == "blockquote_close":
            quote_depth = max(0, quote_depth - 1)
            i += 1
            continue
        if kind in {"fence", "code_block"}:
            code = token.content.replace("\t", "    ").rstrip("\n")
            if code:
                style = _code_style(styles, len(list_stack))
                story.append(XPreformatted(_escape_code(code), style))
                story.append(Spacer(1, 2))
            i += 1
            continue
        if kind == "hr":
            story.append(
                HRFlowable(
                    width="35%",
                    thickness=0.7,
                    color=RULE_INK,
                    hAlign="CENTER",
                    spaceBefore=8,
                    spaceAfter=12,
                )
            )
            i += 1
            continue
        if kind == "table_open":
            rows, end = collect_table(tokens, i)
            if rows:
                story.append(_pdf_table(rows, styles, warnings, chapter.relative_source))
                story.append(Spacer(1, 8))
            i = end + 1
            continue
        if kind == "html_block":
            text = html_block_to_text(token.content)
            if text:
                warnings.append(
                    f"{chapter.relative_source}: raw HTML was converted to plain text; "
                    "use Markdown for reliable print formatting."
                )
                story.append(Paragraph(html.escape(text, quote=False), styles.body))
            i += 1
            continue

        if kind in {
            "paragraph_close",
            "heading_close",
            "thead_open",
            "thead_close",
            "tbody_open",
            "tbody_close",
            "tr_open",
            "tr_close",
            "table_close",
            "inline",
        }:
            i += 1
            continue
        # Structural or unsupported block token. Skipping it keeps the build moving;
        # visible text is almost always inside a paragraph token.
        i += 1


def _paragraph_in_list(
    list_stack: list[dict[str, object]], styles: _Styles
) -> tuple[ParagraphStyle, str | None]:
    if not list_stack:
        return styles.body, None
    state = list_stack[-1]
    depth = len(list_stack)
    first = bool(state["first_para"])
    ordered = bool(state["ordered"])
    counter = int(state["counter"])
    if ordered:
        bullet = f"{counter}."
    else:
        bullets = ["•", "◦", "▪", "–"]
        bullet = bullets[min(depth - 1, len(bullets) - 1)]
    left_indent = 15 + (depth - 1) * 17
    paragraph_style = ParagraphStyle(
        f"List-{depth}-{'ol' if ordered else 'ul'}",
        parent=styles.bullet,
        leftIndent=left_indent,
        bulletIndent=max(0, left_indent - 12),
        bulletFontName=SERIF,
        bulletFontSize=10.2,
    )
    if first:
        state["first_para"] = False
        return paragraph_style, bullet
    return paragraph_style, None


def _standalone_images(inline_token: object) -> list[object] | None:
    if inline_token is None or not getattr(inline_token, "children", None):
        return None
    images = [child for child in inline_token.children if child.type == "image"]
    if not images:
        return None
    for child in inline_token.children:
        if child.type == "image":
            continue
        if child.type == "text" and not child.content.strip():
            continue
        if child.type in {"softbreak", "hardbreak"}:
            continue
        return None
    return images


def _append_image(
    story: list[Flowable],
    source: str,
    alt: str,
    chapter: Chapter,
    book: Book,
    styles: _Styles,
    warnings: list[str],
) -> None:
    asset = resolve_image(source, chapter.source, book.root)
    display_alt = alt.strip() or asset.alt or "Image"
    if asset.problem or asset.path is None:
        warnings.append(
            f"{chapter.relative_source}: image {source!r} skipped ({asset.problem})."
        )
        story.append(
            Paragraph(
                html.escape(f"[Image: {display_alt}]", quote=False),
                styles.caption,
            )
        )
        return
    if asset.path.suffix.lower() not in PDF_IMAGE_SUFFIXES:
        warnings.append(
            f"{chapter.relative_source}: {asset.path.name} cannot be placed in the "
            "print PDF. Convert SVG images to 300 DPI PNG or JPEG for print."
        )
        story.append(
            Paragraph(
                html.escape(f"[Image: {display_alt}]", quote=False),
                styles.caption,
            )
        )
        return
    try:
        with PILImage.open(asset.path) as image:
            pixel_width, pixel_height = image.size
    except Exception:
        warnings.append(
            f"{chapter.relative_source}: image {asset.path.name} could not be read."
        )
        return

    max_width = styles.text_width
    max_height = styles.trim_height * 0.44
    display_width = min(max_width, (pixel_width / 96.0) * inch)
    display_height = display_width * pixel_height / pixel_width
    if display_height > max_height:
        display_height = max_height
        display_width = display_height * pixel_width / pixel_height
    try:
        rl_image = RLImage(
            str(asset.path), width=display_width, height=display_height
        )
    except Exception:
        warnings.append(
            f"{chapter.relative_source}: image {asset.path.name} is not in a format "
            "ReportLab can place in the PDF; use PNG or JPEG."
        )
        return
    rl_image.hAlign = "CENTER"
    effective_dpi = pixel_width / max(display_width / inch, 0.01)
    if effective_dpi < 300:
        warnings.append(
            f"{chapter.relative_source}: {asset.path.name} will print at about "
            f"{effective_dpi:.0f} DPI. Aim for 300 DPI at its printed size for crisp "
            "results."
        )
    caption = Paragraph(html.escape(display_alt, quote=False), styles.caption)
    story.append(KeepTogether([rl_image, caption]))
    story.append(Spacer(1, 6))


def _pdf_table(
    rows: Sequence[Sequence[tuple[object, bool, str]]],
    styles: _Styles,
    warnings: list[str],
    source: str,
) -> Table:
    column_count = max(len(row) for row in rows)
    data: list[list[Paragraph]] = []
    header_flags: list[bool] = []
    for row in rows:
        pdf_row: list[Paragraph] = []
        is_header = bool(row[0][1]) if row else False
        header_flags.append(is_header)
        for inline_token, cell_is_header, align in row:
            rendered = inline_to_pdf(
                inline_token,  # type: ignore[arg-type]
                warnings=warnings,
                source=source,
            )
            base = styles.table_header if cell_is_header else styles.table_cell
            alignment = {"left": TA_LEFT, "center": TA_CENTER, "right": TA_RIGHT}[
                align
            ]
            cell_style = ParagraphStyle(
                f"Cell-{alignment}-{'h' if cell_is_header else 'b'}",
                parent=base,
                alignment=alignment,
            )
            pdf_row.append(Paragraph(rendered, cell_style))
        while len(pdf_row) < column_count:
            pdf_row.append(Paragraph("", styles.table_cell))
        data.append(pdf_row)
    if not data:
        return Table([[""]])
    column_width = styles.text_width / column_count
    table = Table(
        data,
        colWidths=[column_width] * column_count,
        repeatRows=1 if header_flags and header_flags[0] else 0,
        hAlign="CENTER",
    )
    table_style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, TABLE_GRID),
        ("BOX", (0, 0), (-1, -1), 0.6, TABLE_GRID),
        ("FONTNAME", (0, 0), (-1, -1), SERIF),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    if header_flags and header_flags[0]:
        table_style.append(("BACKGROUND", (0, 0), (-1, 0), PAPER_TINT))
    for row_index, is_header in enumerate(header_flags):
        if is_header and row_index:
            table_style.append(("BACKGROUND", (0, row_index), (-1, row_index), PAPER_TINT))
    table.setStyle(TableStyle(table_style))
    return table


def _code_style(styles: _Styles, list_depth: int) -> ParagraphStyle:
    if not list_depth:
        return styles.code
    return ParagraphStyle(
        f"Code-{list_depth}",
        parent=styles.code,
        leftIndent=16 * list_depth,
        rightIndent=0,
    )


def _escape_code(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _plain_heading(inline_token: object) -> str:
    if inline_token is None or not getattr(inline_token, "children", None):
        return ""
    pieces: list[str] = []
    for child in inline_token.children:
        if child.type in {"text", "code_inline", "image"}:
            pieces.append(child.content)
        elif child.type in {"softbreak", "hardbreak"}:
            pieces.append(" ")
    return " ".join("".join(pieces).split())


def _wrap_text(
    text: str, font_name: str, font_size: float, max_width: float
) -> list[str]:
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    if stringWidth(current, font_name, font_size) > max_width:
        current = _split_long_word(current, font_name, font_size, max_width)
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            if stringWidth(word, font_name, font_size) > max_width:
                current = _split_long_word(word, font_name, font_size, max_width)
            else:
                current = word
    lines.append(current)
    return lines


def _split_long_word(
    word: str, font_name: str, font_size: float, max_width: float
) -> str:
    avg = max(stringWidth("M", font_name, font_size), 1)
    chars = max(1, int(max_width / avg))
    return textwrap.wrap(word, width=chars, break_long_words=True)[0]


def _padded_target(page_count: int, minimum: int) -> int:
    target = max(page_count, minimum)
    return target if target % 2 == 0 else target + 1


def _pad_pdf(data: bytes, target: int) -> tuple[bytes, int]:
    reader = PdfReader(io.BytesIO(data))
    missing = target - len(reader.pages)
    if missing <= 0:
        return data, 0
    writer = PdfWriter(clone_from=reader)
    page = reader.pages[0]
    width = float(page.mediabox.width)
    height = float(page.mediabox.height)
    for _ in range(missing):
        writer.add_blank_page(width=width, height=height)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue(), missing


def _dedupe(messages: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            result.append(message)
    return result
