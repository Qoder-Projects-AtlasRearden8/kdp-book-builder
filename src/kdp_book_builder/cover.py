from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps
from reportlab.lib.colors import Color, HexColor
from reportlab.lib.units import inch
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from kdp_book_builder.book import Book
from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.fonts import (
    SANS,
    SANS_BOLD,
    SERIF_BOLD,
    SERIF_ITALIC,
    font_paths,
    register_fonts,
)
from kdp_book_builder.layout import (
    SPINE_TEXT_MIN_PAGES,
    CoverGeometry,
    cover_geometry,
    fmt_inches,
    validate_page_count,
)

WRAP_FILENAME = "-cover-wrap.pdf"
TEMPLATE_FILENAME = "-cover-template.pdf"
EBOOK_COVER_FILENAME = "-ebook-cover.jpg"

_GUIDE_TRIM = HexColor("#E0007A")
_GUIDE_SAFE = HexColor("#00A2C7")
_GUIDE_FOLD = HexColor("#D79500")
_GUIDE_BARCODE = HexColor("#33803B")
_TEMPLATE_PAPER = HexColor("#FCFAF5")
_TEMPLATE_PANEL = HexColor("#F2EDE4")
_TEMPLATE_INK = HexColor("#342F29")
_TEMPLATE_MUTED = HexColor("#6B6257")


@dataclass(frozen=True)
class CoverBuildResult:
    wrap_pdf: bytes
    template_pdf: bytes
    geometry: CoverGeometry
    warnings: list[str]


def build_cover_wrap(book: Book, page_count: int) -> CoverBuildResult:
    """Build a clean KDP-sized cover wrap and a matching guide template."""
    validate_page_count(page_count, book.paper, book.trim)
    register_fonts()
    geometry = cover_geometry(book.trim, book.paper, page_count)
    warnings: list[str] = []
    wrap = _render_design(book, geometry, warnings)
    template = _render_template(book, geometry)
    return CoverBuildResult(
        wrap_pdf=wrap,
        template_pdf=template,
        geometry=geometry,
        warnings=warnings,
    )


def build_cover_wrap_pdf(book: Book, page_count: int) -> bytes:
    return build_cover_wrap(book, page_count).wrap_pdf


def build_cover_template_pdf(book: Book, page_count: int) -> bytes:
    return build_cover_wrap(book, page_count).template_pdf


def render_ebook_cover(
    book: Book, *, width: int = 1600, height: int = 2560
) -> tuple[bytes, list[str]]:
    """Render a KDP-friendly 1,600 × 2,560 JPEG cover."""
    if width < 600 or height < 900:
        raise BookBuilderError("The ebook cover must be at least 600 × 900 pixels.")
    warnings: list[str] = []
    bg = _pil_hex(book.cover.background)
    accent = _pil_hex(book.cover.accent)
    ink = _pil_hex(book.cover.text)
    image = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(image, "RGBA")

    image_bottom = int(height * 0.49)
    artwork = _load_artwork(book.cover.image, warnings)
    if artwork is not None:
        fitted = ImageOps.fit(
            artwork.convert("RGB"),
            (width, image_bottom),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.45),
        )
        image.paste(fitted, (0, 0))
        _fade_to_color(image, image_bottom, bg)
        draw = ImageDraw.Draw(image, "RGBA")
        draw.rectangle((0, 0, width, image_bottom), fill=(*bg, 72))
    else:
        _pil_artwork_shapes(draw, width, height, bg, accent, image_bottom)

    # A slim accent rule gives the generated cover a recognizable series look.
    draw.rectangle((width // 2 - 130, int(height * 0.105), width // 2 + 130, int(height * 0.105) + 5), fill=accent)

    paths = font_paths()
    if book.cover.tagline:
        tagline_font = _pil_font(paths.sans_bold, 33)
        tagline = book.cover.tagline.upper()
        while draw.textlength(tagline, font=tagline_font) > width * 0.78 and tagline_font.size > 22:
            tagline_font = _pil_font(paths.sans_bold, tagline_font.size - 1)
        draw.text(
            (width / 2, int(height * 0.125) + 30),
            tagline,
            font=tagline_font,
            fill=accent,
            anchor="ma",
        )

    if book.publisher:
        publisher_font = _pil_font(paths.sans_bold, 26)
        draw.text(
            (width / 2, int(height * 0.055)),
            book.publisher.upper(),
            font=publisher_font,
            fill=ink,
            anchor="ma",
        )

    title_font, title_lines = _fit_pil_lines(
        draw,
        book.title,
        paths.serif_bold,
        start_size=174,
        min_size=98,
        max_width=int(width * 0.83),
        max_lines=4,
    )
    line_height = int(title_font.size * 1.12)
    block_height = line_height * len(title_lines)
    title_center = int(height * 0.63) - block_height // 2
    y = title_center
    for line in title_lines:
        draw.text((width / 2, y), line, font=title_font, fill=ink, anchor="ma")
        y += line_height

    divider_y = y + 34
    draw.rectangle((width // 2 - 92, divider_y, width // 2 + 92, divider_y + 5), fill=accent)

    subtitle_y = divider_y + 42
    if book.subtitle:
        subtitle_font, subtitle_lines = _fit_pil_lines(
            draw,
            book.subtitle,
            paths.serif_italic,
            start_size=50,
            min_size=34,
            max_width=int(width * 0.76),
            max_lines=3,
        )
        for line in subtitle_lines:
            draw.text(
                (width / 2, subtitle_y),
                line,
                font=subtitle_font,
                fill=ink,
                anchor="ma",
            )
            subtitle_y += int(subtitle_font.size * 1.22)

    author_font, author_lines = _fit_pil_lines(
        draw,
        book.author.upper(),
        paths.sans_bold,
        start_size=40,
        min_size=26,
        max_width=int(width * 0.82),
        max_lines=2,
    )
    author_y = int(height * 0.865)
    for line in author_lines:
        draw.text(
            (width / 2, author_y),
            line,
            font=author_font,
            fill=ink,
            anchor="ma",
        )
        author_y += int(author_font.size * 1.25)

    bottom_font = _pil_font(paths.sans, 22)
    footer = "A FIELD GUIDE" if "field guide" in (book.subtitle or "").lower() else ""
    if book.edition:
        footer = f"{footer}  ·  {book.edition}" if footer else book.edition
    if footer:
        draw.text(
            (width / 2, int(height * 0.955)),
            footer.upper(),
            font=bottom_font,
            fill=(*ink, 210),
            anchor="ma",
        )

    output = io.BytesIO()
    image.save(
        output,
        format="JPEG",
        quality=92,
        optimize=True,
        progressive=True,
    )
    return output.getvalue(), warnings


def _render_design(
    book: Book, geometry: CoverGeometry, warnings: list[str]
) -> bytes:
    width = float(geometry.page_width_in) * inch
    height = float(geometry.page_height_in) * inch
    buffer = io.BytesIO()
    canvas = Canvas(
        buffer,
        pagesize=(width, height),
        pageCompression=1,
        initialFontName=SANS,
        initialFontSize=12,
        initialLeading=14.4,
    )
    canvas.setTitle(f"{book.title} — paperback cover wrap")
    canvas.setAuthor(book.author)
    canvas.setSubject(
        f"KDP cover wrap: {geometry.page_count} pages, "
        f"{geometry.paper.label.lower()}, spine {fmt_inches(geometry.spine_width_in, 4)}"
    )
    canvas.setCreator("kdp-book-builder")

    bg = _hex(book.cover.background)
    accent = _hex(book.cover.accent)
    ink = _hex(book.cover.text)
    bleed = float(geometry.bleed_in) * inch
    trim_width = float(geometry.trim.width_in) * inch
    trim_height = float(geometry.trim.height_in) * inch
    spine_left = float(geometry.spine_left_in) * inch
    spine_right = float(geometry.front_left_in) * inch
    spine_width = float(geometry.spine_width_in) * inch
    panel_bottom = bleed
    panel_top = bleed + trim_height

    canvas.setFillColor(bg)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    _draw_background_texture(canvas, width, height, geometry, bg, accent)

    _draw_back_panel(
        canvas,
        book,
        geometry,
        left=bleed,
        bottom=panel_bottom,
        width=trim_width,
        height=trim_height,
        bg=bg,
        accent=accent,
        ink=ink,
    )

    if spine_width > 0:
        canvas.saveState()
        canvas.setFillColor(_mix(bg, accent, 0.08))
        canvas.rect(spine_left, panel_bottom, spine_width, trim_height, stroke=0, fill=1)
        canvas.restoreState()
        _draw_spine(canvas, book, geometry, ink)
        canvas.saveState()
        canvas.setStrokeColor(_with_alpha(accent, 0.45))
        canvas.setLineWidth(0.6)
        canvas.line(spine_left, panel_bottom + 0.18 * inch, spine_left, panel_top - 0.18 * inch)
        canvas.line(spine_right, panel_bottom + 0.18 * inch, spine_right, panel_top - 0.18 * inch)
        canvas.restoreState()

    _draw_front_panel(
        canvas,
        book,
        geometry,
        left=spine_right,
        bottom=panel_bottom,
        width=trim_width,
        height=trim_height,
        bleed=bleed,
        bg=bg,
        accent=accent,
        ink=ink,
        warnings=warnings,
    )

    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _draw_background_texture(
    canvas: Canvas,
    width: float,
    height: float,
    geometry: CoverGeometry,
    bg: Color,
    accent: Color,
) -> None:
    canvas.saveState()
    canvas.setFillColor(_with_alpha(accent, 0.055))
    canvas.circle(width * 0.09, height * 0.87, float(geometry.trim.height_in) * inch * 0.38, stroke=0, fill=1)
    canvas.setFillColor(_with_alpha(accent, 0.04))
    canvas.circle(width * 0.94, height * 0.2, float(geometry.trim.height_in) * inch * 0.3, stroke=0, fill=1)
    canvas.setStrokeColor(_with_alpha(accent, 0.13))
    canvas.setLineWidth(1)
    canvas.circle(width * 0.09, height * 0.87, float(geometry.trim.height_in) * inch * 0.46, stroke=1, fill=0)
    canvas.restoreState()


def _draw_back_panel(
    canvas: Canvas,
    book: Book,
    geometry: CoverGeometry,
    *,
    left: float,
    bottom: float,
    width: float,
    height: float,
    bg: Color,
    accent: Color,
    ink: Color,
) -> None:
    x = left + 0.55 * inch
    content_width = width - 1.1 * inch
    top = bottom + height - 0.62 * inch

    if book.publisher:
        canvas.setFont(SANS_BOLD, 8.2)
        canvas.setFillColor(_with_alpha(ink, 0.76))
        canvas.drawString(x, top, book.publisher.upper())
        top -= 12
    canvas.setStrokeColor(_with_alpha(accent, 0.8))
    canvas.setLineWidth(1.1)
    canvas.line(x, top, x + 0.72 * inch, top)
    top -= 0.38 * inch

    body = book.description or book.subtitle or book.cover.tagline
    if body:
        body_size = 9.6
        leading = 14.8
        lines = _wrap_lines(body, SANS, body_size, content_width)
        reserved_bottom = bottom + 1.97 * inch
        max_lines = max(1, int((top - reserved_bottom) / leading))
        for line in lines[:max_lines]:
            canvas.setFont(SANS, body_size)
            canvas.setFillColor(_with_alpha(ink, 0.9))
            canvas.drawString(x, top, line)
            top -= leading
        if len(lines) > max_lines:
            canvas.setFont(SERIF_ITALIC, 8.4)
            canvas.setFillColor(_with_alpha(ink, 0.66))
            canvas.drawString(x, top - 5, "Learn more inside.")
            top -= 19

    if book.cover.tagline:
        tagline_y = max(bottom + 1.4 * inch, top - 0.28 * inch)
        canvas.setFont(SERIF_ITALIC, 9.1)
        canvas.setFillColor(_with_alpha(accent, 0.96))
        tagline_lines = _wrap_lines(
            book.cover.tagline, SERIF_ITALIC, 9.1, content_width
        )
        for line in tagline_lines[:2]:
            canvas.drawString(x, tagline_y, line)
            tagline_y -= 12.5

    if book.isbn:
        canvas.setFont(SANS, 7.6)
        canvas.setFillColor(_with_alpha(ink, 0.62))
        canvas.drawString(x, bottom + 1.04 * inch, f"ISBN {book.isbn}")

    canvas.setFont(SANS_BOLD, 7.7)
    canvas.setFillColor(_with_alpha(ink, 0.74))
    author_y = bottom + 0.72 * inch
    canvas.drawString(x, author_y, book.author.upper())
    if book.publisher:
        canvas.setFont(SANS, 7.1)
        canvas.setFillColor(_with_alpha(ink, 0.5))
        canvas.drawString(x, author_y - 12, book.publisher)

    barcode_x = float(geometry.barcode_x_in) * inch
    barcode_y = float(geometry.barcode_y_in) * inch
    barcode_w = float(geometry.barcode_width_in) * inch
    barcode_h = float(geometry.barcode_height_in) * inch
    canvas.setFillColor(_hex("#FFFFFF"))
    canvas.rect(barcode_x, barcode_y, barcode_w, barcode_h, stroke=0, fill=1)


def _draw_spine(
    canvas: Canvas, book: Book, geometry: CoverGeometry, ink: Color
) -> None:
    if not geometry.spine_text_allowed:
        return
    spine_width = float(geometry.spine_width_in) * inch
    if spine_width < 0.15 * inch:
        return
    left = float(geometry.spine_left_in) * inch
    trim_height = float(geometry.trim.height_in) * inch
    page_height = float(geometry.page_height_in) * inch
    available = trim_height - 0.8 * inch
    labels = [f"{book.title}  ·  {book.author}", book.title, book.author]
    text = ""
    font_size = min(8.4, max(5.5, spine_width - 1.5))
    combined = labels[0]
    if stringWidth(combined, SANS_BOLD, font_size) <= available:
        text = combined
    elif stringWidth(labels[1], SANS_BOLD, font_size) <= available:
        text = labels[1]
    elif stringWidth(labels[2], SANS_BOLD, font_size) <= available:
        text = labels[2]
    if not text:
        return
    canvas.saveState()
    canvas.setFillColor(ink)
    canvas.setFont(SANS_BOLD, font_size)
    canvas.translate(left + spine_width / 2, page_height / 2)
    canvas.rotate(-90)
    canvas.drawCentredString(0, -font_size * 0.34, text)
    canvas.restoreState()


def _draw_front_panel(
    canvas: Canvas,
    book: Book,
    geometry: CoverGeometry,
    *,
    left: float,
    bottom: float,
    width: float,
    height: float,
    bleed: float,
    bg: Color,
    accent: Color,
    ink: Color,
    warnings: list[str],
) -> None:
    top = bottom + height
    margin = 0.56 * inch
    content_x = left + margin
    content_width = width - 2 * margin
    image_bottom = bottom + height * 0.52

    if book.cover.image is not None:
        if _draw_artwork(
            canvas,
            book.cover.image,
            left,
            image_bottom,
            width + bleed,
            height - height * 0.52 + bleed,
            warnings,
        ):
            canvas.saveState()
            canvas.setFillColor(_with_alpha(bg, 0.46))
            canvas.rect(left, image_bottom, width + bleed, top + bleed - image_bottom, stroke=0, fill=1)
            canvas.restoreState()
    else:
        canvas.saveState()
        canvas.setFillColor(_with_alpha(accent, 0.12))
        canvas.circle(left + width * 0.82, top - height * 0.18, width * 0.33, stroke=0, fill=1)
        canvas.setStrokeColor(_with_alpha(accent, 0.32))
        canvas.setLineWidth(1)
        canvas.circle(left + width * 0.82, top - height * 0.18, width * 0.4, stroke=1, fill=0)
        canvas.restoreState()

    canvas.setFont(SANS_BOLD, 7.9)
    canvas.setFillColor(_with_alpha(ink, 0.76))
    canvas.drawString(content_x, top - 0.56 * inch, (book.author or "").upper())

    if book.cover.tagline:
        canvas.setFont(SANS_BOLD, 7.8)
        canvas.setFillColor(accent)
        canvas.drawString(
            content_x, top - height * 0.26, book.cover.tagline.upper()
        )

    title_top = top - height * 0.33
    max_title_bottom = bottom + 1.94 * inch
    title_size = 33.0 if width < 5.5 * inch else 37.0
    title_lines, title_size, clipped = _fit_pdf_lines(
        book.title,
        SERIF_BOLD,
        title_size,
        min_size=20.0,
        max_width=content_width,
        max_lines=5,
    )
    if clipped:
        warnings.append(
            "The cover title is very long and was shortened with an ellipsis. "
            "Use a shorter display title or adjust the cover artwork."
        )
    leading = title_size * 1.14
    while title_top - len(title_lines) * leading < max_title_bottom and title_size > 20:
        title_size -= 1
        leading = title_size * 1.14
        title_lines, _, clipped = _fit_pdf_lines(
            book.title,
            SERIF_BOLD,
            title_size,
            min_size=20.0,
            max_width=content_width,
            max_lines=5,
        )
    canvas.setFont(SERIF_BOLD, title_size)
    canvas.setFillColor(ink)
    y = title_top
    for line in title_lines:
        canvas.drawString(content_x, y, line)
        y -= leading

    line_y = y + leading - 0.17 * inch
    canvas.setStrokeColor(accent)
    canvas.setLineWidth(1.25)
    canvas.line(content_x, line_y, content_x + 0.62 * inch, line_y)

    subtitle_y = line_y - 0.29 * inch
    if book.subtitle:
        subtitle_size = 11.8 if width < 5.5 * inch else 12.6
        subtitle_lines = _wrap_lines(
            book.subtitle, SERIF_ITALIC, subtitle_size, content_width * 0.94
        )
        canvas.setFont(SERIF_ITALIC, subtitle_size)
        canvas.setFillColor(_with_alpha(ink, 0.82))
        for line in subtitle_lines[:3]:
            canvas.drawString(content_x, subtitle_y, line)
            subtitle_y -= subtitle_size * 1.32

    canvas.setStrokeColor(_with_alpha(accent, 0.72))
    canvas.setLineWidth(0.7)
    canvas.line(
        content_x,
        bottom + 0.82 * inch,
        content_x + content_width,
        bottom + 0.82 * inch,
    )
    canvas.setFont(SANS_BOLD, 8.1)
    canvas.setFillColor(_with_alpha(ink, 0.74))
    edition = book.edition.upper() if book.edition else "A PAPERBACK EDITION"
    canvas.drawString(content_x, bottom + 0.53 * inch, edition)


def _draw_artwork(
    canvas: Canvas,
    path: Path,
    left: float,
    bottom: float,
    width: float,
    height: float,
    warnings: list[str],
) -> bool:
    try:
        reader = ImageReader(str(path))
        image_width, image_height = reader.getSize()
    except Exception:
        warnings.append(
            f"Cover image {path.name} could not be read. The cover used the color "
            "design instead; use a valid PNG or JPEG."
        )
        return False
    if image_width <= 0 or image_height <= 0:
        return False
    scale = max(width / image_width, height / image_height)
    draw_width = image_width * scale
    draw_height = image_height * scale
    x = left + (width - draw_width) / 2
    y = bottom + (height - draw_height) / 2
    canvas.saveState()
    clip = canvas.beginPath()
    clip.rect(left, bottom, width, height)
    canvas.clipPath(clip, stroke=0, fill=0)
    try:
        canvas.drawImage(
            reader,
            x,
            y,
            width=draw_width,
            height=draw_height,
            mask="auto",
        )
    except Exception:
        canvas.restoreState()
        warnings.append(
            f"Cover image {path.name} is not a format ReportLab can place. "
            "Use a standard PNG or JPEG."
        )
        return False
    canvas.restoreState()
    return True


def _render_template(book: Book, geometry: CoverGeometry) -> bytes:
    width = float(geometry.page_width_in) * inch
    height = float(geometry.page_height_in) * inch
    bleed = float(geometry.bleed_in) * inch
    trim_width = float(geometry.trim.width_in) * inch
    trim_height = float(geometry.trim.height_in) * inch
    safe = float(geometry.safe_inset_in) * inch
    spine_left = float(geometry.spine_left_in) * inch
    spine_right = float(geometry.front_left_in) * inch
    spine_width = float(geometry.spine_width_in) * inch
    bottom = bleed
    top = bleed + trim_height

    buffer = io.BytesIO()
    canvas = Canvas(
        buffer,
        pagesize=(width, height),
        pageCompression=1,
        initialFontName=SANS,
        initialFontSize=12,
        initialLeading=14.4,
    )
    canvas.setTitle(f"{book.title} — cover wrap template")
    canvas.setAuthor(book.author)
    canvas.setSubject(
        "KDP cover wrap guide. Remove guide marks before submitting final artwork."
    )
    canvas.setCreator("kdp-book-builder")

    canvas.setFillColor(_TEMPLATE_PAPER)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setFillColor(_TEMPLATE_PANEL)
    canvas.rect(bleed, bottom, trim_width, trim_height, stroke=0, fill=1)
    canvas.rect(spine_right, bottom, trim_width, trim_height, stroke=0, fill=1)
    if spine_width > 0:
        canvas.setFillColor(HexColor("#E9E1D4"))
        canvas.rect(spine_left, bottom, spine_width, trim_height, stroke=0, fill=1)

    # Back-cover measurement sheet.
    x = bleed + 0.48 * inch
    y = top - 0.48 * inch
    max_width = trim_width - 0.96 * inch
    canvas.setFillColor(_TEMPLATE_INK)
    canvas.setFont(SANS_BOLD, 8)
    canvas.drawString(x, y, "KDP PAPERBACK COVER WRAP")
    y -= 20
    canvas.setFont(SERIF_BOLD, 17)
    title_lines = _wrap_lines(book.title, SERIF_BOLD, 17, max_width)
    for line in title_lines[:3]:
        canvas.drawString(x, y, line)
        y -= 20
    y -= 3
    canvas.setFont(SANS, 8.4)
    canvas.setFillColor(_TEMPLATE_MUTED)
    for line in _wrap_lines(book.author, SANS, 8.4, max_width)[:2]:
        canvas.drawString(x, y, line)
        y -= 12
    y -= 6
    canvas.setStrokeColor(HexColor("#B8AA91"))
    canvas.setLineWidth(0.7)
    canvas.line(x, y, x + 0.9 * inch, y)
    y -= 24

    details = [
        f"Trim size: {geometry.trim.display}",
        f"Pages: {geometry.page_count}",
        f"Paper: {geometry.paper.label} ({_decimal_text(geometry.paper.thickness_in)} in/page)",
        f"Spine: {fmt_inches(geometry.spine_width_in)}"
        f"  ({geometry.page_count} pages × {_decimal_text(geometry.paper.thickness_in)} in)",
        f"Full wrap: {_decimal_text(geometry.page_width_in)} × "
        f"{_decimal_text(geometry.page_height_in)} in (with {fmt_inches(bleed / inch)} bleed)",
        "Barcode: 2 × 1.2 in clear area, 0.25 in from trim edges",
    ]
    for detail in details:
        canvas.setFont(SANS, 8.0)
        canvas.setFillColor(_TEMPLATE_INK)
        for line in _wrap_lines(detail, SANS, 8.0, max_width):
            canvas.drawString(x, y, line)
            y -= 11.6
        y -= 3.5

    y -= 4
    canvas.setFont(SANS_BOLD, 7.4)
    canvas.setFillColor(_TEMPLATE_MUTED)
    if geometry.spine_text_allowed:
        spine_note = (
            f"Spine text is allowed from {SPINE_TEXT_MIN_PAGES} pages. "
            "Keep it at least 0.0625 in from each spine fold."
        )
    else:
        spine_note = (
            f"No spine text: KDP books under {SPINE_TEXT_MIN_PAGES} pages "
            "must keep the spine clear."
        )
    for line in _wrap_lines(spine_note, SANS_BOLD, 7.4, max_width):
        canvas.drawString(x, y, line)
        y -= 10.5

    # Legend.
    legend_y = bottom + 0.62 * inch
    _legend_item(canvas, x, legend_y, _GUIDE_TRIM, "Trim line")
    _legend_item(canvas, x + 1.0 * inch, legend_y, _GUIDE_SAFE, "Safe text area")
    _legend_item(canvas, x + 2.1 * inch, legend_y, _GUIDE_FOLD, "Spine fold")
    _legend_item(canvas, x + 3.15 * inch, legend_y, _GUIDE_BARCODE, "Barcode clear zone")
    canvas.setFont(SANS, 6.7)
    canvas.setFillColor(_TEMPLATE_MUTED)
    canvas.drawString(
        x,
        legend_y - 15,
        "Guides sit above the layout. Use this sheet as a measuring guide, not final artwork.",
    )

    # Guides.
    canvas.saveState()
    canvas.setStrokeColor(_GUIDE_TRIM)
    canvas.setLineWidth(0.8)
    canvas.setDash(4, 3)
    canvas.rect(bleed, bottom, 2 * trim_width + spine_width, trim_height)
    canvas.setStrokeColor(_GUIDE_SAFE)
    canvas.setDash(2, 3)
    canvas.rect(bleed + safe, bottom + safe, trim_width - 2 * safe, trim_height - 2 * safe)
    canvas.rect(
        spine_right + safe,
        bottom + safe,
        trim_width - 2 * safe,
        trim_height - 2 * safe,
    )
    canvas.setStrokeColor(_GUIDE_FOLD)
    canvas.setDash(5, 3)
    canvas.line(spine_left, bottom, spine_left, top)
    canvas.line(spine_right, bottom, spine_right, top)
    canvas.restoreState()

    # Barcode clear zone.
    barcode_x = float(geometry.barcode_x_in) * inch
    barcode_y = float(geometry.barcode_y_in) * inch
    barcode_w = float(geometry.barcode_width_in) * inch
    barcode_h = float(geometry.barcode_height_in) * inch
    canvas.setFillColor(HexColor("#FFFFFF"))
    canvas.setStrokeColor(_GUIDE_BARCODE)
    canvas.setDash(3, 2)
    canvas.rect(barcode_x, barcode_y, barcode_w, barcode_h, stroke=1, fill=1)
    canvas.setDash()
    canvas.setFillColor(_TEMPLATE_MUTED)
    canvas.setFont(SANS_BOLD, 6.3)
    canvas.drawCentredString(
        barcode_x + barcode_w / 2,
        barcode_y + barcode_h / 2 + 5,
        "KDP BARCODE AREA",
    )
    canvas.setFont(SANS, 6.1)
    canvas.drawCentredString(
        barcode_x + barcode_w / 2,
        barcode_y + barcode_h / 2 - 5,
        "2 × 1.2 in · keep clear",
    )

    # Panel labels and a roomy front-cover placeholder.
    canvas.setFillColor(_TEMPLATE_MUTED)
    canvas.setFont(SANS_BOLD, 7.2)
    canvas.drawCentredString(
        bleed + trim_width / 2, top - 0.22 * inch, "BACK COVER"
    )
    front_center = spine_right + trim_width / 2
    canvas.drawCentredString(front_center, top - 0.22 * inch, "FRONT COVER")
    if spine_width >= 0.36 * inch:
        canvas.saveState()
        canvas.translate(spine_left + spine_width / 2, bottom + trim_height / 2)
        canvas.rotate(90)
        canvas.setFont(SANS_BOLD, min(7.0, spine_width - 0.08 * inch))
        canvas.drawCentredString(0, 0, "SPINE")
        canvas.restoreState()
    else:
        canvas.setFont(SANS, 6.2)
        canvas.drawString(
            bleed + 0.06 * inch,
            bottom + trim_height + 0.032 * inch,
            f"Spine {fmt_inches(geometry.spine_width_in)}",
        )

    front_x = spine_right + safe + 0.1 * inch
    front_w = trim_width - 2 * safe - 0.2 * inch
    placeholder_top = top - 0.46 * inch
    placeholder_bottom = bottom + 0.46 * inch
    canvas.setStrokeColor(_GUIDE_SAFE)
    canvas.setDash(2, 4)
    canvas.roundRect(
        front_x,
        placeholder_bottom,
        front_w,
        placeholder_top - placeholder_bottom,
        8,
        stroke=1,
        fill=0,
    )
    canvas.setDash()
    canvas.setFillColor(_TEMPLATE_MUTED)
    canvas.setFont(SANS_BOLD, 9.2)
    canvas.drawCentredString(
        front_center, bottom + trim_height * 0.54, "FRONT COVER ARTWORK"
    )
    canvas.setFont(SANS, 7.6)
    canvas.drawCentredString(
        front_center,
        bottom + trim_height * 0.54 - 16,
        "Place title, author, and artwork inside the cyan safe guides.",
    )

    canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def _legend_item(canvas: Canvas, x: float, y: float, color: Color, label: str) -> None:
    canvas.saveState()
    canvas.setStrokeColor(color)
    canvas.setLineWidth(1.2)
    canvas.setDash(3, 2)
    canvas.line(x, y + 2.4, x + 14, y + 2.4)
    canvas.restoreState()
    canvas.setFillColor(_TEMPLATE_MUTED)
    canvas.setFont(SANS, 6.5)
    canvas.drawString(x + 18, y, label)


def _load_artwork(path: Path | None, warnings: list[str]) -> Image.Image | None:
    if path is None:
        return None
    try:
        with Image.open(path) as source:
            return source.convert("RGB")
    except Exception:
        warnings.append(
            f"Cover image {path.name} could not be read for the ebook cover. "
            "A typographic cover was generated instead."
        )
        return None


def _fade_to_color(
    image: Image.Image, bottom_y: int, color: tuple[int, int, int]
) -> None:
    width, _height = image.size
    start = int(bottom_y * 0.55)
    overlay = Image.new("RGBA", image.size, (*color, 0))
    pixels = overlay.load()
    for y in range(start, bottom_y):
        ratio = (y - start) / max(1, bottom_y - start)
        alpha = int(255 * min(1.0, ratio * 1.15))
        for x in range(width):
            pixels[x, y] = (*color, alpha)
    image.paste(Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB"), (0, 0))


def _pil_artwork_shapes(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    bg: tuple[int, int, int],
    accent: tuple[int, int, int],
    image_bottom: int,
) -> None:
    draw.ellipse(
        (width * 0.54, -height * 0.08, width * 1.13, image_bottom * 0.9),
        outline=(*accent, 52),
        width=3,
    )
    draw.ellipse(
        (width * 0.64, height * 0.02, width * 1.18, image_bottom * 1.03),
        outline=(*accent, 30),
        width=2,
    )
    draw.ellipse(
        (width * 0.08, image_bottom * 0.2, width * 0.44, image_bottom * 0.72),
        fill=(*accent, 18),
    )
    # Fine rules add texture without requiring an external illustration.
    for index in range(5):
        y = int(image_bottom * (0.28 + index * 0.04))
        draw.line(
            (int(width * 0.1), y, int(width * 0.42), y),
            fill=(*accent, 24),
            width=2,
        )


def _wrap_lines(
    text: str, font_name: str, font_size: float, max_width: float
) -> list[str]:
    text = " ".join(str(text).split())
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_pdf_lines(
    text: str,
    font_name: str,
    start_size: float,
    *,
    min_size: float,
    max_width: float,
    max_lines: int,
) -> tuple[list[str], float, bool]:
    size = start_size
    last_lines: list[str] = []
    while size >= min_size:
        lines = _wrap_lines(text, font_name, size, max_width)
        last_lines = lines
        if len(lines) <= max_lines:
            return lines, size, False
        size -= 1
    lines = last_lines[:max_lines]
    if lines:
        lines[-1] = _ellipsize(lines[-1], font_name, size, max_width)
    return lines, min_size, True


def _ellipsize(
    text: str, font_name: str, font_size: float, max_width: float
) -> str:
    suffix = "…"
    candidate = text
    while candidate and stringWidth(candidate + suffix, font_name, font_size) > max_width:
        candidate = candidate[:-1]
    return candidate.rstrip() + suffix


def _fit_pil_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    *,
    start_size: int,
    min_size: int,
    max_width: int,
    max_lines: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = start_size
    font = _pil_font(font_path, size)
    lines = _pil_wrap(draw, text, font, max_width)
    while len(lines) > max_lines and size > min_size:
        size = max(min_size, size - 4)
        font = _pil_font(font_path, size)
        lines = _pil_wrap(draw, text, font, max_width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines:
            last = lines[-1]
            suffix = "…"
            while last and draw.textlength(last + suffix, font=font) > max_width:
                last = last[:-1]
            lines[-1] = last.rstrip() + suffix
    return font, lines


def _pil_wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    text = " ".join(str(text).split())
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _pil_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except OSError as exc:
        raise BookBuilderError(
            f"Could not load the bundled font {path.name}. Reinstall the package."
        ) from exc


def _pil_hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _hex(value: str) -> Color:
    return HexColor(value)


def _with_alpha(color: Color, alpha: float) -> Color:
    return Color(color.red, color.green, color.blue, alpha=alpha)


def _mix(first: Color, second: Color, amount: float) -> Color:
    amount = min(1.0, max(0.0, amount))
    return Color(
        first.red * (1 - amount) + second.red * amount,
        first.green * (1 - amount) + second.green * amount,
        first.blue * (1 - amount) + second.blue * amount,
    )


def _decimal_text(value: object) -> str:
    text = f"{value:f}" if hasattr(value, "quantize") else str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text
