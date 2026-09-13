"""Decode an uploaded text file whose encoding nobody declared.

Subtitle and manuscript uploads arrive as raw bytes. Windows tools commonly
save them as UTF-16 with a byte-order mark (Notepad's "Unicode", many subtitle
editors) or in the legacy Windows-1252 code page. A UTF-8 decode turns the
first into NUL-interleaved text and, lossily, drops every accent, dash and
curly quote from the second.
"""
from __future__ import annotations

import codecs

_BOMS = (
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def decode_text_upload(data: bytes) -> str:
    """Return the text of ``data``, without its byte-order mark.

    A BOM names the encoding. Without one, valid UTF-8 is UTF-8; anything else
    is read as Windows-1252, the legacy code page such files come from. The
    five bytes Windows-1252 leaves undefined fall back to Latin-1, so the
    decode never raises.
    """
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            return data[len(bom):].decode(encoding, errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252")
    except UnicodeDecodeError:
        return data.decode("latin-1")
