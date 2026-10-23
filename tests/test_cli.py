from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from kdp_book_builder.cli import main

SAMPLE_SLUG = "the-friendly-ai-field-guide"


def test_build_all_sample_outputs(sample_dir: Path, tmp_path: Path, capsys) -> None:
    output = tmp_path / "published"
    assert main(["build", str(sample_dir), "--output", str(output)]) == 0
    captured = capsys.readouterr()
    assert "Files saved in" in captured.out
    assert "Cover wrap: 12.31 × 9.25 in" in captured.out
    assert "Spine math: 24 pages" in captured.out
    assert "Warnings (1):" in captured.err

    names = {path.name for path in output.iterdir()}
    assert names == {
        f"{SAMPLE_SLUG}-interior.pdf",
        f"{SAMPLE_SLUG}.epub",
        f"{SAMPLE_SLUG}-ebook-cover.jpg",
        f"{SAMPLE_SLUG}-cover-wrap.pdf",
        f"{SAMPLE_SLUG}-cover-template.pdf",
    }
    assert (output / f"{SAMPLE_SLUG}-interior.pdf").read_bytes().startswith(b"%PDF")
    assert (output / f"{SAMPLE_SLUG}.epub").read_bytes().startswith(b"PK")
    assert (output / f"{SAMPLE_SLUG}-ebook-cover.jpg").read_bytes().startswith(
        b"\xff\xd8"
    )


def test_format_pdf_writes_only_interior(make_book, tmp_path: Path) -> None:
    book_dir = make_book()
    output = tmp_path / "pdf-only"
    assert main(["build", str(book_dir), "--format", "pdf", "--output", str(output)]) == 0
    assert [path.name for path in output.iterdir()] == ["a-test-book-interior.pdf"]
    reader = PdfReader(output / "a-test-book-interior.pdf")
    assert len(reader.pages) >= 24
    assert len(reader.pages) % 2 == 0


def test_format_epub_writes_epub_and_cover_only(make_book, tmp_path: Path) -> None:
    book_dir = make_book()
    output = tmp_path / "epub-only"
    assert main(["build", str(book_dir), "--format", "epub", "--output", str(output)]) == 0
    assert {path.name for path in output.iterdir()} == {
        "a-test-book.epub",
        "a-test-book-ebook-cover.jpg",
    }


def test_format_cover_reports_page_count_but_does_not_write_pdf(
    make_book, tmp_path: Path, capsys
) -> None:
    book_dir = make_book()
    output = tmp_path / "cover-only"
    assert main(["build", str(book_dir), "--format", "cover", "--output", str(output)]) == 0
    assert {path.name for path in output.iterdir()} == {
        "a-test-book-cover-wrap.pdf",
        "a-test-book-cover-template.pdf",
    }
    assert "Print interior: 24 pages" in capsys.readouterr().out


def test_default_output_folder_is_dist_slug(
    make_book, tmp_path: Path, monkeypatch, capsys
) -> None:
    book_dir = make_book()
    monkeypatch.chdir(tmp_path)
    assert main(["build", str(book_dir), "--format", "epub"]) == 0
    output = tmp_path / "dist" / "a-test-book"
    assert output.is_dir()
    assert (output / "a-test-book.epub").is_file()
    assert "dist/a-test-book" in capsys.readouterr().out


def test_trim_and_paper_overrides_reach_the_outputs(
    make_book, tmp_path: Path, capsys
) -> None:
    book_dir = make_book()
    output = tmp_path / "override"
    assert (
        main(
            [
                "build",
                str(book_dir),
                "--format",
                "pdf",
                "--trim",
                "5.5x8.5",
                "--paper",
                "white",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    page = PdfReader(output / "a-test-book-interior.pdf").pages[0]
    assert float(page.mediabox.width) == pytest.approx(5.5 * 72)
    assert float(page.mediabox.height) == pytest.approx(8.5 * 72)
    assert "white paper" in capsys.readouterr().out


def test_bad_book_folder_is_a_friendly_error(tmp_path: Path, capsys) -> None:
    code = main(["build", str(tmp_path / "does-not-exist")])
    assert code == 1
    captured = capsys.readouterr()
    assert "Book folder not found" in captured.err
    assert "Traceback" not in captured.err


def test_bad_margin_is_rejected_before_files_are_written(
    make_book, tmp_path: Path, capsys
) -> None:
    book_dir = make_book()
    output = tmp_path / "bad-margin"
    code = main(
        [
            "build",
            str(book_dir),
            "--format",
            "pdf",
            "--inside-margin",
            "0.1",
            "--output",
            str(output),
        ]
    )
    assert code == 1
    assert "KDP requires" in capsys.readouterr().err
    assert not output.exists()


def test_invalid_trim_is_a_friendly_error(make_book, capsys) -> None:
    book_dir = make_book()
    code = main(["build", str(book_dir), "--trim", "9x12", "--format", "epub"])
    assert code == 1
    assert "Unknown trim size" in capsys.readouterr().err


def test_output_path_cannot_be_a_file(make_book, tmp_path: Path, capsys) -> None:
    book_dir = make_book()
    output = tmp_path / "not-a-folder"
    output.write_text("hello", encoding="utf-8")
    code = main(["build", str(book_dir), "--format", "epub", "--output", str(output)])
    assert code == 1
    assert "exists but is a file" in capsys.readouterr().err


def test_trim_sizes_command(capsys) -> None:
    assert main(["trim-sizes"]) == 0
    output = capsys.readouterr().out
    assert "TRIM SIZES" in output
    assert "6x9" in output
    assert "cream" in output
    assert "spine width = final page count × paper thickness" in output


def test_version_and_help(capsys) -> None:
    with pytest.raises(SystemExit) as version_exit:
        main(["--version"])
    assert version_exit.value.code == 0
    assert "0.1.0" in capsys.readouterr().out

    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    assert "kdp-book-builder build" in capsys.readouterr().out
