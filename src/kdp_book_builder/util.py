from __future__ import annotations

import re
import unicodedata
from pathlib import Path


def slugify(value: str, fallback: str = "book") -> str:
    """Return a conservative ASCII slug suitable for file and XML IDs."""
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or fallback


def unique_slug(base: str, used: set[str]) -> str:
    candidate = base or "section"
    index = 2
    while candidate in used:
        candidate = f"{base}-{index}"
        index += 1
    used.add(candidate)
    return candidate


def natural_sort_key(value: str) -> list[object]:
    """Sort ``chapter-2.md`` before ``chapter-10.md``."""
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    ]


def display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def join_english(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} or {items[1]}"
    return ", ".join(items[:-1]) + f", or {items[-1]}"
