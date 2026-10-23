from __future__ import annotations

import io
from decimal import Decimal

import pytest
from PIL import Image
from pypdf import PdfReader

from kdp_book_builder.book import load_book
from kdp_book_builder.cover import build_cover_wrap, render_ebook_cover
from kdp_book_builder.errors import BookBuilderError


def test_sample_cover_wrap_is_exact_kdp_size(sample_book, sample_cover) -> None:
    geometry = sample_cover.geometry
    assert geometry.spine_width_in == Decimal("0.0600")
    assert geometry.page_width_in == Decimal("12.3100")
    assert geometry.page_height_in == Decimal("9.2500")

    reader = PdfReader(io.BytesIO(sample_cover.wrap_pdf))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(12.31 * 72, abs=0.02)
    assert float(page.mediabox.height) == pytest.approx(9.25 * 72, abs=0.02)
    assert sample_cover.warnings == []


def test_cover_metadata_documents_page_count_and_spine(sample_book, sample_cover) -> None:
    reader = PdfReader(io.BytesIO(sample_cover.wrap_pdf))
    subject = reader.metadata.subject
    assert "24 pages" in subject
    assert "spine 0.06 in" in subject


def test_cover_pdfs_embed_all_fonts(sample_cover, unembedded_pdf_fonts) -> None:
    assert unembedded_pdf_fonts(sample_cover.wrap_pdf) == []
    assert unembedded_pdf_fonts(sample_cover.template_pdf) == []


def test_template_has_dimensions_and_spine_math(sample_cover) -> None:
    reader = PdfReader(io.BytesIO(sample_cover.template_pdf))
    page = reader.pages[0]
    assert float(page.mediabox.width) == pytest.approx(12.31 * 72, abs=0.02)
    assert float(page.mediabox.height) == pytest.approx(9.25 * 72, abs=0.02)
    text = " ".join(page.extract_text().split())
    assert "KDP PAPERBACK COVER WRAP" in text
    assert "24" in text
    assert "Spine: 0.06 in" in text
    assert "12.31 × 9.25 in" in text
    assert "KDP BARCODE AREA" in text
    assert "No spine text" in text
    assert "TRIM" not in text or "Trim line" in text


def test_template_is_not_the_designed_cover(sample_book, sample_cover) -> None:
    designed = " ".join(
        PdfReader(io.BytesIO(sample_cover.wrap_pdf)).pages[0].extract_text().split()
    )
    template = " ".join(
        PdfReader(io.BytesIO(sample_cover.template_pdf)).pages[0].extract_text().split()
    )
    assert sample_book.title in designed
    assert sample_book.title in template
    assert "FRONT COVER ARTWORK" in template
    assert "FRONT COVER ARTWORK" not in designed


def test_cover_rejects_page_count_below_paper_minimum(sample_book) -> None:
    with pytest.raises(BookBuilderError, match="at least 24 interior pages"):
        build_cover_wrap(sample_book, 10)


def test_spine_text_is_enabled_above_eighty_pages(sample_book) -> None:
    cover = build_cover_wrap(sample_book, 200)
    assert cover.geometry.spine_text_allowed
    assert cover.geometry.spine_width_in == Decimal("0.5000")
    assert float(
        PdfReader(io.BytesIO(cover.wrap_pdf)).pages[0].mediabox.width
    ) == pytest.approx((0.125 + 6 + 0.5 + 6 + 0.125) * 72, abs=0.02)


def test_cover_uses_other_paper_thickness(make_book) -> None:
    root = make_book(config={"paper": "white"})
    book = load_book(root)
    cover = build_cover_wrap(book, 100)
    assert cover.geometry.spine_width_in == Decimal("100") * book.paper.thickness_in
    text = " ".join(
        PdfReader(io.BytesIO(cover.template_pdf)).pages[0].extract_text().split()
    )
    assert "white paper" in text
    assert "0.2252 in" in text


def test_cover_artwork_is_used_without_warning(make_book) -> None:
    root = make_book(
        {
            "01-one.md": "# One\n\nWords.",
        }
    )
    art = Image.new("RGB", (1200, 1600), "#944E2D")
    art.save(root / "cover.jpg", format="JPEG")
    book = load_book(root, trim="6x9", paper="cream")
    # Editing the YAML is the simplest way to exercise the same public loader path.
    import yaml

    config = yaml.safe_load((root / "book.yaml").read_text(encoding="utf-8"))
    config["cover"] = {
        "background": "#17324D",
        "accent": "#E3B563",
        "text": "#FFF9EF",
        "tagline": "The friendly test.",
        "image": "cover.jpg",
    }
    (root / "book.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    book = load_book(root)
    cover = build_cover_wrap(book, 100)
    assert cover.geometry.page_count == 100
    assert cover.warnings == []
    assert PdfReader(io.BytesIO(cover.wrap_pdf)).pages


def test_ebook_cover_is_kdp_friendly_jpeg(sample_book) -> None:
    data, warnings = render_ebook_cover(sample_book)
    assert data[:2] == b"\xff\xd8"
    assert len(data) > 10_000
    assert warnings == []
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == "JPEG"
        assert image.size == (1600, 2560)
        assert image.mode == "RGB"


def test_ebook_cover_has_minimum_size_guard(sample_book) -> None:
    with pytest.raises(BookBuilderError, match="at least 600"):
        render_ebook_cover(sample_book, width=400, height=600)
