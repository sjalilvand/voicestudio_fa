"""Import plain text / EPUB into the chapter-delimited script the audiobook
parser understands.

Both helpers are pure (bytes/str in, script-str out) so they're unit-tested
without a server. EPUB parsing is **stdlib only** (zipfile + ElementTree +
html.parser) — no new dependency, no network, consistent with the local-first
guarantee. The output is the same ``# Heading`` + body grammar
:func:`services.audiobook.parse_audiobook_script` already consumes, so import is
just a front door onto the existing pipeline.
"""

from __future__ import annotations

import html
import io
import logging
import posixpath
import re
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree as ET

# A line that *starts* with a chapter keyword and is short enough to be a title
# (not a sentence that happens to begin with "Chapter"). Anchored, no ambiguous
# quantifiers → ReDoS-safe and applied per-line (short input) anyway.
_CH_RE = re.compile(r"^(?:chapter|part|book|prologue|epilogue|section)\b", re.IGNORECASE)
# Already-present Markdown H1 — if the text has any, we leave it untouched.
_H1_RE = re.compile(r"^[ \t]*#[ \t]+\S", re.MULTILINE)
_CHAPTER_TITLE_MAX = 60
# Zip-bomb / OOM guards for EPUB ingestion: per-entry and cumulative caps on
# *uncompressed* bytes read from the archive.
_EPUB_MAX_ENTRY_BYTES = 25 * 1024 * 1024
_EPUB_MAX_TOTAL_BYTES = 300 * 1024 * 1024

logger = logging.getLogger("omnivoice.longform_import")


def chapterize_plaintext(text: str) -> str:
    """Insert ``# `` headings ahead of obvious chapter-title lines.

    No-op if the text already has Markdown H1 headings (the user has structured
    it). Otherwise short standalone lines beginning with a chapter keyword
    (``Chapter 3``, ``Prologue`` …) become headings; everything else is left
    verbatim. Text with no detectable breaks falls through as a single chapter.
    """
    text = text or ""
    if _H1_RE.search(text):
        return text
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s and len(s) <= _CHAPTER_TITLE_MAX and _CH_RE.match(s):
            out.append(f"# {s}")
        else:
            out.append(line)
    return "\n".join(out)


class _TextExtractor(HTMLParser):
    """Collect visible text from XHTML, dropping script/style and collapsing
    whitespace. First <h1>/<h2>/<title> seen is kept as the chapter title."""

    _SKIP = {"script", "style", "head"}
    _BREAK = {"p", "br", "div", "h1", "h2", "h3", "li", "tr"}
    #: A print page number carried into the EPUB (EPUB 3 ``epub:type="pagebreak"``,
    #: ARIA ``role="doc-pagebreak"``, or a publisher class such as
    #: ``pagebreak-rw``). Inline, it glues onto prose ("happily as 2Zoe threw");
    #: block-level, it becomes a lone "120" / "iv" paragraph. Never narrated.
    _PAGEBREAK_CLASS = re.compile(r"page-?(break|num(ber)?)", re.I)

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self._pagebreak_stack: list[str] = []
        self._in_title = False
        self.title = ""
        #: Set once any page-number markup was seen: the only evidence on which
        #: a bare "120" / "iv" paragraph may be treated as a stray folio.
        self.saw_pagebreak = False
        #: ``epub:type`` tokens seen on the document's structural elements
        #: (``body``/``section``/``article``/``div``): "frontmatter chapter" →
        #: {"frontmatter", "chapter"}. Lets the caller drop title pages,
        #: dedications, copyright pages and other non-narrated matter.
        self.epub_types: set[str] = set()

    @classmethod
    def _is_pagebreak(cls, attrs) -> bool:
        for name, value in attrs:
            if not value:
                continue
            if name == "epub:type" and "pagebreak" in value.split():
                return True
            if name == "role" and "doc-pagebreak" in value.split():
                return True
            if name == "class" and cls._PAGEBREAK_CLASS.search(value):
                return True
        return False

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag in ("body", "section", "article", "div"):
            for name, value in attrs:
                if name == "epub:type" and value:
                    self.epub_types.update(value.split())
        if self._pagebreak_stack:
            # Nested inside a page-number element: keep skipping until it closes.
            self._pagebreak_stack.append(tag)
            return
        if self._is_pagebreak(attrs):
            self.saw_pagebreak = True
            self._pagebreak_stack.append(tag)
            return
        if tag in ("h1", "h2", "title") and not self.title:
            self._in_title = True
        if tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if self._pagebreak_stack:
            if self._pagebreak_stack[-1] == tag:
                self._pagebreak_stack.pop()
            return
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag in ("h1", "h2", "title"):
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth or self._pagebreak_stack:
            return
        if self._in_title:
            # The first heading becomes the chapter's `# Title` (metadata, not
            # narrated) — capture it but keep it out of the body. Later headings
            # (title already set) fall through and are narrated as subheadings.
            if not self.title:
                self.title = data.strip()
            return
        self._parts.append(data)

    def text(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of blank lines / trailing spaces into tidy paragraphs.
        lines = [ln.strip() for ln in raw.split("\n")]
        out: list[str] = []
        for ln in lines:
            if self.saw_pagebreak and _BARE_PAGE_NUMBER.fullmatch(ln):
                continue  # a print folio that escaped the pagebreak markup
            if ln or (out and out[-1]):
                out.append(ln)
        return "\n".join(out).strip()


#: A paragraph that is only a print folio: arabic ("120") or a *lowercase* roman
#: numeral ("iv", as front matter is paginated). Applied only to documents that
#: carry page-number markup (``_TextExtractor.saw_pagebreak``), and never to an
#: uppercase numeral ("IV" is a chapter number) or a word ("civil").
_BARE_PAGE_NUMBER = re.compile(r"\d{1,4}|(?=[ivxlc])(?:c{0,3})(?:xc|xl|l?x{0,3})(?:ix|iv|v?i{0,3})")


def _html_to_title_body(xhtml: str) -> tuple[str, str]:
    """(title, body) — see :func:`_html_extract` for the epub:type tokens too."""
    _, title, body = _html_extract(xhtml)
    return title, body


def _html_extract(xhtml: str) -> tuple[set[str], str, str]:
    p = _TextExtractor()
    try:
        p.feed(xhtml)
    except Exception:
        # Keep whatever the extractor collected before the failure: an empty
        # return would make the caller's `if not body.strip(): continue` drop
        # the whole chapter from the audiobook silently — a partial chapter
        # plus this log line is strictly more recoverable than a missing one.
        logger.warning("HTML parsing failed for EPUB entry; using partial text", exc_info=True)
    return p.epub_types, p.title, p.text()


_OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "c": "urn:oasis:names:tc:opendocument:xmlns:container"}


def _opf_path(zf: zipfile.ZipFile) -> str:
    container = zf.read("META-INF/container.xml")
    # The EPUB is a local file the user chose to import (not a remote/untrusted
    # surface); stdlib ElementTree doesn't expand external entities by default.
    root = ET.fromstring(container)  # nosec B314
    rootfile = root.find(".//c:rootfiles/c:rootfile", _OPF_NS)
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB container.xml has no rootfile")
    return rootfile.get("full-path")


#: EPUB 3 structural semantics (``epub:type``) that mark matter a narrator
#: would not read: covers, title/copyright pages, dedications, contents,
#: acknowledgements, landmarks. ``bodymatter``/``chapter``/``part`` override
#: (a chapter tagged "bodymatter chapter" is narrated even inside a "part").
_ANCILLARY_TYPES = frozenset({
    "frontmatter", "backmatter", "cover", "titlepage", "halftitlepage",
    "copyright-page", "toc", "landmarks", "dedication", "acknowledgments",
    "imprint", "colophon", "contributors", "other-credits", "epigraph",
    "loi", "lot", "index", "glossary", "bibliography", "appendix",
})
_BODY_TYPES = frozenset({"bodymatter", "chapter", "part", "prologue", "epilogue", "introduction", "preface", "foreword", "volume"})
#: Fallback for EPUBs without ``epub:type``: the section's TOC label / title.
_ANCILLARY_TITLE = re.compile(
    r"^\s*(cover|half[ -]?title|title[ -]?page|copyright|dedication|contents|"
    r"table of contents|acknowledg\w*|about the (author|illustrator|book)|"
    r"also (by|available)|praise for|imprint|colophon|newsletter|look out for)\b",
    re.I,
)


def _is_ancillary(types: set[str], title: str) -> bool:
    if types & _BODY_TYPES:
        return False
    if types & _ANCILLARY_TYPES:
        return True
    return bool(title and _ANCILLARY_TITLE.match(title))


def _toc_titles(
    zf: zipfile.ZipFile,
    base: str,
    nav_hrefs: list[str],
    names: set[str],
    *,
    max_entry_bytes: int,
    budget: list[int],
    max_total_bytes: int,
) -> dict[str, str]:
    """Map each spine document (full zip path) to its table-of-contents label.

    Publishers label sections better than their headings do ("Chapter One:
    A New Arrival" versus an ``<h1>`` holding only "A New Arrival"). Reads
    the EPUB 3 nav document (``<a href>`` entries) and the EPUB 2 NCX
    (``navPoint/content@src``); the first label for a document wins.

    Navigation documents come from the user's file like every other member,
    so they draw on the same zip-bomb guards as the spine: an entry above
    ``max_entry_bytes`` is skipped, and what is read counts against the
    shared uncompressed-byte ``budget`` (a one-item list the caller keeps
    tallying) up to ``max_total_bytes``.
    """
    titles: dict[str, str] = {}
    for href in nav_hrefs:
        full = posixpath.normpath(posixpath.join(base, href)) if base else href
        if full not in names:
            continue
        try:
            info = zf.getinfo(full)
        except KeyError:
            continue
        if info.file_size > max_entry_bytes or budget[0] + info.file_size > max_total_bytes:
            continue
        try:
            raw = zf.read(full)
        except KeyError:
            continue
        budget[0] += len(raw)
        doc = raw.decode("utf-8", "ignore")
        nav_dir = posixpath.dirname(full)
        if href.lower().endswith(".ncx"):
            pairs = [
                (src, label)
                for label, src in re.findall(
                    r"<text>(.*?)</text>\s*</navLabel>\s*<content[^>]*\bsrc\s*=\s*[\"']([^\"'#]+)", doc, re.S
                )
            ]
        else:
            pairs = re.findall(r"<a\b[^>]*\bhref\s*=\s*[\"']([^\"'#]+)(?:#[^\"']*)?[\"'][^>]*>(.*?)</a>", doc, re.S)
        for src, label in pairs:
            titles.setdefault(posixpath.normpath(posixpath.join(nav_dir, src)), _plain(label))
    return {k: v for k, v in titles.items() if v}


def _plain(markup: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(markup))).strip()


def epub_to_chapter_script(
    data: bytes,
    *,
    max_entry_bytes: int = _EPUB_MAX_ENTRY_BYTES,
    max_total_bytes: int = _EPUB_MAX_TOTAL_BYTES,
) -> str:
    """Convert EPUB bytes into a ``# Chapter`` / body script in spine order.

    Reads the OPF manifest + spine (the publisher's reading order), extracts
    each document's title + visible text, and emits one ``# Title`` block per
    document with renderable text. ``max_entry_bytes`` / ``max_total_bytes``
    bound the *uncompressed* bytes read (zip-bomb guard). Raises ``ValueError``
    on a malformed EPUB.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ValueError(f"not a valid EPUB (zip) file: {e}") from e

    opf_path = _opf_path(zf)
    opf = ET.fromstring(zf.read(opf_path))  # nosec B314 — local user EPUB; see _opf_path
    base = posixpath.dirname(opf_path)

    manifest: dict[str, str] = {}
    nav_hrefs: list[str] = []
    for item in opf.findall(".//opf:manifest/opf:item", _OPF_NS):
        iid, href = item.get("id"), item.get("href")
        if iid and href:
            manifest[iid] = href
            props = (item.get("properties") or "").split()
            if "nav" in props or item.get("media-type") == "application/x-dtbncx+xml":
                nav_hrefs.append(href)

    names = set(zf.namelist())
    budget = [0]  # cumulative uncompressed bytes read — zip-bomb guard, shared with the TOC read
    toc = _toc_titles(
        zf, base, nav_hrefs, names, max_entry_bytes=max_entry_bytes, budget=budget, max_total_bytes=max_total_bytes
    )
    total = budget[0]

    blocks: list[str] = []
    for ref in opf.findall(".//opf:spine/opf:itemref", _OPF_NS):
        href = manifest.get(ref.get("idref") or "")
        if not href or href in nav_hrefs:
            continue  # the table of contents itself is never narrated
        if (ref.get("linear") or "yes").lower() == "no":
            continue  # publisher marked it as outside the reading order
        full = posixpath.normpath(posixpath.join(base, href)) if base else href
        if full not in names:
            continue
        # Bound decompression: skip an absurdly large entry, and stop once the
        # cumulative uncompressed size crosses the ceiling (defends against a
        # zip bomb / a maliciously huge chapter exhausting memory).
        try:
            info = zf.getinfo(full)
        except KeyError:
            continue
        if info.file_size > max_entry_bytes:
            continue
        if total + info.file_size > max_total_bytes:
            break
        try:
            raw = zf.read(full)
        except KeyError:
            continue
        total += len(raw)
        types, title, body = _html_extract(raw.decode("utf-8", "ignore"))
        if not body.strip():
            continue  # nav docs, empty pages
        title = toc.get(full) or title
        if _is_ancillary(types, title):
            continue  # cover, title page, dedication, copyright, contents, …
        title = title or f"Chapter {len(blocks) + 1}"
        blocks.append(f"# {title}\n\n{body}")

    if not blocks:
        raise ValueError("no readable chapters found in the EPUB")
    return "\n\n".join(blocks)


# Page-count ceiling for PDF ingestion — a defence against a pathological
# document tying up the worker. 5000 pages comfortably covers any real book.
_PDF_MAX_PAGES = 5000


def pdf_to_chapter_script(data: bytes, *, max_pages: int = _PDF_MAX_PAGES) -> str:
    """Convert PDF bytes into a ``# Chapter`` / body script.

    Extracts the embedded text layer page-by-page (in page order), joins it,
    and runs it through :func:`chapterize_plaintext` so ``Chapter N`` /
    ``Prologue`` lines become headings — same grammar EPUB and plaintext emit.
    Unlike EPUB this needs a real parser (``pypdf``, pure-Python, no native
    deps → identical on every platform).

    Limitations surfaced as ``ValueError`` (the route maps these to a 400 with
    the message, so the user gets actionable feedback rather than a silent
    empty import):

    * **Scanned / image-only PDFs** have no text layer — there's nothing to
      extract without OCR, so we raise rather than return an empty script.
    * **Password-protected PDFs** that don't open with an empty password can't
      be read.
    """
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
    except (PdfReadError, OSError, ValueError) as e:
        raise ValueError(f"not a valid PDF file: {e}") from e

    if reader.is_encrypted:
        # Many PDFs are encrypted with an empty user password (owner-locked but
        # freely readable). Try that; a real password we can't supply.
        try:
            if reader.decrypt("") == 0:  # 0 == wrong password
                raise ValueError("PDF is password-protected")
        except (NotImplementedError, PdfReadError) as e:
            raise ValueError(f"can't read this encrypted PDF: {e}") from e

    pages = reader.pages
    if len(pages) > max_pages:
        raise ValueError(f"PDF has too many pages (max {max_pages})")

    parts: list[str] = []
    for page in pages:
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001 — one bad page shouldn't kill the import
            continue
        if text.strip():
            parts.append(text)

    if not parts:
        raise ValueError(
            "no extractable text — this looks like a scanned or image-only PDF")
    return chapterize_plaintext("\n\n".join(parts))
