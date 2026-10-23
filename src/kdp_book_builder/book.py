from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml
from markdown_it.token import Token

from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.layout import PaperType, TrimSize, normalize_paper, normalize_trim
from kdp_book_builder.markdown import (
    IMAGE_SUFFIXES,
    Section,
    parse_chapter_text,
)
from kdp_book_builder.util import display_path, is_relative_to, natural_sort_key, slugify

_KNOWN_CONFIG_KEYS = {
    "title",
    "subtitle",
    "author",
    "publisher",
    "language",
    "edition",
    "copyright_year",
    "copyright_holder",
    "isbn",
    "description",
    "disclaimer",
    "keywords",
    "trim",
    "paper",
    "chapters",
    "cover",
    "margins",
}
_KNOWN_COVER_KEYS = {"background", "accent", "text", "tagline", "image"}
_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class CoverDesign:
    background: str = "#17324D"
    accent: str = "#E3B563"
    text: str = "#FFF9EF"
    tagline: str = ""
    image: Path | None = None


@dataclass(frozen=True)
class MarginOverrides:
    inside: Decimal | None = None
    outside: Decimal | None = None
    top: Decimal | None = None
    bottom: Decimal | None = None


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    source: Path
    relative_source: str
    body_tokens: list[Token]
    sections: list[Section]


@dataclass
class Book:
    root: Path
    config_path: Path
    title: str
    subtitle: str | None
    author: str
    publisher: str
    language: str
    edition: str | None
    copyright_year: int
    copyright_holder: str
    isbn: str | None
    description: str | None
    disclaimer: str | None
    keywords: list[str]
    trim: TrimSize
    paper: PaperType
    chapters: list[Chapter]
    cover: CoverDesign
    margins: MarginOverrides
    warnings: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.title)

    @property
    def display_title(self) -> str:
        return self.title


def load_book(
    book_dir: str | Path,
    *,
    trim: str | None = None,
    paper: str | None = None,
    title: str | None = None,
    author: str | None = None,
    margins: MarginOverrides | None = None,
) -> Book:
    root = Path(book_dir).expanduser().resolve()
    if not root.is_dir():
        raise BookBuilderError(
            f"Book folder not found: {book_dir}. Point the command at a folder "
            "containing book.yaml."
        )
    config_path = root / "book.yaml"
    if not config_path.is_file():
        raise BookBuilderError(
            f"No book.yaml found in {root}. Add a book.yaml with a title, author, "
            "and chapters: chapters, or copy the sample_book folder."
        )
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise BookBuilderError("book.yaml must be saved as UTF-8 text.") from exc
    except yaml.YAMLError as exc:
        raise BookBuilderError(f"Could not read book.yaml:\n{exc}") from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise BookBuilderError("book.yaml must contain a set of key: value settings.")

    warnings: list[str] = []
    unknown = sorted(set(raw) - _KNOWN_CONFIG_KEYS)
    if unknown:
        warnings.append(
            "book.yaml: ignored unknown setting"
            + ("s: " if len(unknown) > 1 else ": ")
            + ", ".join(str(key) for key in unknown)
        )

    book_title = _first_nonempty(title, raw.get("title"))
    if not book_title:
        raise BookBuilderError("book.yaml needs a non-empty title: field.")
    book_author = _first_nonempty(author, raw.get("author"))
    if not book_author:
        raise BookBuilderError("book.yaml needs a non-empty author: field.")

    subtitle = _optional_text(raw.get("subtitle"))
    publisher = _optional_text(raw.get("publisher")) or ""
    language = _optional_text(raw.get("language")) or "en"
    edition = _optional_text(raw.get("edition"))
    description = _optional_text(raw.get("description"))
    disclaimer = _optional_text(raw.get("disclaimer"))
    isbn = _normalize_isbn(raw.get("isbn"))
    copyright_holder = _optional_text(raw.get("copyright_holder")) or book_author
    copyright_year = _copyright_year(raw.get("copyright_year"))
    keywords = _keywords(raw.get("keywords"))
    trim_size = normalize_trim(trim or _optional_text(raw.get("trim")) or "6x9")
    paper_type = normalize_paper(paper or _optional_text(raw.get("paper")) or "cream")
    cover = _parse_cover(raw.get("cover"), root)
    configured_margins = _parse_margins(raw.get("margins"))
    margin_overrides = _merge_margins(configured_margins, margins)
    chapter_files = _chapter_files(raw.get("chapters"), root)
    chapters = _load_chapters(chapter_files, root)

    titles = [chapter.title.casefold() for chapter in chapters]
    if len(set(titles)) != len(titles):
        warnings.append(
            "Two or more chapters have the same title. That is allowed, but the "
            "table of contents will be harder to scan."
        )

    return Book(
        root=root,
        config_path=config_path,
        title=book_title,
        subtitle=subtitle,
        author=book_author,
        publisher=publisher,
        language=language,
        edition=edition,
        copyright_year=copyright_year,
        copyright_holder=copyright_holder,
        isbn=isbn,
        description=description,
        disclaimer=disclaimer,
        keywords=keywords,
        trim=trim_size,
        paper=paper_type,
        chapters=chapters,
        cover=cover,
        margins=margin_overrides,
        warnings=warnings,
    )


def _chapter_files(value: Any, root: Path) -> list[Path]:
    if value is None:
        candidate = root / "chapters"
        if not candidate.is_dir():
            raise BookBuilderError(
                "No chapter folder found. Add Markdown files to chapters/ or set "
                "chapters: chapters in book.yaml."
            )
        value = "chapters"

    if isinstance(value, str):
        target = _inside_root(value, root, "chapter path")
        if target.is_dir():
            files = sorted(
                (
                    path
                    for path in target.iterdir()
                    if path.is_file()
                    and path.suffix.lower() in {".md", ".markdown"}
                    and not path.name.startswith(".")
                ),
                key=lambda path: natural_sort_key(path.name),
            )
            if not files:
                raise BookBuilderError(
                    f"No .md chapter files found in {display_path(target, root)}."
                )
            return files
        if target.is_file():
            return [target]
        raise BookBuilderError(
            f"Chapter path not found: {display_path(target, root)}."
        )

    if isinstance(value, (list, tuple)):
        if not value:
            raise BookBuilderError("chapters: must list at least one Markdown file.")
        files = []
        seen: set[Path] = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise BookBuilderError(
                    "Each entry under chapters: must be a Markdown file path."
                )
            path = _inside_root(item, root, "chapter path")
            if not path.is_file():
                raise BookBuilderError(
                    f"Chapter file not found: {display_path(path, root)}."
                )
            if path.suffix.lower() not in {".md", ".markdown"}:
                raise BookBuilderError(
                    f"Chapter file must end in .md or .markdown: "
                    f"{display_path(path, root)}."
                )
            if path not in seen:
                files.append(path)
                seen.add(path)
        return files

    raise BookBuilderError(
        "chapters: must be a folder path or a list of Markdown files."
    )


def _load_chapters(files: list[Path], root: Path) -> list[Chapter]:
    chapters: list[Chapter] = []
    for number, path in enumerate(files, start=1):
        relative = display_path(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise BookBuilderError(f"{relative} must be saved as UTF-8 text.") from exc
        except OSError as exc:
            raise BookBuilderError(f"Could not read {relative}: {exc}") from exc
        parsed = parse_chapter_text(text, path.resolve(), relative)
        chapters.append(
            Chapter(
                number=number,
                title=parsed.title,
                source=path.resolve(),
                relative_source=relative,
                body_tokens=parsed.body_tokens,
                sections=parsed.sections,
            )
        )
    return chapters


def _parse_cover(value: Any, root: Path) -> CoverDesign:
    if value is None:
        return CoverDesign()
    if not isinstance(value, dict):
        raise BookBuilderError("cover: must be a group of color and tagline settings.")
    unknown = sorted(set(value) - _KNOWN_COVER_KEYS)
    if unknown:
        raise BookBuilderError(
            "cover: contains unknown setting(s): "
            + ", ".join(str(key) for key in unknown)
            + ". Use background, accent, text, tagline, or image."
        )
    colors = {
        "background": _color(value.get("background"), "#17324D", "cover.background"),
        "accent": _color(value.get("accent"), "#E3B563", "cover.accent"),
        "text": _color(value.get("text"), "#FFF9EF", "cover.text"),
    }
    image_value = _optional_text(value.get("image"))
    image_path = None
    if image_value:
        image_path = _inside_root(image_value, root, "cover.image")
        if not image_path.is_file():
            raise BookBuilderError(
                f"Cover image not found: {display_path(image_path, root)}."
            )
        if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise BookBuilderError(
                "cover.image must be a .jpg, .jpeg, or .png file."
            )
    return CoverDesign(
        background=colors["background"],
        accent=colors["accent"],
        text=colors["text"],
        tagline=_optional_text(value.get("tagline")) or "",
        image=image_path,
    )


def _parse_margins(value: Any) -> MarginOverrides:
    if value is None:
        return MarginOverrides()
    if not isinstance(value, dict):
        raise BookBuilderError(
            "margins: must contain inside, outside, top, and/or bottom values in inches."
        )
    unknown = sorted(set(value) - {"inside", "outside", "top", "bottom"})
    if unknown:
        raise BookBuilderError(
            "margins: contains unknown setting(s): " + ", ".join(str(k) for k in unknown)
        )
    return MarginOverrides(
        inside=_margin_decimal(value.get("inside"), "margins.inside"),
        outside=_margin_decimal(value.get("outside"), "margins.outside"),
        top=_margin_decimal(value.get("top"), "margins.top"),
        bottom=_margin_decimal(value.get("bottom"), "margins.bottom"),
    )


def _merge_margins(
    configured: MarginOverrides, supplied: MarginOverrides | None
) -> MarginOverrides:
    if supplied is None:
        return configured
    return MarginOverrides(
        inside=supplied.inside if supplied.inside is not None else configured.inside,
        outside=supplied.outside if supplied.outside is not None else configured.outside,
        top=supplied.top if supplied.top is not None else configured.top,
        bottom=supplied.bottom if supplied.bottom is not None else configured.bottom,
    )


def _margin_decimal(value: Any, name: str) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BookBuilderError(f"{name} must be a number of inches.") from exc
    if not decimal.is_finite() or decimal <= 0:
        raise BookBuilderError(f"{name} must be greater than zero.")
    return decimal


def _inside_root(value: str, root: Path, label: str) -> Path:
    candidate = Path(value).expanduser()
    path = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if not is_relative_to(path, root):
        raise BookBuilderError(
            f"{label} must stay inside the book folder: {value!r}."
        )
    return path


def _color(value: Any, default: str, name: str) -> str:
    if value is None:
        return default
    color = str(value).strip()
    if not _COLOR_RE.fullmatch(color):
        raise BookBuilderError(f"{name} must be a six-digit hex color such as #17324D.")
    return color.upper()


def _normalize_isbn(value: Any) -> str | None:
    if value is None or value == "":
        return None
    isbn = re.sub(r"[\s-]", "", str(value)).upper()
    if not re.fullmatch(r"(?:\d{9}[\dX]|\d{13})", isbn):
        raise BookBuilderError(
            "isbn: must be a 10- or 13-digit number. Leave it blank if KDP will "
            "assign a free ISBN; the interior does not require one."
        )
    return isbn


def _copyright_year(value: Any) -> int:
    if value is None or value == "":
        return dt.date.today().year
    try:
        year = int(value)
    except (TypeError, ValueError) as exc:
        raise BookBuilderError("copyright_year: must be a four-digit year.") from exc
    if year < 1000 or year > 2200:
        raise BookBuilderError("copyright_year: must be a four-digit year.")
    return year


def _keywords(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(part).strip() for part in value if str(part).strip()]
    raise BookBuilderError("keywords: must be a comma-separated string or a list.")


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _first_nonempty(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text:
            return text
    return None
