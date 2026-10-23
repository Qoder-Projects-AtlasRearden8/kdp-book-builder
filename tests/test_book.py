from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from kdp_book_builder.book import MarginOverrides, load_book
from kdp_book_builder.errors import BookBuilderError


def test_load_sample_book(sample_dir: Path) -> None:
    book = load_book(sample_dir)
    assert book.title == "The Friendly AI Field Guide"
    assert book.author == "Dylan Asdale"
    assert book.publisher == "ASDALE DYNAMICS, LLC"
    assert book.trim.key == "6x9"
    assert book.paper.key == "cream"
    assert book.cover.background == "#17324D"
    assert book.cover.tagline.startswith("Plain English")
    assert len(book.chapters) == 3
    assert [chapter.number for chapter in book.chapters] == [1, 2, 3]
    assert book.chapters[0].source.name.startswith("01-")
    assert book.chapters[2].title == "Ask Better Questions (Without Memorizing Prompts)"
    assert book.warnings == []


def test_chapter_files_are_naturally_sorted(make_book) -> None:
    root = make_book(
        {
            "chapter-10.md": "# Ten\n\nLast.",
            "chapter-2.md": "# Two\n\nSecond.",
            "chapter-1.md": "# One\n\nFirst.",
        }
    )
    book = load_book(root)
    assert [chapter.title for chapter in book.chapters] == ["One", "Two", "Ten"]


def test_explicit_chapter_list_controls_order(make_book) -> None:
    root = make_book(
        {
            "01-first.md": "# First\n\nOne.",
            "02-second.md": "# Second\n\nTwo.",
        },
        config={"chapters": ["chapters/02-second.md", "chapters/01-first.md"]},
    )
    book = load_book(root)
    assert [chapter.title for chapter in book.chapters] == ["Second", "First"]
    assert [chapter.number for chapter in book.chapters] == [1, 2]


def test_headings_become_unique_section_anchors(make_book) -> None:
    root = make_book(
        {
            "01-one.md": (
                "# Main\n\n"
                "## A Note\n\nText.\n\n"
                "## A Note\n\nMore.\n\n"
                "### Deep Idea\n\nDeeper."
            )
        }
    )
    book = load_book(root)
    sections = book.chapters[0].sections
    assert [(section.title, section.anchor) for section in sections] == [
        ("A Note", "a-note"),
        ("A Note", "a-note-2"),
        ("Deep Idea", "deep-idea"),
    ]


def test_missing_book_yaml_error(tmp_path: Path) -> None:
    with pytest.raises(BookBuilderError, match="No book.yaml"):
        load_book(tmp_path)


def test_empty_book_yaml_still_requires_title_and_author(tmp_path: Path) -> None:
    (tmp_path / "book.yaml").write_text("# nothing here\n", encoding="utf-8")
    with pytest.raises(BookBuilderError, match="title"):
        load_book(tmp_path)


def test_chapter_must_start_with_h1(make_book) -> None:
    root = make_book({"01-bad.md": "Just a paragraph.\n"})
    with pytest.raises(BookBuilderError, match="must start with a single"):
        load_book(root)


def test_chapter_cannot_have_second_h1(make_book) -> None:
    root = make_book({"01-bad.md": "# Good\n\n## Fine\n\n# Another title\n"})
    with pytest.raises(BookBuilderError, match="only one level-one heading"):
        load_book(root)


def test_empty_chapter_is_rejected(make_book) -> None:
    root = make_book({"01-empty.md": "   \n\n"})
    with pytest.raises(BookBuilderError, match="is empty"):
        load_book(root)


def test_top_level_config_typo_produces_warning(make_book) -> None:
    root = make_book(config={"trimm": "6x9"})
    book = load_book(root)
    assert any("ignored unknown setting" in warning for warning in book.warnings)


def test_unknown_cover_setting_is_error(make_book) -> None:
    root = make_book(
        config={"cover": {"background": "#112233", "sparkle": True}}
    )
    with pytest.raises(BookBuilderError, match="unknown setting"):
        load_book(root)


def test_cover_image_must_stay_inside_book_folder(make_book, tmp_path: Path) -> None:
    root = make_book(config={"cover": {"image": "../outside.jpg"}})
    (tmp_path / "outside.jpg").write_bytes(b"not really a jpeg")
    with pytest.raises(BookBuilderError, match="cover.image.*inside the book folder"):
        load_book(root)


def test_chapter_path_cannot_escape_book_folder(make_book) -> None:
    root = make_book(config={"chapters": "../outside"})
    with pytest.raises(BookBuilderError, match="chapter path must stay inside"):
        load_book(root)


def test_cover_image_extension_is_checked(make_book) -> None:
    root = make_book()
    (root / "cover.svg").write_text("<svg/>", encoding="utf-8")
    config = yaml.safe_load((root / "book.yaml").read_text(encoding="utf-8"))
    config["cover"] = {"image": "cover.svg"}
    (root / "book.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(BookBuilderError, match=r"\.jpg"):
        load_book(root)


def test_invalid_isbn_is_rejected(make_book) -> None:
    root = make_book(config={"isbn": "12345"})
    with pytest.raises(BookBuilderError, match="10- or 13-digit"):
        load_book(root)


def test_isbn_is_normalized(make_book) -> None:
    root = make_book(config={"isbn": "978-1-234-56789-7"})
    assert load_book(root).isbn == "9781234567897"


def test_invalid_hex_color_is_rejected(make_book) -> None:
    root = make_book(config={"cover": {"background": "navy"}})
    with pytest.raises(BookBuilderError, match="six-digit hex"):
        load_book(root)


def test_bad_margin_value_is_rejected(make_book) -> None:
    root = make_book(config={"margins": {"inside": "wide"}})
    with pytest.raises(BookBuilderError, match="must be a number"):
        load_book(root)


def test_cli_margin_overrides_merge_with_config(make_book) -> None:
    root = make_book(config={"margins": {"inside": "0.7", "top": "0.9"}})
    book = load_book(root, margins=MarginOverrides(outside=Decimal("0.8")))
    assert book.margins.inside == Decimal("0.7")
    assert book.margins.top == Decimal("0.9")
    assert book.margins.outside == Decimal("0.8")


def test_title_and_author_overrides(make_book) -> None:
    root = make_book()
    book = load_book(root, title="Proof Title", author="Proof Author")
    assert book.title == "Proof Title"
    assert book.author == "Proof Author"


def test_description_disclaimer_keywords_and_language(make_book) -> None:
    root = make_book(
        config={
            "language": "en-GB",
            "description": "A short description.",
            "disclaimer": "General information only.",
            "keywords": "one, two, three",
            "edition": "Second edition",
        }
    )
    book = load_book(root)
    assert book.language == "en-GB"
    assert book.description == "A short description."
    assert book.disclaimer == "General information only."
    assert book.keywords == ["one", "two", "three"]
    assert book.edition == "Second edition"


def test_non_markdown_chapter_in_list_is_rejected(make_book) -> None:
    root = make_book()
    (root / "chapters" / "notes.txt").write_text("hello", encoding="utf-8")
    config = yaml.safe_load((root / "book.yaml").read_text(encoding="utf-8"))
    config["chapters"] = ["chapters/notes.txt"]
    (root / "book.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(BookBuilderError, match=r"\.md or \.markdown"):
        load_book(root)
