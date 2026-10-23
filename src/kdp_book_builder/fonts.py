from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

FONT_DIR = Path(__file__).parent / "assets" / "fonts"

SERIF = "KDPBookSerif"
SERIF_BOLD = "KDPBookSerif-Bold"
SERIF_ITALIC = "KDPBookSerif-Italic"
SERIF_BOLD_ITALIC = "KDPBookSerif-BoldItalic"
SANS = "KDPBookSans"
SANS_BOLD = "KDPBookSans-Bold"
MONO = "KDPBookMono"

_FILES = {
    SERIF: "LiberationSerif-Regular.ttf",
    SERIF_BOLD: "LiberationSerif-Bold.ttf",
    SERIF_ITALIC: "LiberationSerif-Italic.ttf",
    SERIF_BOLD_ITALIC: "LiberationSerif-BoldItalic.ttf",
    SANS: "LiberationSans-Regular.ttf",
    SANS_BOLD: "LiberationSans-Bold.ttf",
    MONO: "LiberationMono-Regular.ttf",
}

_registered = False


@dataclass(frozen=True)
class FontPaths:
    serif: Path
    serif_bold: Path
    serif_italic: Path
    sans: Path
    sans_bold: Path
    mono: Path


def font_paths() -> FontPaths:
    return FontPaths(
        serif=FONT_DIR / _FILES[SERIF],
        serif_bold=FONT_DIR / _FILES[SERIF_BOLD],
        serif_italic=FONT_DIR / _FILES[SERIF_ITALIC],
        sans=FONT_DIR / _FILES[SANS],
        sans_bold=FONT_DIR / _FILES[SANS_BOLD],
        mono=FONT_DIR / _FILES[MONO],
    )


def register_fonts() -> None:
    """Register bundled TrueType fonts with ReportLab exactly once."""
    global _registered
    if _registered:
        return
    for name, filename in _FILES.items():
        path = FONT_DIR / filename
        if not path.is_file():
            raise RuntimeError(f"Bundled font is missing: {path}")
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily(
        SERIF,
        normal=SERIF,
        bold=SERIF_BOLD,
        italic=SERIF_ITALIC,
        boldItalic=SERIF_BOLD_ITALIC,
    )
    pdfmetrics.registerFontFamily(
        SANS,
        normal=SANS,
        bold=SANS_BOLD,
        italic=SANS,
        boldItalic=SANS_BOLD,
    )
    pdfmetrics.registerFontFamily(
        MONO,
        normal=MONO,
        bold=MONO,
        italic=MONO,
        boldItalic=MONO,
    )
    _registered = True
