from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest
from PIL import Image

from kdp_book_builder.book import load_book
from kdp_book_builder.epub import build_epub

NS_XHTML = "http://www.w3.org/1999/xhtml"
NS_OPF = "http://www.idpf.org/2007/opf"
NS_DC = "http://purl.org/dc/elements/1.1/"


def _parse(data: bytes) -> ElementTree.Element:
    return ElementTree.fromstring(data)


def _zip_text(archive: zipfile.ZipFile, name: str) -> str:
    return archive.read(name).decode("utf-8")


def test_epub_zip_contract(sample_epub) -> None:
    with zipfile.ZipFile(io.BytesIO(sample_epub.data)) as archive:
        assert archive.testzip() is None
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in archive.namelist()
        assert "OEBPS/content.opf" in archive.namelist()
        assert all(not info.filename.startswith("/") for info in infos)
        assert all(".." not in Path(info.filename).parts for info in infos)


def test_epub_xml_is_well_formed_and_manifest_is_consistent(sample_epub) -> None:
    with zipfile.ZipFile(io.BytesIO(sample_epub.data)) as archive:
        for name in archive.namelist():
            if name.endswith((".xhtml", ".opf", ".xml")):
                _parse(archive.read(name))
        opf = _parse(archive.read("OEBPS/content.opf"))
        manifest = opf.find(f"{{{NS_OPF}}}manifest")
        spine = opf.find(f"{{{NS_OPF}}}spine")
        assert manifest is not None and spine is not None
        items = {}
        hrefs = set()
        for item in manifest.findall(f"{{{NS_OPF}}}item"):
            item_id = item.attrib["id"]
            assert item_id not in items
            items[item_id] = item
            href = item.attrib["href"]
            assert href not in hrefs
            hrefs.add(href)
            assert (Path("OEBPS") / href).as_posix() in archive.namelist()
        for itemref in spine.findall(f"{{{NS_OPF}}}itemref"):
            assert itemref.attrib["idref"] in items
        nav = next(item for item in items.values() if "nav" in item.attrib.get("properties", "").split())
        cover = next(
            item
            for item in items.values()
            if "cover-image" in item.attrib.get("properties", "").split()
        )
        assert nav.attrib["media-type"] == "application/xhtml+xml"
        assert cover.attrib["href"] == "images/cover.jpg"
        assert cover.attrib["media-type"] == "image/jpeg"


def test_epub_metadata_and_identifier(sample_epub) -> None:
    with zipfile.ZipFile(io.BytesIO(sample_epub.data)) as archive:
        metadata = _parse(archive.read("OEBPS/content.opf")).find(
            f"{{{NS_OPF}}}metadata"
        )
        assert metadata is not None
        titles = [
            element.text
            for element in metadata.findall(f"{{{NS_DC}}}title")
            if element.text
        ]
        assert "The Friendly AI Field Guide" in titles
        assert "A calm, practical start with everyday AI" in titles
        assert metadata.find(f"{{{NS_DC}}}creator").text == "Dylan Asdale"
        assert metadata.find(f"{{{NS_DC}}}language").text == "en-US"
        assert metadata.find(f"{{{NS_DC}}}publisher").text == "ASDALE DYNAMICS, LLC"
        subjects = [
            element.text for element in metadata.findall(f"{{{NS_DC}}}subject")
        ]
        assert "prompt writing" in subjects
        identifier = metadata.find(f"{{{NS_DC}}}identifier")
        assert identifier.text.startswith("urn:uuid:")
        modified = next(
            element.text
            for element in metadata.findall(f"{{{NS_OPF}}}meta")
            if element.attrib.get("property") == "dcterms:modified"
        )
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", modified)


def test_epub_has_cover_chapters_and_working_navigation(sample_epub, sample_book) -> None:
    with zipfile.ZipFile(io.BytesIO(sample_epub.data)) as archive:
        names = set(archive.namelist())
        assert "OEBPS/text/cover.xhtml" in names
        assert "OEBPS/images/cover.jpg" in names
        assert archive.read("OEBPS/images/cover.jpg").startswith(b"\xff\xd8")
        assert sample_epub.cover_image == archive.read("OEBPS/images/cover.jpg")

        for chapter in sample_book.chapters:
            name = f"OEBPS/text/chapter-{chapter.number:02d}.xhtml"
            assert name in names
            text = _zip_text(archive, name)
            assert chapter.title in text

        nav = _parse(archive.read("OEBPS/nav.xhtml"))
        links = [
            element.attrib["href"]
            for element in nav.iter(f"{{{NS_XHTML}}}a")
        ]
        assert links
        for href in links:
            file_part, _, fragment = href.partition("#")
            file_name = (Path("OEBPS") / file_part).as_posix()
            assert file_name in names
            target = _parse(archive.read(file_name))
            ids = {
                value
                for element in target.iter()
                for key, value in element.attrib.items()
                if key == "id"
            }
            if fragment:
                assert fragment in ids
        assert len(links) >= len(sample_book.chapters)


def test_epub_preserves_rich_markdown(sample_epub) -> None:
    with zipfile.ZipFile(io.BytesIO(sample_epub.data)) as archive:
        chapter_two = _zip_text(archive, "OEBPS/text/chapter-02.xhtml")
        assert "<table" in chapter_two
        assert "<th" in chapter_two
        assert "<blockquote>" in chapter_two
        assert "<strong>" in chapter_two
        assert 'id="what-these-tools-do-well"' in chapter_two
        chapter_three = _zip_text(archive, "OEBPS/text/chapter-03.xhtml")
        assert "<ol>" in chapter_three
        assert "<pre><code>" in chapter_three


def test_epub_embeds_content_images(make_book) -> None:
    root = make_book(
        {
            "01-picture.md": (
                "# A Picture\n\nSome words.\n\n![A blue square](art.png)\n"
            )
        }
    )
    art = Image.new("RGB", (320, 240), "#2B5B7A")
    art.save(root / "chapters" / "art.png")
    result = build_epub(load_book(root))
    assert result.image_count == 1
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        images = [name for name in archive.namelist() if name.startswith("OEBPS/images/image-")]
        assert images == ["OEBPS/images/image-001.png"]
        chapter = _zip_text(archive, "OEBPS/text/chapter-01.xhtml")
        assert 'src="../images/image-001.png"' in chapter
        assert 'alt="A blue square"' in chapter
        opf = _zip_text(archive, "OEBPS/content.opf")
        assert 'media-type="image/png"' in opf


def test_cross_chapter_markdown_link_is_rewritten(make_book) -> None:
    root = make_book(
        {
            "01-one.md": (
                "# One\n\nJump to [the section](02-two.md#a-section) or "
                "[the chapter](02-two.md).\n"
            ),
            "02-two.md": "# Two\n\n## A Section\n\nBody.\n",
        }
    )
    result = build_epub(load_book(root))
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        chapter_one = _zip_text(archive, "OEBPS/text/chapter-01.xhtml")
    assert 'href="chapter-02.xhtml#a-section"' in chapter_one
    assert 'href="chapter-02.xhtml"' in chapter_one
    assert "unsupported link" not in " ".join(result.warnings)


def test_unsafe_and_missing_links_are_removed_with_warnings(make_book) -> None:
    root = make_book(
        {
            "01-one.md": (
                "# One\n\n"
                "[Bad](ftp://example.com/secret) and [missing](nowhere.md).\n"
            )
        }
    )
    result = build_epub(load_book(root))
    warnings = " ".join(result.warnings)
    assert "unsupported link" in warnings
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        chapter = _zip_text(archive, "OEBPS/text/chapter-01.xhtml")
    assert "ftp:" not in chapter
    assert "Bad" in chapter
    assert "missing" in chapter
    assert 'href="nowhere.md"' not in chapter


def test_missing_image_keeps_alt_text_and_warns(make_book) -> None:
    root = make_book({"01-one.md": "# One\n\n![Quiet diagram](missing.png)\n"})
    result = build_epub(load_book(root))
    assert any("skipped" in warning for warning in result.warnings)
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        chapter = _zip_text(archive, "OEBPS/text/chapter-01.xhtml")
    assert "missing-image" in chapter
    assert "Quiet diagram" in chapter


def test_svg_is_included_but_warned_for_kindle(make_book) -> None:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
        '<rect width="20" height="10" fill="#2B5B7A"/></svg>'
    )
    root = make_book({"01-one.md": "# One\n\n![Shape](shape.svg)\n"})
    (root / "chapters" / "shape.svg").write_text(svg, encoding="utf-8")
    result = build_epub(load_book(root))
    assert any("SVG" in warning for warning in result.warnings)
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        assert "OEBPS/images/image-001.svg" in archive.namelist()
        opf = _zip_text(archive, "OEBPS/content.opf")
    assert 'media-type="image/svg+xml"' in opf


def test_raw_html_becomes_plain_text_with_warning(make_book) -> None:
    root = make_book(
        {
            "01-one.md": (
                "# One\n\n<div class=\"fancy\">Hello <b>there</b>.</div>\n"
            )
        }
    )
    result = build_epub(load_book(root))
    assert any("raw HTML" in warning for warning in result.warnings)
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        chapter = _zip_text(archive, "OEBPS/text/chapter-01.xhtml")
    assert "Hello there." in chapter
    assert "<div class=\"fancy\">" not in chapter


def test_metadata_and_titles_are_xml_escaped(make_book) -> None:
    root = make_book(
        {
            "01-one.md": "# A & odd title\n\nText.\n",
        },
        config={
            "title": "Book <script>alert('no')</script> & Friends",
            "author": "A. & B.",
            "description": "Five > four & three < two.",
        },
    )
    result = build_epub(load_book(root))
    with zipfile.ZipFile(io.BytesIO(result.data)) as archive:
        chapter = _zip_text(archive, "OEBPS/text/chapter-01.xhtml")
        opf = _zip_text(archive, "OEBPS/content.opf")
        _parse(chapter.encode("utf-8"))
        _parse(opf.encode("utf-8"))
    assert "<script>" not in chapter
    assert "A &amp; odd title" in chapter
    assert "&lt;script&gt;" in opf
    assert "&amp; Friends" in opf


def test_epub_identifier_prefers_isbn(make_book) -> None:
    root = make_book(config={"isbn": "9781234567897"})
    result = build_epub(load_book(root))
    assert result.identifier == "urn:isbn:9781234567897"
