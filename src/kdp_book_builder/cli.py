from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Sequence

from kdp_book_builder import __version__
from kdp_book_builder.book import Book, MarginOverrides, load_book
from kdp_book_builder.cover import (
    EBOOK_COVER_FILENAME,
    TEMPLATE_FILENAME,
    WRAP_FILENAME,
    CoverBuildResult,
    build_cover_wrap,
)
from kdp_book_builder.epub import EpubBuildResult, build_epub
from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.layout import (
    PAPERS,
    SPINE_TEXT_MIN_PAGES,
    TRIM_SIZES,
    fmt_inches,
)
from kdp_book_builder.pdf import PdfBuildResult, build_interior_pdf


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "trim-sizes":
            _print_sizes()
            return 0
        if args.command == "build":
            return _run_build(args)
        parser.print_help()
        return 2
    except BookBuilderError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped. No files were published anywhere.", file=sys.stderr)
        return 130
    except OSError as exc:
        print(f"\nError: Could not read or write a file: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        if getattr(args, "debug", False):
            traceback.print_exc()
        else:
            print(
                "\nUnexpected error. Run the same command with --debug for details "
                f"({type(exc).__name__}: {exc}).",
                file=sys.stderr,
            )
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kdp-book-builder",
        description=(
            "Turn Markdown chapters into a print interior PDF, Kindle EPUB, and "
            "correctly sized paperback cover wrap."
        ),
        epilog=(
            "Start with: kdp-book-builder build sample_book\n"
            "Sizes:      kdp-book-builder trim-sizes"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show a traceback if something unexpected fails.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser(
        "build",
        help="Build files from a book folder.",
        description=(
            "Build files from a folder containing book.yaml and Markdown chapters."
        ),
    )
    build.add_argument(
        "book_dir",
        nargs="?",
        default=".",
        help="Book folder containing book.yaml (default: current folder).",
    )
    build.add_argument(
        "-o",
        "--output",
        help="Folder for generated files (default: ./dist/<book-slug>).",
    )
    build.add_argument(
        "--format",
        choices=("all", "pdf", "epub", "cover"),
        default="all",
        help="Which files to save (default: all).",
    )
    build.add_argument(
        "--trim",
        help="Override trim size, for example 6x9 or 5.5x8.5. Run trim-sizes to list.",
    )
    build.add_argument(
        "--paper",
        help="Override paper: white, cream, groundwood, standard-color, premium-color.",
    )
    build.add_argument(
        "--title", help="Override the title from book.yaml (useful for a quick proof)."
    )
    build.add_argument(
        "--author", help="Override the author from book.yaml (useful for a quick proof)."
    )
    build.add_argument(
        "--inside-margin", help="Override inside (gutter) margin in inches."
    )
    build.add_argument("--outside-margin", help="Override outside margin in inches.")
    build.add_argument("--top-margin", help="Override top margin in inches.")
    build.add_argument("--bottom-margin", help="Override bottom margin in inches.")
    build.set_defaults(handler="build")

    sizes = subparsers.add_parser(
        "trim-sizes",
        help="List supported trim sizes, paper types, and spine rules.",
        description="List the trim sizes and paper types built into this tool.",
    )
    sizes.set_defaults(handler="sizes")
    return parser


def _run_build(args: argparse.Namespace) -> int:
    margins = _margin_overrides(args)
    book = load_book(
        args.book_dir,
        trim=args.trim,
        paper=args.paper,
        title=args.title,
        author=args.author,
        margins=margins,
    )
    output_dir = _output_dir(args.output, book)
    warnings = list(book.warnings)
    artifacts: list[tuple[Path, bytes]] = []
    interior: PdfBuildResult | None = None
    cover: CoverBuildResult | None = None
    epub: EpubBuildResult | None = None

    print(f"Preparing {book.title}")
    print(f"  by {book.author}")
    if args.format in {"all", "pdf", "cover"}:
        print(
            f"  Laying out {book.trim.display} pages on {book.paper.label.lower()}...",
            flush=True,
        )
        interior = build_interior_pdf(book)
        warnings.extend(interior.warnings)
        if args.format in {"all", "pdf"}:
            artifacts.append(
                (output_dir / f"{book.slug}-interior.pdf", interior.data)
            )

    if args.format in {"all", "cover"}:
        assert interior is not None
        cover = build_cover_wrap(book, interior.page_count)
        warnings.extend(cover.warnings)
        artifacts.extend(
            [
                (output_dir / f"{book.slug}{WRAP_FILENAME}", cover.wrap_pdf),
                (output_dir / f"{book.slug}{TEMPLATE_FILENAME}", cover.template_pdf),
            ]
        )

    if args.format in {"all", "epub"}:
        print("  Building the Kindle EPUB and cover image...", flush=True)
        epub = build_epub(book)
        warnings.extend(epub.warnings)
        artifacts.extend(
            [
                (output_dir / f"{book.slug}.epub", epub.data),
                (
                    output_dir / f"{book.slug}{EBOOK_COVER_FILENAME}",
                    epub.cover_image,
                ),
            ]
        )

    if not artifacts:
        raise BookBuilderError("Nothing was selected to build.")
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for path, data in artifacts:
        _atomic_write(path, data)
        written.append(path)

    _print_summary(
        book,
        interior=interior,
        cover=cover,
        epub=epub,
        written=written,
        output_dir=output_dir,
        warnings=_dedupe(warnings),
    )
    return 0


def _print_summary(
    book: Book,
    *,
    interior: PdfBuildResult | None,
    cover: CoverBuildResult | None,
    epub: EpubBuildResult | None,
    written: list[Path],
    output_dir: Path,
    warnings: list[str],
) -> None:
    print()
    if interior is not None:
        print(
            f"Print interior: {interior.page_count} pages · {book.trim.display} · "
            f"{book.paper.label.lower()}"
        )
        print(f"  Margins: {interior.margins.display}")
    if cover is not None:
        geometry = cover.geometry
        print(
            f"Cover wrap: {_decimal_text(geometry.page_width_in)} × "
            f"{_decimal_text(geometry.page_height_in)} in "
            f"(spine {fmt_inches(geometry.spine_width_in)})"
        )
        print(
            f"  Spine math: {geometry.page_count} pages × "
            f"{_decimal_text(geometry.paper.thickness_in)} in = "
            f"{fmt_inches(geometry.spine_width_in)}"
        )
        if not geometry.spine_text_allowed:
            print(
                "  Spine text: leave the spine clear (KDP minimum is "
                f"{SPINE_TEXT_MIN_PAGES} pages)."
            )
    if epub is not None:
        print(
            f"Kindle EPUB: {epub.chapter_count} chapters, {epub.image_count} "
            f"interior image{'s' if epub.image_count != 1 else ''}"
        )
    print()
    print(f"Files saved in {output_dir}:")
    for path in written:
        print(f"  {path.name}")
    print()
    print(
        "Before uploading, open the PDF, check the table of contents and page "
        "numbers, and review both files in KDP's previewer."
    )
    if warnings:
        sys.stdout.flush()
        print(f"\nWarnings ({len(warnings)}):", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)


def _print_sizes() -> None:
    print("TRIM SIZES (width × height in inches)")
    print()
    print(f"  {'Size':<14}{'Typical use':<40}")
    print(f"  {'-' * 12:<14}{'-' * 38:<40}")
    for trim in TRIM_SIZES:
        print(f"  {trim.key:<14}{trim.note:<40}")
    print()
    print("PAPER TYPES")
    print()
    print(f"  {'Name':<18}{'Thickness/page':<18}{'Pages':<12}Ink")
    print(f"  {'-' * 16:<18}{'-' * 16:<18}{'-' * 10:<12}{'-' * 15}")
    for paper in PAPERS:
        page_range = f"{paper.min_pages}-{paper.max_pages}"
        print(
            f"  {paper.key:<18}{str(paper.thickness_in) + ' in':<18}"
            f"{page_range:<12}{paper.ink}"
        )
    print()
    print("SPINE MATH")
    print("  spine width = final page count × paper thickness")
    print(
        "  full cover width = 0.125 in bleed + back trim + spine + front trim "
        "+ 0.125 in bleed"
    )
    print("  full cover height = trim height + 0.25 in bleed")
    print("  KDP does not allow spine text on books under 80 pages.")
    print()
    print("Always confirm current specifications in KDP's cover calculator.")


def _margin_overrides(args: argparse.Namespace) -> MarginOverrides | None:
    values = {
        "inside": args.inside_margin,
        "outside": args.outside_margin,
        "top": args.top_margin,
        "bottom": args.bottom_margin,
    }
    if not any(value is not None for value in values.values()):
        return None
    parsed: dict[str, Decimal | None] = {}
    for name, value in values.items():
        if value is None:
            parsed[name] = None
            continue
        try:
            decimal = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise BookBuilderError(
                f"--{name}-margin must be a number of inches, not {value!r}."
            ) from exc
        if not decimal.is_finite() or decimal <= 0:
            raise BookBuilderError(
                f"--{name}-margin must be greater than zero."
            )
        parsed[name] = decimal
    return MarginOverrides(
        inside=parsed["inside"],
        outside=parsed["outside"],
        top=parsed["top"],
        bottom=parsed["bottom"],
    )


def _output_dir(value: str | None, book: Book) -> Path:
    target = (
        Path(value).expanduser()
        if value is not None
        else Path.cwd() / "dist" / book.slug
    )
    target = target.resolve()
    if target.exists() and not target.is_dir():
        raise BookBuilderError(
            f"Output path exists but is a file, not a folder: {target}"
        )
    return target


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _dedupe(messages: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for message in messages:
        if message not in seen:
            seen.add(message)
            result.append(message)
    return result


def _decimal_text(value: object) -> str:
    text = str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
