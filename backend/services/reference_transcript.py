"""Reference transcripts made from script text (#3062).

A cloning engine pairs a reference clip with its transcript. A transcript that
holds words the clip does not speak makes OmniVoice say those words at the start
of every chunk it renders. Two kinds of script text used to reach a transcript
that way:

* **Control markup.** ``[pause 1s]``, ``[voice:NAME]``, ``[speed:1.2]``,
  ``[rate 0.9]``, the SSML-lite ``[slow]…[/slow]`` family and ``[[term|say]]``
  overrides steer delivery but are never spoken as written.
  :func:`strip_script_markup` removes them; reaction tags such as
  ``[laughter]`` stay, because the take really contains them.
* **Truncated take text.** History rows saved before #3062 kept only the first
  :data:`LEGACY_HISTORY_TEXT_CAP` characters of a take, so a long take became a
  transcript that stops mid-word. :func:`take_reference_transcript` returns no
  transcript for text that may have been cut, and generation then transcribes
  the take's audio instead.

Pure and import-light (no torch), so routers and the engine layer share it.
"""
from __future__ import annotations

import re
from typing import Optional

#: History rows written before #3062 stored ``text[:200]``.
LEGACY_HISTORY_TEXT_CAP = 200

# Each alternative is a fixed literal head followed by one bounded class run
# that cannot contain brackets, so matching stays linear (ReDoS-safe).
_CONTROL_TAG_RE = re.compile(
    r"\[\s*(?:"
    r"pause(?:\s[^\[\]\n]{0,64})?"
    r"|voice\s*:[^\[\]\n]{0,128}"
    r"|speed\s*:[^\[\]\n]{0,32}"
    r"|rate(?:\s[^\[\]\n]{0,32})?"
    r"|/?(?:slow|fast|emphasis|spell)"
    r")\s*\]",
    re.IGNORECASE,
)
_INLINE_OVERRIDE_RE = re.compile(r"\[\[([^\]]{0,256})\]\]")
_HSPACE_RE = re.compile(r"[^\S\n]+")


def _spoken_override(match: re.Match) -> str:
    inner = match.group(1)
    return inner.split("|", 1)[1] if "|" in inner else inner


def strip_script_markup(text: Optional[str]) -> str:
    """``text`` with the script's control markup removed, as it was spoken."""
    if not text:
        return ""
    if "[" in text:
        text = _INLINE_OVERRIDE_RE.sub(_spoken_override, text)
        text = _CONTROL_TAG_RE.sub(" ", text)
    text = _HSPACE_RE.sub(" ", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def take_reference_transcript(text: Optional[str]) -> str:
    """The transcript to pair with a saved take's audio, or ``""``.

    ``""`` means "transcribe the audio": it is returned for text that may be a
    pre-#3062 truncated history row, because a transcript that stops partway
    through the take is worse than none.
    """
    if not text or len(text) == LEGACY_HISTORY_TEXT_CAP:
        return ""
    return strip_script_markup(text)
