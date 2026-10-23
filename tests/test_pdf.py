from __future__ import annotations

import io
from decimal import Decimal

import pytest
from pypdf import PdfReader

from kdp_book_builder.book import MarginOverrides, load_book
from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.pdf import PAGE_NUMBER_START, build_interior_pdf


def _text(page: object) -> str:
    return " ".join(page.extract_text().split())


def test_sample_interior_is_padded_even_and_page_sized(sample_interior) -> None:
    reader = PdfReader(io.BytesIO(sample_interior.data))
    assert sample_interior.page_count == len(reader.pages)
    assert sample_interior.page_count >= 24
    assert sample_interior.page_count % 2 == 0
    assert sample_interior.padded_pages > 0
    assert any("blank page" in warning for warning in sample_interior.warnings)

    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(6 * 72)
    assert float(page.mediabox.height) == pytest.approx(9 * 72)


def test_front_matter_and_contents_exist(sample_interior, sample_book) -> None:
    reader = PdfReader(io.BytesIO(sample_interior.data))
    title_page = _text(reader.pages[0])
    copyright_page = _text(reader.pages[1])
    contents = _text(reader.pages[2])
    assert sample_book.title in title_page
    assert sample_book.author.upper() in title_page
    assert "Copyright © 2026" in copyright_page
    assert sample_book.copyright_holder in copyright_page
    assert "Contents" in contents
    for chapter in sample_book.chapters:
        assert chapter.title in contents


def test_every_chapter_has_a_page_number_and_reported_start(
    sample_interior, sample_book
) -> None:
    reader = PdfReader(io.BytesIO(sample_interior.data))
    for chapter in sample_book.chapters:
        reported = next(
            item for item in sample_interior.chapters if item.number == chapter.number
        )
        assert reported.page >= PAGE_NUMBER_START
        lines = [
            line.strip()
            for line in reader.pages[reported.page - 1].extract_text().splitlines()
            if line.strip()
        ]
        page_text = " ".join(lines)
        assert chapter.title in page_text
        assert str(reported.page) in lines


def test_first_two_front_matter_pages_are_unnumbered(sample_interior) -> None:
    reader = PdfReader(io.BytesIO(sample_interior.data))
    for page in reader.pages[:2]:
        lines = [line.strip() for line in page.extract_text().splitlines() if line.strip()]
        assert lines[-1] not in {"1", "2"}


def test_pdf_outline_contains_chapters(sample_interior, sample_book) -> None:
    reader = PdfReader(io.BytesIO(sample_interior.data))
    outline = reader.outline
    assert outline
    flattened: list[str] = []

    def walk(items: list | object) -> None:
        if isinstance(items, list):
            for item in items:
                walk(item)
        elif hasattr(items, "title"):
            flattened.append(str(items.title))

    walk(outline)
    for chapter in sample_book.chapters:
        assert any(chapter.title in title for title in flattened)


def test_pdf_metadata_and_keywords(sample_interior, sample_book) -> None:
    reader = PdfReader(io.BytesIO(sample_interior.data))
    metadata = reader.metadata
    assert metadata.title == sample_book.title
    assert metadata.author == sample_book.author
    assert "prompt writing" in metadata.get("/Keywords", "")


def test_every_interior_font_is_embedded(sample_interior, unembedded_pdf_fonts) -> None:
    assert unembedded_pdf_fonts(sample_interior.data) == []


def test_manual_gutter_below_kdp_minimum_is_rejected(make_book) -> None:
    book = load_book(
        make_book(),
        margins=MarginOverrides(inside=Decimal("0.2")),
    )
    with pytest.raises(BookBuilderError, match="KDP requires"):
        build_interior_pdf(book)


def test_tiny_trim_with_large_margins_reports_clear_error(make_book) -> None:
    book = load_book(
        make_book(),
        trim="5x8",
        margins=MarginOverrides(
            inside=Decimal("2"),
            outside=Decimal("2"),
            top=Decimal("3"),
            bottom=Decimal("3"),
        ),
    )
    with pytest.raises(BookBuilderError, match="too little room"):
        build_interior_pdf(book)


def test_trim_override_changes_media_box(make_book) -> None:
    book = load_book(make_book(), trim="5.5x8.5")
    result = build_interior_pdf(book)
    page = PdfReader(io.BytesIO(result.data)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(5.5 * 72)
    assert float(page.mediabox.height) == pytest.approx(8.5 * 72)


def test_page_count_reflects_extra_content(make_book) -> None:
    short = build_interior_pdf(
        load_book(make_book({"01-short.md": "# Short\n\nOne line."}))
    )
    long_text = "# Long\n\n" + ("This is a longer paragraph for the page count. " * 500)
    long_book = load_book(
        make_book({"01-long.md": long_text}, folder="long-book")
    )
    long_result = build_interior_pdf(long_book)
    assert long_result.layout_page_count > short.layout_page_count
    assert long_result.page_count % 2 == 0


def test_chapter_with_image_renders_without_missing_file(make_book) -> None:
    from PIL import Image

    root = make_book(
        {
            "01-picture.md": (
                "# A Picture\n\nSome words.\n\n![A calm blue square](art.png)\n"
            )
        }
    )
    image = Image.new("RGB", (900, 600), "#2B5B7A")
    image.save(root / "chapters" / "art.png")
    book = load_book(root)
    result = build_interior_pdf(book)
    reader = PdfReader(io.BytesIO(result.data))
    full_text = " ".join(
        " ".join(page.extract_text().split()) for page in reader.pages
    )
    assert "A calm blue square" in full_text
    assert not any("skipped" in warning for warning in result.warnings)
