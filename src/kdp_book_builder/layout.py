from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.util import join_english

INCH = Decimal("1")
BLEED_IN = Decimal("0.125")
MIN_EDGE_MARGIN_IN = Decimal("0.25")
DEFAULT_OUTSIDE_MARGIN_IN = Decimal("0.625")
DEFAULT_TOP_MARGIN_IN = Decimal("0.75")
DEFAULT_BOTTOM_MARGIN_IN = Decimal("0.75")
AUTO_GUTTER_SAFETY_IN = Decimal("0.125")
AUTO_GUTTER_FLOOR_IN = Decimal("0.625")
SPINE_TEXT_MIN_PAGES = 80
COVER_SAFE_INSET_IN = Decimal("0.25")


@dataclass(frozen=True)
class TrimSize:
    key: str
    width_in: Decimal
    height_in: Decimal
    note: str

    @property
    def display(self) -> str:
        return f"{_short(self.width_in)} × {_short(self.height_in)} in"


@dataclass(frozen=True)
class PaperType:
    key: str
    label: str
    thickness_in: Decimal
    min_pages: int
    max_pages: int
    ink: str


@dataclass(frozen=True)
class Margins:
    inside: Decimal
    outside: Decimal
    top: Decimal
    bottom: Decimal

    @property
    def display(self) -> str:
        return (
            f"inside {fmt_inches(self.inside)}, outside {fmt_inches(self.outside)}, "
            f"top {fmt_inches(self.top)}, bottom {fmt_inches(self.bottom)}"
        )


@dataclass(frozen=True)
class CoverGeometry:
    trim: TrimSize
    paper: PaperType
    page_count: int
    spine_width_in: Decimal
    page_width_in: Decimal
    page_height_in: Decimal
    bleed_in: Decimal
    safe_inset_in: Decimal
    barcode_width_in: Decimal
    barcode_height_in: Decimal
    barcode_x_in: Decimal
    barcode_y_in: Decimal

    @property
    def spine_text_allowed(self) -> bool:
        return self.page_count >= SPINE_TEXT_MIN_PAGES

    @property
    def spine_left_in(self) -> Decimal:
        return self.bleed_in + self.trim.width_in

    @property
    def front_left_in(self) -> Decimal:
        return self.spine_left_in + self.spine_width_in


TRIM_SIZES: tuple[TrimSize, ...] = (
    TrimSize("5x8", Decimal("5"), Decimal("8"), "compact novels, poetry"),
    TrimSize("5.06x7.81", Decimal("5.06"), Decimal("7.81"), "small trade nonfiction"),
    TrimSize("5.25x8", Decimal("5.25"), Decimal("8"), "novels and memoirs"),
    TrimSize("5.5x8.5", Decimal("5.5"), Decimal("8.5"), "self-help and business"),
    TrimSize("6x9", Decimal("6"), Decimal("9"), "manuals and general nonfiction"),
    TrimSize("6.14x9.21", Decimal("6.14"), Decimal("9.21"), "UK trade paperback"),
    TrimSize("6.69x9.61", Decimal("6.69"), Decimal("9.61"), "reference and workbooks"),
    TrimSize("7x10", Decimal("7"), Decimal("10"), "instructional and workbooks"),
    TrimSize("7.44x9.69", Decimal("7.44"), Decimal("9.69"), "textbooks"),
    TrimSize("7.5x9.25", Decimal("7.5"), Decimal("9.25"), "educational"),
    TrimSize("8x10", Decimal("8"), Decimal("10"), "workbooks and visual guides"),
    TrimSize("8.25x6", Decimal("8.25"), Decimal("6"), "landscape books"),
    TrimSize("8.25x8.25", Decimal("8.25"), Decimal("8.25"), "square children's books"),
    TrimSize("8.5x8.5", Decimal("8.5"), Decimal("8.5"), "square picture books"),
    TrimSize("8.5x11", Decimal("8.5"), Decimal("11"), "workbooks and manuals"),
    TrimSize("8.27x11.69", Decimal("8.27"), Decimal("11.69"), "A4-size reference"),
)

TRIM_BY_KEY = {trim.key: trim for trim in TRIM_SIZES}

PAPERS: tuple[PaperType, ...] = (
    PaperType(
        "white",
        "Black & white on white paper",
        Decimal("0.002252"),
        24,
        828,
        "black & white",
    ),
    PaperType(
        "cream",
        "Black & white on cream paper",
        Decimal("0.0025"),
        24,
        776,
        "black & white",
    ),
    PaperType(
        "groundwood",
        "Black & white on groundwood paper",
        Decimal("0.00235"),
        24,
        828,
        "black & white",
    ),
    PaperType(
        "standard-color",
        "Standard color",
        Decimal("0.002252"),
        72,
        600,
        "standard color",
    ),
    PaperType(
        "premium-color",
        "Premium color",
        Decimal("0.002347"),
        24,
        828,
        "premium color",
    ),
)

PAPER_BY_KEY = {paper.key: paper for paper in PAPERS}

_TRIM_ALIASES = {
    "a4": "8.27x11.69",
    "a4-size": "8.27x11.69",
}

_PAPER_ALIASES = {
    "standard": "standard-color",
    "standard-color-ink": "standard-color",
    "bw-white": "white",
    "black-white-white": "white",
    "white-paper": "white",
    "ivory": "cream",
    "cream-paper": "cream",
    "bw-cream": "cream",
    "black-white-cream": "cream",
    "ground-wood": "groundwood",
    "bw-groundwood": "groundwood",
    "standard_color": "standard-color",
    "standardcolor": "standard-color",
    "standard-colour": "standard-color",
    "color-standard": "standard-color",
    "colour-standard": "standard-color",
    "color": "standard-color",
    "premium_color": "premium-color",
    "premiumcolor": "premium-color",
    "premium-colour": "premium-color",
    "color-premium": "premium-color",
    "colour-premium": "premium-color",
    "premium": "premium-color",
}


def normalize_trim(value: str) -> TrimSize:
    raw = str(value).strip().lower()
    raw = raw.replace("×", "x").replace("*", "x")
    raw = re.sub(r"\s+", "", raw)
    raw = re.sub(r"(inches|inch|in)$", "", raw)
    raw = raw.replace("by", "x")
    if raw in _TRIM_ALIASES:
        raw = _TRIM_ALIASES[raw]
    if raw in TRIM_BY_KEY:
        return TRIM_BY_KEY[raw]

    match = re.fullmatch(r"(\d+(?:\.\d+)?)x(\d+(?:\.\d+)?)", raw)
    if match:
        width = Decimal(match.group(1))
        height = Decimal(match.group(2))
        for trim in TRIM_SIZES:
            if trim.width_in == width and trim.height_in == height:
                return trim
    choices = join_english([trim.key for trim in TRIM_SIZES])
    raise BookBuilderError(
        f"Unknown trim size {value!r}. Choose one of: {choices}. "
        "Run 'kdp-book-builder trim-sizes' for details."
    )


def normalize_paper(value: str) -> PaperType:
    raw = str(value).strip().lower().replace(" ", "-")
    raw = _PAPER_ALIASES.get(raw, raw)
    if raw in PAPER_BY_KEY:
        return PAPER_BY_KEY[raw]
    choices = join_english([paper.key for paper in PAPERS])
    raise BookBuilderError(
        f"Unknown paper type {value!r}. Choose one of: {choices}."
    )


def required_gutter_in(page_count: int) -> Decimal:
    """Return KDP's minimum inside (gutter) margin for a page count."""
    if page_count <= 150:
        return Decimal("0.375")
    if page_count <= 300:
        return Decimal("0.5")
    if page_count <= 500:
        return Decimal("0.625")
    if page_count <= 700:
        return Decimal("0.75")
    return Decimal("0.875")


def automatic_inside_margin_in(page_count: int) -> Decimal:
    """A comfortable gutter that is always at or above KDP's minimum."""
    return max(
        AUTO_GUTTER_FLOOR_IN,
        required_gutter_in(page_count) + AUTO_GUTTER_SAFETY_IN,
    )


def resolve_margins(
    page_count: int,
    *,
    inside: Decimal | float | int | str | None = None,
    outside: Decimal | float | int | str | None = None,
    top: Decimal | float | int | str | None = None,
    bottom: Decimal | float | int | str | None = None,
) -> Margins:
    """Use automatic inside margins unless every side is supplied explicitly."""
    return Margins(
        inside=(
            automatic_inside_margin_in(page_count)
            if inside is None
            else _decimal(inside, "inside margin")
        ),
        outside=(
            DEFAULT_OUTSIDE_MARGIN_IN
            if outside is None
            else _decimal(outside, "outside margin")
        ),
        top=(
            DEFAULT_TOP_MARGIN_IN if top is None else _decimal(top, "top margin")
        ),
        bottom=(
            DEFAULT_BOTTOM_MARGIN_IN
            if bottom is None
            else _decimal(bottom, "bottom margin")
        ),
    )


def validate_margins(
    margins: Margins,
    page_count: int,
    trim: TrimSize,
    *,
    inside_was_automatic: bool,
) -> None:
    required = required_gutter_in(page_count)
    for name, value in (
        ("inside", margins.inside),
        ("outside", margins.outside),
        ("top", margins.top),
        ("bottom", margins.bottom),
    ):
        if value <= 0:
            raise BookBuilderError(f"The {name} margin must be greater than zero.")
    if margins.inside < required and not inside_was_automatic:
        raise BookBuilderError(
            f"The inside margin is {fmt_inches(margins.inside)}, but KDP requires "
            f"at least {fmt_inches(required)} for a {page_count}-page book. "
            "Leave --inside-margin unset to let the tool choose a safe margin, "
            f"or use at least {fmt_inches(required)}."
        )
    for name, value in (
        ("outside", margins.outside),
        ("top", margins.top),
        ("bottom", margins.bottom),
    ):
        if value < MIN_EDGE_MARGIN_IN:
            raise BookBuilderError(
                f"The {name} margin is {fmt_inches(value)}, below KDP's "
                f"{fmt_inches(MIN_EDGE_MARGIN_IN)} minimum for a no-bleed interior. "
                f"Use --{name.replace('_', '-')}-margin {fmt_inches(MIN_EDGE_MARGIN_IN)} "
                "or more."
            )
    text_width = trim.width_in - margins.inside - margins.outside
    text_height = trim.height_in - margins.top - margins.bottom
    if text_width < Decimal("1.5") or text_height < Decimal("1.5"):
        raise BookBuilderError(
            "Those margins leave too little room for text. Use smaller margins "
            f"for this {trim.display} trim size."
        )


def calculate_spine_width_in(page_count: int, paper: PaperType) -> Decimal:
    if page_count < 1:
        raise BookBuilderError("A book needs at least one page.")
    return Decimal(page_count) * paper.thickness_in


def cover_geometry(
    trim: TrimSize, paper: PaperType, page_count: int
) -> CoverGeometry:
    """Calculate a full KDP cover wrap with 0.125-inch bleed on all sides."""
    spine = calculate_spine_width_in(page_count, paper)
    width = trim.width_in * 2 + spine + BLEED_IN * 2
    height = trim.height_in + BLEED_IN * 2
    back_right = BLEED_IN + trim.width_in
    spine_right = back_right + spine
    barcode_width = Decimal("2")
    barcode_height = Decimal("1.2")
    gap = Decimal("0.25")
    return CoverGeometry(
        trim=trim,
        paper=paper,
        page_count=page_count,
        spine_width_in=spine,
        page_width_in=width,
        page_height_in=height,
        bleed_in=BLEED_IN,
        safe_inset_in=COVER_SAFE_INSET_IN,
        barcode_width_in=barcode_width,
        barcode_height_in=barcode_height,
        barcode_x_in=back_right - gap - barcode_width,
        barcode_y_in=BLEED_IN + gap,
    )


def validate_page_count(page_count: int, paper: PaperType, trim: TrimSize) -> None:
    if page_count < paper.min_pages:
        raise BookBuilderError(
            f"KDP needs at least {paper.min_pages} interior pages for "
            f"{paper.label.lower()}; this interior has {page_count}."
        )
    if page_count > paper.max_pages:
        raise BookBuilderError(
            f"This interior has {page_count} pages, above the {paper.max_pages}-page "
            f"limit for {paper.label.lower()}. Split the book into volumes or choose "
            "a denser layout. Confirm current limits in KDP's cover calculator."
        )
    if trim.key in {"8.25x6", "8.5x8.5"} and page_count > 800:
        raise BookBuilderError(
            f"KDP's maximum page count is lower for the {trim.display} trim size. "
            "Please check the current KDP page-count table."
        )


def spine_note(geometry: CoverGeometry) -> str:
    if geometry.spine_text_allowed:
        return (
            f"This {geometry.page_count}-page book can have spine text. "
            "Keep text 0.0625 in away from the spine edges."
        )
    return (
        f"KDP does not print spine text on books under {SPINE_TEXT_MIN_PAGES} pages. "
        f"This book has {geometry.page_count}. Leave the spine free of text."
    )


def fmt_inches(value: Decimal | float, places: int = 4) -> str:
    decimal = Decimal(str(value))
    rounded = decimal.quantize(Decimal(1).scaleb(-places))
    text = f"{rounded:f}".rstrip("0").rstrip(".")
    return f"{text} in"


def _short(value: Decimal) -> str:
    return f"{value.normalize():f}"


def _decimal(value: Decimal | float | int | str, name: str) -> Decimal:
    try:
        decimal = Decimal(str(value))
    except Exception as exc:
        raise BookBuilderError(f"The {name} must be a number, not {value!r}.") from exc
    if not decimal.is_finite():
        raise BookBuilderError(f"The {name} must be a finite number.")
    return decimal
