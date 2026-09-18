"""EPUB import narrates the book, not its print furniture (#2208).

A publisher EPUB carries print page numbers as ``epub:type="pagebreak"``
spans — inline they glued onto prose ("happily as 2Zoe threw"), block-level
they became lone "120" / "iv" paragraphs. Its spine also starts with a
title page, dedication and teaser and ends with the copyright page; each
came through as a "Chapter N". And the chapter heading lived in the nav
table of contents ("Chapter One: A New Arrival") while the ``<h1>`` held only
the subtitle. The extractor now drops page-number markup, skips front and
back matter (``epub:type`` first, title fallback), and titles chapters from
the TOC.
"""

import io
import zipfile

from services import longform_import as li

_CONTAINER = (
    '<?xml version="1.0"?>'
    '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
    '<rootfiles><rootfile full-path="OPS/package.opf"'
    ' media-type="application/oebps-package+xml"/></rootfiles></container>'
)


def _doc(body: str, *, title: str = "", section_type: str | None = None) -> str:
    sec = f' epub:type="{section_type}"' if section_type else ""
    return (
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        f"<head><title>{title}</title></head><body><section{sec}>{body}</section></body></html>"
    )


def _epub(docs: dict[str, str], *, nav: str | None = None, ncx: str | None = None, linear_no=()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        manifest, spine = [], []
        if nav is not None:
            z.writestr("OPS/TOC.xhtml", nav)
            manifest.append('<item id="toc" href="TOC.xhtml" media-type="application/xhtml+xml" properties="nav"/>')
        if ncx is not None:
            z.writestr("OPS/toc.ncx", ncx)
            manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        for i, (name, xhtml) in enumerate(docs.items()):
            z.writestr(f"OPS/{name}", xhtml)
            manifest.append(f'<item id="d{i}" href="{name}" media-type="application/xhtml+xml"/>')
            linear = ' linear="no"' if name in linear_no else ""
            spine.append(f'<itemref idref="d{i}"{linear}/>')
        z.writestr(
            "OPS/package.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>T</dc:title></metadata>'
            f"<manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>",
        )
    return buf.getvalue()


_NAV = (
    '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>'
    '<nav epub:type="toc"><ol>'
    '<li><a href="title.xhtml">Title Page</a></li>'
    '<li><a href="ch1.xhtml">Chapter One: A New Arrival</a></li>'
    '<li><a href="ch2.xhtml#start">Chapter Two: Too Many Questions</a></li>'
    "</ol></nav></body></html>"
)


def _publisher_epub() -> bytes:
    return _epub(
        {
            "cover.xhtml": _doc('<img src="c.jpg"/>', section_type="cover"),
            "title.xhtml": _doc("<p>The Talkative Tiger</p><p>Amelia Cobb</p>", section_type="frontmatter titlepage"),
            "teaser.xhtml": _doc(
                '<span epub:type="pagebreak" id="pi">i</span><p>“What is it?” chattered Meep.</p>',
                section_type="frontmatter",
            ),
            "dedication.xhtml": _doc("<p>For John Arthur</p>", section_type="frontmatter dedication"),
            "ch1.xhtml": _doc(
                '<div><span class="pagebreak-rw" epub:type="pagebreak" id="p1">1</span>'
                '<p class="title-num-rw">Chapter One</p><h1>A New Arrival</h1></div>'
                "<p>Alex and Nina, whistled happily as "
                '<span epub:type="pagebreak" id="p2">2</span>Zoe threw more fish.</p>'
                '<p>She handed it to Meep.<span role="doc-pagebreak" id="p3">3</span></p>'
                '<p><a class="page-number" id="p4">4</a>Someone wasn’t excited though.</p>',
                title="A New Arrival",
                section_type="bodymatter chapter",
            ),
            "ch2.xhtml": _doc(
                '<h1 id="start">Too Many Questions</h1><p>120</p><p>“Fish for breakfast!”</p><p>iv</p><p>I</p>',
                title="Too Many Questions",
                section_type="bodymatter chapter",
            ),
            "notes.xhtml": _doc("<p>Printer notes.</p>", title="Notes"),
            "copyright.xhtml": _doc(
                "<p>First published in the UK in 2021</p><p>ISBN: 978 1 78800 935 5</p>",
                section_type="backmatter copyright-page",
            ),
        },
        nav=_NAV,
        linear_no=("notes.xhtml",),
    )


def test_page_numbers_never_reach_the_narration():
    script = li.epub_to_chapter_script(_publisher_epub())
    assert "whistled happily as Zoe threw more fish." in script  # inline pagebreak span gone
    assert "She handed it to Meep.\n" in script or script.endswith("She handed it to Meep.")
    assert "Meep.3" not in script and "2Zoe" not in script and "4Someone" not in script
    lines = [ln.strip() for ln in script.split("\n")]
    assert "120" not in lines and "iv" not in lines and "i" not in lines
    assert "I" not in lines  # a lone roman numeral is a folio, not prose


def test_front_and_back_matter_are_skipped_and_chapters_take_toc_titles():
    script = li.epub_to_chapter_script(_publisher_epub())
    heads = [ln for ln in script.split("\n") if ln.startswith("# ")]
    assert heads == ["# Chapter One: A New Arrival", "# Chapter Two: Too Many Questions"]
    for furniture in ("Talkative Tiger", "Amelia Cobb", "For John Arthur", "chattered Meep", "ISBN", "First published"):
        assert furniture not in script
    assert "Printer notes" not in script  # linear="no"
    assert "Chapter One\n" in script  # the printed chapter label is still narrated


def test_untagged_epub_falls_back_to_title_heuristics():
    """No epub:type anywhere (EPUB 2 era): the section title decides."""
    epub = _epub(
        {
            "front.xhtml": _doc("<h1>Copyright</h1><p>All rights reserved.</p>", title="Copyright"),
            "toc.xhtml": _doc("<h1>Contents</h1><p>Chapter 1</p>", title="Contents"),
            "c1.xhtml": _doc("<h1>Chapter 1</h1><p>Once upon a time.</p>", title="Chapter 1"),
            "c2.xhtml": _doc("<h2>The Return</h2><p>And then.</p>", title="The Return"),
        },
        ncx=(
            '<?xml version="1.0"?><ncx xmlns="http://www.daisy.org/z3986/2005/ncx/"><navMap>'
            "<navPoint><navLabel><text>Chapter 1: The Departure</text></navLabel><content src=\"c1.xhtml\"/></navPoint>"
            "<navPoint><navLabel><text>Chapter 2: The Return</text></navLabel><content src=\"c2.xhtml#top\"/></navPoint>"
            "</navMap></ncx>"
        ),
    )
    script = li.epub_to_chapter_script(epub)
    heads = [ln for ln in script.split("\n") if ln.startswith("# ")]
    assert heads == ["# Chapter 1: The Departure", "# Chapter 2: The Return"]
    assert "All rights reserved" not in script and "Contents" not in script


def test_section_typed_as_body_matter_survives_an_ancillary_looking_title():
    epub = _epub(
        {"c1.xhtml": _doc("<h1>Acknowledgments</h1><p>A chapter really named that.</p>", section_type="bodymatter chapter")},
    )
    assert "A chapter really named that." in li.epub_to_chapter_script(epub)
