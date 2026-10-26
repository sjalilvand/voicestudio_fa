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


# CLEAN-ROOM (spec N-jaketame-2 §1): XHTML text extractor `_TextExtractor`
# (an html.parser.HTMLParser subclass whose `feed` is called once per EPUB document).
class _TextExtractor(HTMLParser):
    pass


# CLEAN-ROOM (spec N-jaketame-2 §1): `_html_to_title_body` and the epub:type-aware
# extraction helper it wraps.
def _html_to_title_body(xhtml: str) -> tuple[str, str]:
    raise NotImplementedError("clean-room reimplementation pending")


# CLEAN-ROOM (spec N-jaketame-2 §2): EPUB package handling: member-path resolution,
# container/OPF lookup, ancillary-matter classification, table-of-contents titles,
# declared reading start, the zip-bomb read budget and bounded member reads.


# CLEAN-ROOM (spec N-jaketame-2 §3): `epub_to_chapter_script`, assembling the chapter script.
def epub_to_chapter_script(
    data: bytes,
    *,
    max_entry_bytes: int = _EPUB_MAX_ENTRY_BYTES,
    max_total_bytes: int = _EPUB_MAX_TOTAL_BYTES,
) -> str:
    raise NotImplementedError("clean-room reimplementation pending")


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
