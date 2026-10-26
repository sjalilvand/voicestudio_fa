"""Import plain text / EPUB into the chapter-delimited script the audiobook
parser understands.

Both helpers are pure (bytes/str in, script-str out) so they're unit-tested
without a server. EPUB parsing is **stdlib only** (zipfile + ElementTree +
html.parser, plus the shared ``services.text_upload`` decoder) — no new
dependency, no network, consistent with the local-first guarantee. The output
is the same ``# Heading`` + body grammar
:func:`services.audiobook.parse_audiobook_script` already consumes, so import is
just a front door onto the existing pipeline.
"""

from __future__ import annotations

import io
import logging
import posixpath
import re
import zipfile
import zlib
from html.parser import HTMLParser
from xml.etree import ElementTree as ET
from urllib.parse import unquote, urlsplit

from services.text_upload import bom_encoding, decode_text_upload

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
# An EPUB document declares its own encoding: XML in the declaration, the XHTML
# serialisation additionally in a `<meta charset>`. Both sit in the prologue, so
# only the head of the document is scanned — the patterns never run over a whole
# book, and neither has overlapping quantifiers (ReDoS-safe).
_XML_DECL_ENCODING_RE = re.compile(
    rb"""<\?xml[^>]{0,200}?encoding\s*=\s*["']([A-Za-z0-9_.:+-]{1,40})["']"""
)
_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]{0,400}?charset\s*=\s*["']?\s*([A-Za-z0-9_.:+-]{1,40})""",
    re.IGNORECASE,
)
_DECLARATION_SCAN_BYTES = 1024
# Recognize markup or XML whitespace in BOM-less wide documents. Widest
# first: a UTF-32 LE prefix also starts with its UTF-16 LE counterpart.
_NO_BOM_WIDE_PREFIXES = tuple(
    (char.encode(encoding), encoding)
    for encoding in ("utf-32-le", "utf-32-be", "utf-16-le", "utf-16-be")
    for char in "< \t\r\n"
)

logger = logging.getLogger("omnivoice.longform_import")


def _declared_encoding(raw: bytes) -> str | None:
    """The encoding an EPUB document names for itself, as written."""
    head = raw[:_DECLARATION_SCAN_BYTES]
    for pattern in (_XML_DECL_ENCODING_RE, _META_CHARSET_RE):
        match = pattern.search(head)
        if match:
            return match.group(1).decode("ascii", "ignore")
    return None


def _decode_epub_entry(raw: bytes) -> str:
    """Decode one EPUB document by the encoding it actually carries.

    UTF-8 is only the *default* for an XML document — a BOM or an
    ``encoding=``/``charset=`` declaration overrides it, and EPUB 2 books
    (and Calibre conversions of older HTML) routinely declare ISO-8859-1 or a
    CJK code page. Decoding those as UTF-8 with ``errors="ignore"`` silently
    *deleted* every byte their accents, dashes and curly quotes are spelled
    with, so "Le café était fermé" imported — and was narrated — as "Le caf
    tait ferm". ``decode_text_upload`` is the same BOM → UTF-8 →
    Windows-1252 ladder the ``.txt``/``.md`` import branch already uses.
    """
    # A byte-order mark outranks any declaration (XML 1.0 §F), and
    # decode_text_upload owns the one BOM table both front doors read.
    if not bom_encoding(raw):
        for prefix, wide in _NO_BOM_WIDE_PREFIXES:
            if raw.startswith(prefix):
                return raw.decode(wide, errors="replace")
        declared = _declared_encoding(raw)
        if declared:
            try:
                # errors="replace": a mis-declared document still imports, the
                # way an undeclared one does. Nothing here may fail a book.
                return raw.decode(declared, errors="replace")
            except (LookupError, UnicodeError):
                # An encoding Python doesn't have, or a bytes-to-bytes codec
                # such as "hex_codec" — those resolve but refuse to produce
                # text. Guess the way an undeclared document is guessed.
                logger.warning(
                    "EPUB entry declares an encoding that cannot decode text; guessing instead"
                )
    return decode_text_upload(raw)


def chapterize_plaintext(text: str) -> str:
    """Insert ``# `` headings ahead of obvious chapter-title lines.

    No-op if the text already has Markdown H1 headings (the user has structured
    it). Otherwise short standalone lines beginning with a chapter keyword
    (``Chapter 3``, ``Prologue`` …) become headings; body text is preserved with
    line endings normalized to LF. Text with no detectable breaks falls through
    as a single chapter.
    """
    text = text or ""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if _H1_RE.search(normalized):
        return text
    out = []
    for line in normalized.split("\n"):
        s = line.strip()
        if s and len(s) <= _CHAPTER_TITLE_MAX and _CH_RE.match(s):
            out.append(f"# {s}")
        else:
            out.append(line)
    return "\n".join(out)


# ── XHTML text extraction ────────────────────────────────────────────────────

_OPS_NS = "http://www.idpf.org/2007/ops"
_VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta param source track wbr".split()
)
_BREAKING_TAGS = frozenset(
    "p div h1 h2 h3 h4 h5 h6 li ul ol tr td th table caption thead tbody tfoot "
    "blockquote pre hr section article aside header footer nav main figure "
    "figcaption dl dt dd address details summary fieldset form".split()
)
_DROPPED_TAGS = frozenset({"script", "style", "head"})
_STRUCTURAL_TAGS = frozenset({"body", "main", "section", "article", "div"})
_TITLE_TAGS = frozenset({"h1", "h2", "title"})
# One whole class token: page, optional hyphen, break | num | number, optional -rw.
_PAGE_CLASS_RE = re.compile(r"page-?(?:break|num(?:ber)?)(?:-rw)?", re.IGNORECASE)


class _Frame:
    """One open element on the extractor's stack."""

    __slots__ = ("tag", "outer_ns", "hides")

    def __init__(self, tag: str, outer_ns: dict, hides: bool):
        self.tag = tag
        self.outer_ns = outer_ns
        self.hides = hides


class _TextExtractor(HTMLParser):
    """Collect narratable text, the first heading and the epub:type tokens of
    ONE document. Feed it a single document, then read ``result()``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.types: set[str] = set()
        self._chunks: list[str] = []
        self._stack: list[_Frame] = []
        self._hidden = 0  # open frames whose content is not narrated
        self._ns = {"epub": _OPS_NS}
        self._title_text = ""
        self._title_done = False
        self._title_at: int | None = None  # stack index of the heading being read
        self._title_parts: list[str] = []

    # -- helpers --------------------------------------------------------
    def _ops_values(self, attrs, name: str) -> list[str]:
        """Values of attribute ``name`` under whatever prefix maps to the ops URI."""
        found = []
        for key, value in attrs:
            prefix, sep, local = key.partition(":")
            if sep and local == name and self._ns.get(prefix) == _OPS_NS:
                found.append(value or "")
        return found

    def _line_break(self) -> None:
        if self._hidden:
            return
        if self._title_at is not None:
            self._title_parts.append(" ")
        else:
            self._chunks.append("\n")

    def _is_page_marker(self, attrs) -> bool:
        for raw in self._ops_values(attrs, "type"):
            if "pagebreak" in raw.split():
                return True
        for key, value in attrs:
            if key == "role" and "doc-pagebreak" in (value or "").split():
                return True
            if key == "class" and any(
                _PAGE_CLASS_RE.fullmatch(tok) for tok in (value or "").split()
            ):
                return True
        return False

    def _enter(self, tag: str, attrs, self_closing: bool) -> None:
        outer = self._ns
        declared = {
            key[6:]: (value or "") for key, value in attrs if key.startswith("xmlns:")
        }
        if declared:
            self._ns = {**outer, **declared}
        try:
            if tag == "body":
                self._leave("head")  # an unclosed <head> ends where <body> begins
            marker = self._is_page_marker(attrs)
            if marker and self_closing:
                return  # an empty marker vanishes without leaving a break
            if tag in _VOID_TAGS:
                if tag == "br" and not marker:
                    self._line_break()
                elif tag == "hr" and not marker:
                    self._line_break()
                return
            if not self._hidden and tag in _STRUCTURAL_TAGS:
                for raw in self._ops_values(attrs, "type"):
                    self.types.update(raw.split())
            hides = marker or tag in _DROPPED_TAGS
            if tag in _BREAKING_TAGS:
                self._line_break()
            if self_closing:
                return
            self._stack.append(_Frame(tag, outer, hides))
            if hides:
                self._hidden += 1
            elif (
                tag in _TITLE_TAGS
                and not self._title_done
                and self._title_at is None
                and not self._hidden
            ):
                self._title_at = len(self._stack) - 1
                self._title_parts = []
        finally:
            if self_closing or tag in _VOID_TAGS:
                self._ns = outer

    def _leave(self, tag: str) -> None:
        for idx in range(len(self._stack) - 1, -1, -1):
            if self._stack[idx].tag == tag:
                break
        else:
            return
        released = self._stack[idx:]
        del self._stack[idx:]
        self._ns = released[0].outer_ns
        self._hidden -= sum(1 for f in released if f.hides)
        if self._title_at is not None and self._title_at >= idx:
            candidate = " ".join("".join(self._title_parts).split())
            self._title_at = None
            self._title_parts = []
            if candidate:
                self._title_text = candidate
                self._title_done = True

    # -- HTMLParser hooks ---------------------------------------------------
    def handle_starttag(self, tag, attrs):
        self._enter(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        self._enter(tag, attrs, True)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        self._leave(tag)
        if tag in _BREAKING_TAGS:
            self._line_break()

    def handle_data(self, data):
        if self._hidden:
            return
        if self._title_at is not None:
            self._title_parts.append(data)
        else:
            self._chunks.append(data)

    def result(self) -> tuple[set[str], str, str]:
        lines = [ln.strip() for ln in "".join(self._chunks).split("\n")]
        kept: list[str] = []
        for ln in lines:
            if ln or (kept and kept[-1]):
                kept.append(ln)
        return self.types, self._title_text, "\n".join(kept).strip()


def _extract_document(xhtml: str) -> tuple[set[str], str, str]:
    """(epub:type tokens, chapter title, body) for one XHTML document.

    A parser failure keeps whatever was collected before it: a partly narrated
    chapter beats one that silently vanishes from the book (#1161).
    """
    extractor = _TextExtractor()
    try:
        extractor.feed(xhtml)
        extractor.close()
    except Exception as exc:  # noqa: BLE001 — see docstring
        logger.warning("EPUB chapter HTML parsing failed (%s); keeping the text read so far", exc)
    return extractor.result()


def _html_to_title_body(xhtml: str) -> tuple[str, str]:
    _types, title, body = _extract_document(xhtml)
    return title, body


# ── EPUB package handling ─────────────────────────────────────────────────

_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
_NCX_MEDIA_TYPE = "application/x-dtbncx+xml"
_BODY_TYPES = frozenset(
    "bodymatter chapter part prologue epilogue introduction preface foreword volume".split()
)
_ANCILLARY_TYPES = frozenset(
    "frontmatter backmatter cover titlepage halftitlepage copyright-page toc landmarks "
    "dedication acknowledgments imprint colophon contributors other-credits epigraph "
    "loi lot index glossary bibliography appendix".split()
)
_ANCILLARY_TITLE_RE = re.compile(
    r"(?:cover|half[ -]?title|title[ -]?page|copyright|dedication|contents|"
    r"table of contents|acknowledg\w*|about the (?:author|illustrator|book)|"
    r"also by|also available|praise for|imprint|colophon|newsletter|look out for|"
    r"(?:other )?(?:works|books|titles) by|about the publisher|footnotes?|endnotes?)\b",
    re.IGNORECASE,
)
_PUBLISHER_HEADING_RE = re.compile(r"(?:novels by|published by|bibliography)\b", re.IGNORECASE)
# A page with no heading and no more words than this, outside the table of
# contents, is treated as a stray page rather than a chapter.
_SHORT_PAGE_WORDS = 400


def _member_path(owner: str, ref: str) -> str:
    """Zip member named by URI reference ``ref`` found inside document ``owner``."""
    try:
        parts = urlsplit(ref.strip())
    except ValueError:
        return ""
    if parts.scheme or parts.netloc or not parts.path:
        return ""
    target = unquote(parts.path)  # decoded exactly once
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(owner), target))
    joined = joined.lstrip("/")
    if joined in ("", ".") or joined.startswith("../") or joined == "..":
        return ""
    return joined


class _ReadBudget:
    """Zip-bomb guard shared by every member read of one import."""

    def __init__(self, archive: zipfile.ZipFile, max_entry: int, max_total: int):
        self._zf = archive
        self._max_entry = max_entry
        self._max_total = max_total
        self.used = 0

    @property
    def exhausted(self) -> bool:
        return self.used >= self._max_total

    def read(self, name: str, *, required: bool = False) -> bytes | None:
        try:
            info = self._zf.getinfo(name)
        except KeyError:
            if required:
                raise ValueError(f"not a valid EPUB: {name} is missing") from None
            return None
        room = min(self._max_entry, self._max_total - self.used)
        if info.file_size > room:
            if required:
                raise ValueError(f"{name} exceeds the import size limit")
            return None
        try:
            # The declared size was checked above and ZipFile.read never yields more.
            data = self._zf.read(info)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError, OSError, zlib.error) as exc:
            raise ValueError(f"{name} is unreadable inside this EPUB ({exc})") from exc
        if len(data) > room:
            if required:
                raise ValueError(f"{name} exceeds the import size limit")
            return None
        self.used += len(data)
        return data


def _local(tag: object) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _flat_text(node: ET.Element) -> str:
    return " ".join("".join(node.itertext()).split())


def _ops_tokens(node: ET.Element) -> set[str]:
    return set((node.get("{%s}type" % _OPS_NS) or "").split())


def is_ancillary(types: set[str], title: str) -> bool:
    """True for front/back matter that should not be narrated as a chapter."""
    if types & _BODY_TYPES:
        return False
    if types & _ANCILLARY_TYPES:
        return True
    return bool(title) and _ANCILLARY_TITLE_RE.match(title.strip()) is not None


def _parse_nav_documents(budget, names, nav_paths):
    """Read each navigation document; return (epub3 labels, ncx labels, landmark start)."""
    nav3: dict[str, str] = {}
    ncx: dict[str, str] = {}
    start: str | None = None
    for nav_path in nav_paths:
        raw = budget.read(nav_path, required=False)
        if raw is None:
            continue
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as exc:
            logger.warning("EPUB navigation %s is not well-formed (%s); using headings", nav_path, exc)
            continue
        navs = [el for el in root.iter() if _local(el.tag) == "nav"]
        toc_navs = [n for n in navs if "toc" in _ops_tokens(n)]
        if not toc_navs:
            toc_navs = [n for n in navs if not _ops_tokens(n)]
        for nav in toc_navs:
            for anchor in nav.iter():
                href = anchor.get("href")
                if _local(anchor.tag) != "a" or not href:
                    continue
                target, label = _member_path(nav_path, href), _flat_text(anchor)
                if target and label:
                    nav3.setdefault(target, label)
        if start is None:
            for nav in navs:
                if "landmarks" not in _ops_tokens(nav):
                    continue
                for anchor in nav.iter():
                    if (
                        _local(anchor.tag) == "a"
                        and anchor.get("href")
                        and "bodymatter" in _ops_tokens(anchor)
                    ):
                        start = _member_path(nav_path, anchor.get("href")) or None
                        break
                if start:
                    break
        for point in root.iter():
            if _local(point.tag) != "navPoint":
                continue
            label_el = next((c for c in point if _local(c.tag) == "navLabel"), None)
            content_el = next((c for c in point if _local(c.tag) == "content"), None)
            if label_el is None or content_el is None or not content_el.get("src"):
                continue
            target, label = _member_path(nav_path, content_el.get("src")), _flat_text(label_el)
            if target and label:
                ncx.setdefault(target, label)
    return nav3, ncx, start


def toc_titles(budget, names, nav_paths) -> tuple[dict[str, str], str | None]:
    """(spine path -> table-of-contents label, declared reading start or None)."""
    nav3, ncx, start = _parse_nav_documents(budget, names, nav_paths)
    return {**ncx, **nav3}, start


def front_matter_end(sections, toc, declared) -> tuple[int, bool]:
    """Index of the first narrated section, and whether the book declared it."""
    if declared:
        for idx, section in enumerate(sections):
            if section[0] == declared:
                return idx, True
    for idx, (path, types, _heading, _body) in enumerate(sections):
        label = toc.get(path)
        if label and not is_ancillary(types, label):
            return idx, False
    return 0, False


def _opf_location(budget) -> str:
    raw = budget.read("META-INF/container.xml", required=True)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError(f"the EPUB container file is not valid XML: {exc}") from exc
    for el in root.iter("{%s}rootfile" % _CONTAINER_NS):
        if el.get("full-path"):
            return el.get("full-path").lstrip("/")
    raise ValueError("EPUB container has no rootfile entry")


def epub_to_chapter_script(
    data: bytes,
    *,
    max_entry_bytes: int = _EPUB_MAX_ENTRY_BYTES,
    max_total_bytes: int = _EPUB_MAX_TOTAL_BYTES,
) -> str:
    """Turn EPUB bytes into the ``# Title`` / body script the audiobook parser reads."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid EPUB (the file is not a zip archive)") from exc
    with archive:
        names = set(archive.namelist())
        budget = _ReadBudget(archive, max_entry_bytes, max_total_bytes)
        opf_path = _opf_location(budget)
        try:
            opf = ET.fromstring(budget.read(opf_path, required=True))
        except ET.ParseError as exc:
            raise ValueError(f"the EPUB package file {opf_path} is not well-formed: {exc}") from exc

        manifest: dict[str, str] = {}
        nav_paths: list[str] = []
        for item in opf.iter():
            if _local(item.tag) != "item" or not item.get("href"):
                continue
            target = _member_path(opf_path, item.get("href"))
            if not target:
                continue
            if item.get("id"):
                manifest[item.get("id")] = target
            if "nav" in (item.get("properties") or "").split() or (
                item.get("media-type") == _NCX_MEDIA_TYPE
            ):
                nav_paths.append(target)

        toc, declared = toc_titles(budget, names, nav_paths)
        if declared is None:
            for ref in opf.iter():
                if (
                    _local(ref.tag) == "reference"
                    and (ref.get("type") or "").lower() == "text"
                    and ref.get("href")
                ):
                    declared = _member_path(opf_path, ref.get("href")) or None
                    break

        sections = []
        nav_set = set(nav_paths)
        for ref in opf.iter():
            if _local(ref.tag) != "itemref":
                continue
            if budget.exhausted:
                break
            path = manifest.get(ref.get("idref") or "")
            if (
                not path
                or path in nav_set
                or (ref.get("linear") or "").lower() == "no"
                or path not in names
            ):
                continue
            raw = budget.read(path, required=False)
            if raw is None:
                continue
            types, heading, body = _extract_document(_decode_epub_entry(raw))
            if body.strip():
                sections.append((path, types, heading, body))

    start, _declared_start = front_matter_end(sections, toc, declared)
    blocks: list[str] = []
    back_matter = False
    for idx, (path, types, heading, body) in enumerate(sections):
        label = toc.get(path)
        title = label or heading
        listed = label is not None
        unlisted = not listed and not (types & _BODY_TYPES)
        short = len(body.split()) <= _SHORT_PAGE_WORDS
        stray = not heading and short
        if is_ancillary(types, title):
            if listed and idx > start:
                back_matter = True
            continue
        if unlisted and short:
            # Before the start, a headingless page is a teaser or blurb. A press
            # page announces itself by heading, at the front of any book.
            press_page = bool(heading) and _PUBLISHER_HEADING_RE.match(heading) is not None
            if (idx < start and not heading) or (press_page and (idx < start or not blocks)):
                continue
        if back_matter and unlisted and stray:
            continue
        back_matter = False
        blocks.append(f"# {title or f'Chapter {len(blocks) + 1}'}\n\n{body}")
    if not blocks:
        raise ValueError("no readable chapters were found in this EPUB")
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
