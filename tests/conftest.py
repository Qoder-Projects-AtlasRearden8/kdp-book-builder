from __future__ import annotations

import io
from pathlib import Path

import pytest
import yaml
from pypdf import PdfReader

from kdp_book_builder.book import Book, load_book
from kdp_book_builder.cover import CoverBuildResult, build_cover_wrap
from kdp_book_builder.epub import EpubBuildResult, build_epub
from kdp_book_builder.pdf import PdfBuildResult, build_interior_pdf

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_DIR = ROOT / "sample_book"


@pytest.fixture(scope="session")
def sample_dir() -> Path:
    return SAMPLE_DIR


@pytest.fixture
def sample_book() -> Book:
    return load_book(SAMPLE_DIR)


@pytest.fixture(scope="session")
def sample_interior() -> PdfBuildResult:
    return build_interior_pdf(load_book(SAMPLE_DIR))


@pytest.fixture(scope="session")
def sample_cover(sample_interior: PdfBuildResult) -> CoverBuildResult:
    return build_cover_wrap(load_book(SAMPLE_DIR), sample_interior.page_count)


@pytest.fixture(scope="session")
def sample_epub() -> EpubBuildResult:
    return build_epub(load_book(SAMPLE_DIR))


@pytest.fixture
def unembedded_pdf_fonts():
    """Return a checker listing fonts that KDP could reject as unembedded."""

    def _check(data: bytes) -> list[str]:
        missing: list[str] = []
        for page_number, page in enumerate(
            PdfReader(io.BytesIO(data)).pages, start=1
        ):
            resources = page.get("/Resources")
            if resources is None:
                continue
            fonts = resources.get_object().get("/Font", {})
            if hasattr(fonts, "get_object"):
                fonts = fonts.get_object()
            for reference in fonts.values():
                font = reference.get_object()
                descriptor = font.get("/FontDescriptor")
                if descriptor is None:
                    descendants = font.get("/DescendantFonts")
                    if descendants:
                        descendant = descendants[0].get_object()
                        descriptor = descendant.get("/FontDescriptor")
                embedded = False
                if descriptor is not None:
                    descriptor = descriptor.get_object()
                    embedded = any(
                        key in descriptor
                        for key in ("/FontFile", "/FontFile2", "/FontFile3")
                    )
                if not embedded:
                    missing.append(
                        f"page {page_number}: {font.get('/BaseFont')}"
                    )
        return missing

    return _check


@pytest.fixture
def make_book(tmp_path: Path):
    """Create a valid minimal book and return its folder.

    Usage: ``make_book({"01-chapter.md": "# A title\\n\\nHello."})``.
    """

    def _make(
        chapters: dict[str, str] | None = None,
        *,
        config: dict | None = None,
        folder: str = "book",
    ) -> Path:
        root = tmp_path / folder
        chapter_dir = root / "chapters"
        chapter_dir.mkdir(parents=True)
        files = chapters or {"01-first.md": "# First Chapter\n\nHello there."}
        for name, text in files.items():
            (chapter_dir / name).write_text(text, encoding="utf-8")
        settings = {
            "title": "A Test Book",
            "author": "Test Author",
            "copyright_year": 2026,
            "chapters": "chapters",
            "trim": "6x9",
            "paper": "cream",
            "publisher": "Test Press",
        }
        if config:
            settings.update(config)
        (root / "book.yaml").write_text(
            yaml.safe_dump(settings, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return root

    return _make
