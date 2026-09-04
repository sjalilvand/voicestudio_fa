"""No tracked path that Windows cannot check out.

Windows rejects `< > : " | ? *` and control characters in filenames, treats a
trailing space or dot on a path component as invalid, and reserves the device
names CON/PRN/AUX/NUL/COM1-9/LPT1-9. Git on Windows refuses such a path with
`error: invalid path ...` and exits 128 — during **checkout**, before any
build or test step runs. So a single stray file like `:memory:.ses` (a sqlite
session artifact named after the `:memory:` DSN, committed by accident on the
#1798 branch) turns every Windows job red with an error that names a file
nobody edited, while Linux and macOS stay green.

Nothing else catches this: the file need not be referenced by any code, and
the platforms that can check it out do not care. This scans the index on every
platform so the failure surfaces as a named test rather than as a checkout
crash on one leg of the matrix.
"""
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

# Characters git-for-Windows rejects outright, plus C0 controls.
_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')
# Reserved DOS device names, with or without an extension (`NUL`, `nul.txt`).
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\.|$)", re.IGNORECASE)


def _tracked_paths():
    out = subprocess.run(
        ["git", "-C", str(_ROOT), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def test_no_windows_hostile_tracked_paths():
    offenders = []
    for rel in _tracked_paths():
        # This test file names the offending characters in its own source, but
        # its *path* is what is checked — every path is scanned, none skipped.
        for part in rel.split("/"):
            if _BAD_CHARS.search(part):
                offenders.append(f"{rel} (illegal character in {part!r})")
            elif part != part.rstrip(" ."):
                offenders.append(f"{rel} (component {part!r} ends in space/dot)")
            elif _RESERVED.match(part):
                offenders.append(f"{rel} (reserved device name {part!r})")
    assert not offenders, (
        "Tracked paths Windows cannot check out — git exits 128 during checkout "
        "and every Windows CI job fails before it starts:\n  "
        + "\n  ".join(offenders)
    )
