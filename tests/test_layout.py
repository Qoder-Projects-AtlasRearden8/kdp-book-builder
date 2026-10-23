from __future__ import annotations

from decimal import Decimal

import pytest

from kdp_book_builder.errors import BookBuilderError
from kdp_book_builder.layout import (
    BLEED_IN,
    SPINE_TEXT_MIN_PAGES,
    automatic_inside_margin_in,
    calculate_spine_width_in,
    cover_geometry,
    fmt_inches,
    normalize_paper,
    normalize_trim,
    required_gutter_in,
    resolve_margins,
    validate_margins,
    validate_page_count,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("6x9", "6x9"),
        ("6 x 9", "6x9"),
        ("6by9", "6x9"),
        ("6×9", "6x9"),
        ("6*9", "6x9"),
        ("6 x 9 inches", "6x9"),
        ("A4", "8.27x11.69"),
        ("5.5x8.5", "5.5x8.5"),
        ("8.50 x 11.00", "8.5x11"),
    ],
)
def test_normalize_trim_accepts_human_forms(value: str, expected: str) -> None:
    assert normalize_trim(value).key == expected


def test_normalize_trim_rejects_unknown_size_with_helpful_message() -> None:
    with pytest.raises(BookBuilderError, match="Unknown trim size"):
        normalize_trim("9x12")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("cream", "cream"),
        ("CREAM", "cream"),
        ("ivory", "cream"),
        ("bw-cream", "cream"),
        ("standard", "standard-color"),
        ("standard_color", "standard-color"),
        ("Premium Color", "premium-color"),
        ("color", "standard-color"),
        ("ground-wood", "groundwood"),
    ],
)
def test_normalize_paper_accepts_aliases(value: str, expected: str) -> None:
    assert normalize_paper(value).key == expected


def test_normalize_paper_rejects_unknown() -> None:
    with pytest.raises(BookBuilderError, match="Unknown paper type"):
        normalize_paper("banana")


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (24, Decimal("0.375")),
        (150, Decimal("0.375")),
        (151, Decimal("0.5")),
        (300, Decimal("0.5")),
        (301, Decimal("0.625")),
        (500, Decimal("0.625")),
        (501, Decimal("0.75")),
        (700, Decimal("0.75")),
        (701, Decimal("0.875")),
    ],
)
def test_gutter_requirements_match_kdp_bands(pages: int, expected: Decimal) -> None:
    assert required_gutter_in(pages) == expected


def test_automatic_gutter_has_safety_and_floor() -> None:
    assert automatic_inside_margin_in(24) == Decimal("0.625")
    assert automatic_inside_margin_in(500) == Decimal("0.75")
    assert automatic_inside_margin_in(800) == Decimal("1.0")


def test_resolve_margins_uses_automatic_values_and_overrides() -> None:
    automatic = resolve_margins(200, outside="0.8")
    assert automatic.inside == Decimal("0.625")
    assert automatic.outside == Decimal("0.8")
    assert automatic.top == Decimal("0.75")
    assert automatic.bottom == Decimal("0.75")

    explicit = resolve_margins(
        200,
        inside=7,
        outside=6,
        top=5,
        bottom=4,
    )
    assert explicit.inside == Decimal("7")


def test_validate_margins_rejects_manual_gutter_below_minimum() -> None:
    trim = normalize_trim("6x9")
    margins = resolve_margins(400, inside="0.5", outside="0.625")
    with pytest.raises(BookBuilderError, match="inside margin.*KDP requires"):
        validate_margins(
            margins, 400, trim, inside_was_automatic=False
        )


def test_validate_margins_rejects_tiny_outside_margin() -> None:
    trim = normalize_trim("6x9")
    margins = resolve_margins(100, outside="0.2")
    with pytest.raises(BookBuilderError, match="outside margin"):
        validate_margins(margins, 100, trim, inside_was_automatic=False)


def test_validate_margins_rejects_margins_that_squeeze_text() -> None:
    trim = normalize_trim("5x8")
    margins = resolve_margins(
        100,
        inside="2.2",
        outside="2.2",
        top="3.5",
        bottom="3.5",
    )
    with pytest.raises(BookBuilderError, match="too little room"):
        validate_margins(margins, 100, trim, inside_was_automatic=False)


def test_spine_width_uses_page_count_and_paper() -> None:
    cream = normalize_paper("cream")
    white = normalize_paper("white")
    assert calculate_spine_width_in(24, cream) == Decimal("0.0600")
    assert calculate_spine_width_in(300, white) == Decimal("0.675600")
    assert calculate_spine_width_in(80, cream) == Decimal("0.2000")
    with pytest.raises(BookBuilderError, match="at least one page"):
        calculate_spine_width_in(0, cream)


def test_cover_geometry_for_sample_book() -> None:
    trim = normalize_trim("6x9")
    cream = normalize_paper("cream")
    geometry = cover_geometry(trim, cream, 24)

    assert geometry.spine_width_in == Decimal("0.0600")
    assert geometry.page_width_in == Decimal("12.3100")
    assert geometry.page_height_in == Decimal("9.250")
    assert geometry.bleed_in == BLEED_IN
    assert geometry.front_left_in == Decimal("6.1850")
    assert geometry.spine_left_in == Decimal("6.125")
    assert geometry.safe_inset_in == Decimal("0.25")
    assert geometry.barcode_width_in == Decimal("2")
    assert geometry.barcode_height_in == Decimal("1.2")
    assert geometry.barcode_x_in == Decimal("3.875")
    assert geometry.barcode_y_in == Decimal("0.375")
    assert geometry.spine_text_allowed is False


def test_spine_text_rule_turns_on_at_eighty_pages() -> None:
    geometry = cover_geometry(normalize_trim("6x9"), normalize_paper("cream"), 80)
    assert geometry.page_count == SPINE_TEXT_MIN_PAGES
    assert geometry.spine_text_allowed
    below = cover_geometry(
        normalize_trim("6x9"), normalize_paper("cream"), SPINE_TEXT_MIN_PAGES - 1
    )
    assert not below.spine_text_allowed


def test_page_count_validation() -> None:
    trim = normalize_trim("6x9")
    cream = normalize_paper("cream")
    with pytest.raises(BookBuilderError, match="at least 24"):
        validate_page_count(10, cream, trim)
    validate_page_count(24, cream, trim)
    validate_page_count(776, cream, trim)
    with pytest.raises(BookBuilderError, match="above the 776-page"):
        validate_page_count(777, cream, trim)
    with pytest.raises(BookBuilderError, match="at least 72"):
        validate_page_count(30, normalize_paper("standard-color"), trim)


def test_fmt_inches_trims_unneeded_zeroes() -> None:
    assert fmt_inches(Decimal("0.0600")) == "0.06 in"
    assert fmt_inches(Decimal("12.3100"), 4) == "12.31 in"
    assert fmt_inches(0.5) == "0.5 in"
