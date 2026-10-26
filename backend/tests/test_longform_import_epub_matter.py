"""Book furniture, navigation and archive limits for EPUB import."""
import io
import zipfile
from textwrap import dedent

import pytest

from services.longform_import import _extract_document, _html_to_title_body, epub_to_chapter_script

OPS_URI = "http://www.idpf.org/2007/ops"
CONTAINER_URI = "urn:oasis:names:tc:opendocument:xmlns:container"
GOOD_CONTAINER = f'<container xmlns="{CONTAINER_URI}"><rootfiles><rootfile full-path="pkg/book.opf"/></rootfiles></container>'


class Book:
    """Collects parts, then serialises an in-memory EPUB archive."""

    def __init__(self, container=GOOD_CONTAINER, stored=False):
        self.container = container
        self.method = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
        self.files = []  # (file name, markup) in spine order
        self.nav = None
        self.ncx = None
        self.guide = ""

    def add(self, name, markup):
        self.files.append((name, markup))
        return self

    def bytes(self):
        manifest = [f'<item id="f{n}" href="{name}"/>' for n, (name, _) in enumerate(self.files)]
        if self.nav is not None:
            manifest.append('<item id="nv" href="nav.xhtml" properties="nav"/>')
        if self.ncx is not None:
            manifest.append('<item id="nx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
        refs = "".join(f'<itemref idref="f{n}"/>' for n in range(len(self.files)))
        package = (
            '<package xmlns="http://www.idpf.org/2007/opf">'
            f'<manifest>{"".join(manifest)}</manifest><spine>{refs}</spine>'
            f'<guide>{self.guide}</guide></package>'
        )
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", self.method) as archive:
            archive.writestr("META-INF/container.xml", self.container)
            archive.writestr("pkg/book.opf", package)
            for name, markup in self.files:
                archive.writestr("pkg/" + name, markup)
            if self.nav is not None:
                archive.writestr("pkg/nav.xhtml", self.nav)
            if self.ncx is not None:
                archive.writestr("pkg/toc.ncx", self.ncx)
        return out.getvalue()

    def script(self, **limits):
        return epub_to_chapter_script(self.bytes(), **limits)


def doc(inner, body_attrs=""):
    return f'<html xmlns:epub="{OPS_URI}"><body {body_attrs}>{inner}</body></html>'


def prose(count, word="river"):
    return " ".join([word] * count)


def chapter(n, words=40):
    return f"chap{n}.xhtml", doc(f"<h1>Part {n}</h1><p>{prose(words, 'tide')}</p>")


def nav_of(entries, kind="toc"):
    items = "".join(f'<li><a href="{h}">{t}</a></li>' for h, t in entries)
    return f'<html xmlns:epub="{OPS_URI}"><body><nav epub:type="{kind}"><ol>{items}</ol></nav></body></html>'


def headings(script):
    return [line[2:] for line in script.splitlines() if line.startswith("# ")]


# ---- print page markers -----------------------------------------------------

@pytest.mark.parametrize("tag", [
    f'<span epub:type="pagebreak">41</span>',
    '<span role="doc-pagebreak">41</span>',
    '<span class="pagenum">41</span>',
    '<span class="page-number-rw">41</span>',
])
def test_markers_leave_prose_joined(tag):
    _, text = _html_to_title_body(doc(f"<p>left {tag}right</p>"))
    assert text == "left right"


def test_empty_block_marker_disappears_without_a_break():
    _, text = _html_to_title_body(doc('<p>before<div role="doc-pagebreak"/>after</p>'))
    # No marker, no newline: only the paragraph edges break lines.
    assert text == "beforeafter"
    _, text = _html_to_title_body(doc('<p>one</p><span epub:type="pagebreak"/><p>two</p>'))
    assert text.replace("\n", "|").replace("||", "|") == "one|two"


def test_block_marker_with_number_leaves_nothing_behind():
    _, text = _html_to_title_body(doc('<p>x</p><div class="pagebreak">iv</div><p>y</p>'))
    assert "iv" not in text and "x" in text and "y" in text


def test_same_tag_nested_in_a_marker_is_skipped_whole():
    _, text = _html_to_title_body(doc('<p>a<span epub:type="pagebreak">1<span>2</span>3</span>b</p>'))
    assert text == "ab"


@pytest.mark.parametrize("tag", ['<br role="doc-pagebreak">', '<span class="page-num"/>'])
def test_void_markers_never_hide_what_follows(tag):
    _, text = _html_to_title_body(doc(f"<p>front{tag} back</p>"))
    assert "front" in text and "back" in text


def test_page_break_styling_and_plain_numbers_survive():
    _, text = _html_to_title_body(doc('<div class="page-break-before"><p>In 1984, chapter IV.</p></div>'))
    assert "In 1984, chapter IV." in text


# ---- namespaces ---------------------------------------------------------------

def test_types_follow_the_uri_not_the_prefix():
    types, _, _ = _extract_document(f'<html xmlns:z="{OPS_URI}"><body><div z:type="chapter">t</div></body></html>')
    assert types == {"chapter"}
    types, _, _ = _extract_document('<html xmlns:z="urn:elsewhere"><body><div z:type="chapter">t</div></body></html>')
    assert types == set()


def test_inner_prefix_rebinding_is_scoped_to_its_element():
    markup = (f'<html xmlns:q="{OPS_URI}"><body>'
              '<div xmlns:q="urn:elsewhere" q:type="hidden">a</div>'
              '<div q:type="frontmatter">b</div></body></html>')
    types, _, _ = _extract_document(markup)
    assert types == {"frontmatter"}


def test_main_counts_as_structural_but_paragraphs_do_not():
    types, _, _ = _extract_document('<body><main epub:type="bodymatter">x</main><p epub:type="cover">y</p></body>')
    assert types == {"bodymatter"}


# ---- skipping furniture ---------------------------------------------------------

def test_typed_matter_is_dropped():
    book = Book()
    book.add("a.xhtml", doc(f"<p>{prose(5)}</p>", 'epub:type="cover"'))
    book.add("b.xhtml", doc(f"<p>{prose(5)}</p>", 'epub:type="copyright-page"'))
    book.add(*chapter(1)).add(*chapter(2))
    book.add("z.xhtml", doc(f"<p>{prose(5)}</p>", 'epub:type="index"'))
    assert headings(book.script()) == ["Part 1", "Part 2"]


def test_untyped_books_use_title_wording():
    book = Book()
    for label in ("Title Page", "Dedication", "Acknowledgements"):
        book.add(label[:3] + ".xhtml", doc(f"<h1>{label}</h1><p>{prose(6)}</p>"))
    book.add(*chapter(1))
    book.add("end.xhtml", doc(f"<h1>About the Author</h1><p>{prose(6)}</p>"))
    assert headings(book.script()) == ["Part 1"]


def test_body_type_outranks_a_suspicious_title():
    book = Book().add("d.xhtml", doc(f"<h1>Dedication Day</h1><p>{prose(30)}</p>", 'epub:type="bodymatter chapter"'))
    assert headings(book.script()) == ["Dedication Day"]


def test_vague_one_word_headings_stay():
    book = Book()
    book.add("a.xhtml", doc(f"<h1>About</h1><p>{prose(30)}</p>"))
    book.add("b.xhtml", doc(f"<h1>Notes</h1><p>{prose(30)}</p>"))
    assert headings(book.script()) == ["About", "Notes"]


@pytest.mark.parametrize("lead", ["Published by Lantern Press", "Novels by A. Writer", "Bibliography"])
def test_press_pages_at_the_front_go_even_without_a_declared_start(lead):
    book = Book()
    book.add("press.xhtml", doc(f"<h2>{lead}</h2><p>{prose(25)}</p>"))
    book.add(*chapter(1))
    assert headings(book.script()) == ["Part 1"]


def test_long_press_style_page_is_kept():
    book = Book()
    book.add("big.xhtml", doc(f"<h2>Published by Lantern Press</h2><p>{prose(450)}</p>"))
    book.add(*chapter(1))
    assert len(headings(book.script())) == 2


# ---- navigation ---------------------------------------------------------------------

def test_toc_labels_name_chapters_with_any_quote_style_and_prefix():
    book = Book().add(*chapter(1)).add(*chapter(2))
    book.nav = (f"<html xmlns:k='{OPS_URI}'><body><nav k:type='toc'><a href='chap1.xhtml'>First</a>"
                "<a href='chap2.xhtml#s'>Second</a></nav></body></html>")
    assert headings(book.script()) == ["First", "Second"]


def test_only_the_toc_nav_names_chapters():
    book = Book().add(*chapter(1))
    book.nav = (f'<html xmlns:epub="{OPS_URI}" xmlns:o="urn:elsewhere"><body>'
                '<nav o:type="toc"><a href="chap1.xhtml">Decoy</a></nav>'
                '<nav epub:type="toc"><a href="chap1.xhtml">Genuine</a></nav>'
                '<nav epub:type="landmarks"><a href="chap1.xhtml">Landmark</a></nav></body></html>')
    assert headings(book.script()) == ["Genuine"]


def test_page_list_alone_names_nothing():
    book = Book().add(*chapter(1))
    book.nav = nav_of([("chap1.xhtml", "Numbers")], kind="page-list")
    assert headings(book.script()) == ["Part 1"]


def ncx(prefix=""):
    p = f"{prefix}:" if prefix else ""
    decl = f"xmlns:{prefix}" if prefix else "xmlns"
    return (f'<{p}ncx {decl}="http://www.daisy.org/z3986/2005/ncx/"><{p}navMap><{p}navPoint>'
            f'<{p}navLabel><{p}text>Legacy</{p}text></{p}navLabel><{p}content src="chap1.xhtml"/>'
            f'</{p}navPoint></{p}navMap></{p}ncx>')


@pytest.mark.parametrize("prefix", ["", "dc"])
def test_ncx_supplies_labels(prefix):
    book = Book().add(*chapter(1))
    book.ncx = ncx(prefix)
    assert headings(book.script()) == ["Legacy"]


def test_nav_document_overrides_ncx():
    book = Book().add(*chapter(1))
    book.ncx = ncx()
    book.nav = nav_of([("chap1.xhtml", "Modern")])
    assert headings(book.script()) == ["Modern"]


def test_unusable_navigation_falls_back_to_headings(caplog):
    book = Book().add(*chapter(1))
    book.nav = "<html><nav>"
    with caplog.at_level("WARNING"):
        assert headings(book.script()) == ["Part 1"]
    assert caplog.records
    book.nav = "<html><body><p>no navigation element</p></body></html>"
    assert headings(book.script()) == ["Part 1"]


# ---- limits and damage --------------------------------------------------------------------

def test_oversized_nav_is_not_even_opened(monkeypatch):
    book = Book().add(*chapter(1))
    book.nav = nav_of([("chap1.xhtml", "Big")]) + "<!--" + "-" * 6000 + "-->"
    raw = book.bytes()  # build first: writing also goes through ZipFile.open
    opened = []
    real = zipfile.ZipFile.open
    monkeypatch.setattr(zipfile.ZipFile, "open",
                        lambda self, n, *a, **k: (opened.append(getattr(n, "filename", n)), real(self, n, *a, **k))[1])
    assert headings(epub_to_chapter_script(raw, max_entry_bytes=4000)) == ["Part 1"]
    assert "pkg/nav.xhtml" not in opened


def test_required_parts_are_bounded_and_charged():
    raw = Book().add(*chapter(1)).bytes()
    with pytest.raises(ValueError, match="size limit"):
        epub_to_chapter_script(raw, max_entry_bytes=30)
    with pytest.raises(ValueError, match="size limit"):
        epub_to_chapter_script(raw, max_total_bytes=len(GOOD_CONTAINER) + 20)


def test_required_parts_alone_can_exhaust_the_total():
    book = Book().add(*chapter(1))
    book.nav = nav_of([("chap1.xhtml", "Label")])
    with zipfile.ZipFile(io.BytesIO(book.bytes())) as z:
        required = sum(z.getinfo(n).file_size for n in ("META-INF/container.xml", "pkg/book.opf", "pkg/nav.xhtml"))
    with pytest.raises(ValueError):
        # Everything beyond the required parts is unaffordable: nothing is left to read.
        book.script(max_total_bytes=required - 1)


def test_corrupt_member_is_a_value_error_not_a_skip():
    raw = bytearray(Book(stored=True).add(*chapter(1)).bytes())
    raw[raw.index(b"Part 1")] ^= 0x55
    with pytest.raises(ValueError, match="unreadable"):
        epub_to_chapter_script(bytes(raw))


def test_broken_deflate_stream_is_a_value_error():
    raw = bytearray(Book().add("c.xhtml", doc(f"<p>{prose(300)}</p>")).bytes())
    info = zipfile.ZipFile(io.BytesIO(bytes(raw))).getinfo("pkg/c.xhtml")
    middle = info.header_offset + 30 + len(info.filename) + 4 + 2
    for i in range(middle, middle + 6):
        raw[i] ^= 0xFF
    with pytest.raises(ValueError):
        epub_to_chapter_script(bytes(raw))


def test_bad_container_is_reported_as_invalid_xml():
    with pytest.raises(ValueError) as caught:
        Book(container="<container").add(*chapter(1)).script()
    text = str(caught.value)
    assert "container" in text and "XML" in text


def test_container_without_rootfile():
    with pytest.raises(ValueError, match="rootfile"):
        Book(container=f'<container xmlns="{CONTAINER_URI}"/>').add(*chapter(1)).script()


# ---- where the book really starts --------------------------------------------------------------

def landmark_nav(target):
    return dedent(f"""\
        <html xmlns:epub="{OPS_URI}"><body>
        <nav epub:type="landmarks"><a epub:type="bodymatter" href="{target}">Begin</a></nav>
        <nav epub:type="toc"><a href="chap1.xhtml">Opening</a></nav></body></html>""")


def test_declared_start_discards_the_unlisted_teaser():
    book = Book().add("teaser.xhtml", doc(f"<p>{prose(30, 'hook')}</p>")).add(*chapter(1))
    book.nav = landmark_nav("chap1.xhtml")
    script = book.script()
    assert headings(script) == ["Opening"] and "hook" not in script


def test_guide_text_reference_also_declares_the_start():
    book = Book().add("teaser.xhtml", doc(f"<p>{prose(30, 'hook')}</p>")).add(*chapter(1))
    book.guide = '<reference type="text" href="chap1.xhtml"/>'
    assert "hook" not in book.script()


def test_real_prologue_before_the_start_is_kept():
    book = Book().add("pro.xhtml", doc(f"<p>{prose(500, 'once')}</p>")).add(*chapter(1))
    book.nav = landmark_nav("chap1.xhtml")
    assert "once" in book.script()


def test_listed_pages_before_the_start_are_kept():
    book = Book().add(*chapter(1)).add(*chapter(2))
    book.nav = dedent(f"""\
        <html xmlns:epub="{OPS_URI}"><body>
        <nav epub:type="landmarks"><a epub:type="bodymatter" href="chap2.xhtml">go</a></nav>
        <nav epub:type="toc"><a href="chap1.xhtml">A</a><a href="chap2.xhtml">B</a></nav></body></html>""")
    assert headings(book.script()) == ["A", "B"]


def test_toc_only_start_trims_short_headingless_pages_alone():
    book = Book()
    book.add("t.xhtml", doc(f"<p>{prose(20, 'blurb')}</p>"))
    book.add("h.xhtml", doc(f"<h1>Epigraph Words</h1><p>{prose(20)}</p>"))
    book.add(*chapter(1))
    book.nav = nav_of([("chap1.xhtml", "Opening")])
    script = book.script()
    assert "blurb" not in script and "Epigraph Words" in headings(script)


def test_strays_are_dropped_only_after_listed_back_matter():
    book = Book().add(*chapter(1))
    book.add("about.xhtml", doc(f"<h1>About the Author</h1><p>{prose(10, 'bio')}</p>"))
    book.add("stray.xhtml", doc(f"<p>{prose(10, 'ad')}</p>"))
    book.nav = nav_of([("chap1.xhtml", "One"), ("about.xhtml", "About the Author")])
    assert "ad " not in book.script() + " "

    plain = Book().add(*chapter(1)).add("tail.xhtml", doc(f"<p>{prose(10, 'tail')}</p>"))
    plain.nav = nav_of([("chap1.xhtml", "One")])
    assert "tail" in plain.script()


def test_look_alike_page_does_not_open_back_matter_but_inside_it_keeps_it_open():
    nav = nav_of([("chap1.xhtml", "One"), ("about.xhtml", "About the Author")])
    look = ("look.xhtml", doc(f"<h1>Praise for the Book</h1><p>{prose(10, 'praise')}</p>"))
    stray = ("stray.xhtml", doc(f"<p>{prose(10, 'ad')}</p>"))
    about = ("about.xhtml", doc(f"<h1>About the Author</h1><p>{prose(10, 'bio')}</p>"))

    closed = Book().add(*chapter(1)).add(*look).add(*stray)
    closed.nav = nav
    assert "ad ad" in closed.script()

    opened = Book().add(*chapter(1)).add(*about).add(*look).add(*stray)
    opened.nav = nav
    assert "ad ad" not in opened.script()


def test_no_navigation_means_no_filtering_beyond_ancillary_rules():
    book = Book().add(*chapter(1)).add("s.xhtml", doc(f"<p>{prose(10, 'extra')}</p>"))
    assert "extra" in book.script()
    with pytest.raises(ValueError, match="no readable chapters"):
        Book().add("e.xhtml", doc("<p>  </p>")).script()


@pytest.mark.parametrize("entry_point", ["read", "open"])
def test_zip_level_failure_on_a_listed_chapter_is_reported_as_unreadable(monkeypatch, entry_point):
    raw = Book().add(*chapter(1)).add(*chapter(2)).bytes()
    original = getattr(zipfile.ZipFile, entry_point)

    def failing(self, name, *args, **kwargs):
        target = getattr(name, "filename", name)
        if target == "pkg/chap2.xhtml":
            raise zipfile.BadZipFile("Bad CRC-32 for file 'pkg/chap2.xhtml'")
        return original(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, entry_point, failing)
    with pytest.raises(ValueError, match="unreadable"):
        epub_to_chapter_script(raw)
