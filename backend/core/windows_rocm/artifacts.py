"""Download into temporary storage; extract only a verified named wheel."""
import hashlib
import time
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_archive(url, destination, size):
    deadline = time.monotonic() + 1800
    written = 0
    with urllib.request.urlopen(url, timeout=60) as source, Path(destination).open("wb") as target:
        while chunk := source.read(1024 * 1024):
            written += len(chunk)
            if written > size or time.monotonic() > deadline:
                raise RuntimeError("Windows ROCm archive download exceeded size/time bound")
            target.write(chunk)
    if written != size:
        raise RuntimeError("Windows ROCm archive download was truncated")


def checked_wheel(archive_path, destination, config):
    # CLEAN-ROOM (spec W5-pyannote §6): verify the archive hash, extract exactly
    # the one named wheel member with bounds, verify its hash, return its path.
    raise NotImplementedError("pending clean-room reimplementation (spec W5-pyannote)")
