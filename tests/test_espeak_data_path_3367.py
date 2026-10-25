"""espeak-ng must never exit(1) the backend over its data path (#3367).

Field report: KittenTTS on Windows killed the whole backend with
``Error processing file 'D:/a/espeakng-loader/.../phontab'``. espeak-ng copies
the data path it is given into a fixed-size buffer and opens it with the
narrow C runtime; a path it cannot open makes it fall back to the wheel's
build-time path and ``espeak_Initialize`` calls ``exit(1)``.

The long-path cases below drive the real bundled library when
``espeakng_loader`` is installed: a data path longer than espeak's buffer is
rejected by espeak itself (fail-before), and ``ensure_espeak_data_path`` swaps
in a short copy espeak accepts (pass-after).
"""
from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from utils import espeak_data
from utils.espeak_data import EspeakDataError, ensure_espeak_data_path, espeak_resolves


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    monkeypatch.setattr(espeak_data, "_RESOLVED", None)
    for key in ("PHONEMIZER_ESPEAK_DATA_PATH", "ESPEAK_DATA_PATH", "OMNIVOICE_ESPEAK_DATA_CACHE"):
        monkeypatch.delenv(key, raising=False)


def _long_alias(tmp_path: Path, target: Path) -> Path:
    """A symlink to ``target`` whose own path is longer than N_PATH_HOME."""
    deep = tmp_path
    while len(str(deep)) < 260:
        deep = deep / ("d" * 40)
    deep.mkdir(parents=True)
    alias = deep / "espeak-ng-data"
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable on this host")
    return alias


@pytest.fixture
def real_loader():
    return pytest.importorskip("espeakng_loader")


def test_espeak_rejects_a_data_path_longer_than_its_buffer(real_loader, tmp_path):
    lib = real_loader.get_library_path()
    data = real_loader.get_data_path()
    assert espeak_resolves(lib, data) is True
    assert espeak_resolves(lib, str(tmp_path / "missing")) is False
    assert espeak_resolves(lib, str(_long_alias(tmp_path, Path(data)))) is False


def test_long_wheel_path_is_replaced_by_a_short_copy(real_loader, tmp_path, monkeypatch):
    alias = _long_alias(tmp_path, Path(real_loader.get_data_path()))
    cache = Path(os.path.realpath(tmp_path)) / "c"
    monkeypatch.setenv("OMNIVOICE_ESPEAK_DATA_CACHE", str(cache))
    loader = SimpleNamespace(
        get_library_path=real_loader.get_library_path,
        get_data_path=lambda: str(alias),
    )

    chosen = ensure_espeak_data_path(_loader=loader)

    assert chosen is not None and Path(chosen).is_relative_to(cache)
    assert (Path(chosen) / "phontab").is_file()
    assert espeak_resolves(real_loader.get_library_path(), chosen) is True
    assert os.environ["PHONEMIZER_ESPEAK_DATA_PATH"] == chosen
    wrapper = pytest.importorskip("phonemizer.backend.espeak.wrapper")
    assert wrapper.EspeakWrapper._ESPEAK_DATA_PATH == chosen


def _fake_loader(tmp_path: Path, *, phontab: bool = True):
    data = tmp_path / "espeak-ng-data"
    data.mkdir()
    if phontab:
        (data / "phontab").write_bytes(b"x")
    return SimpleNamespace(get_library_path=lambda: "libespeak", get_data_path=lambda: str(data))


def test_unopenable_data_raises_instead_of_exiting(tmp_path, monkeypatch):
    monkeypatch.setattr(espeak_data, "espeak_resolves", lambda lib, path: False)
    monkeypatch.setattr(espeak_data, "_cache_roots", lambda: [])
    with pytest.raises(EspeakDataError, match="cannot open its data directory"):
        ensure_espeak_data_path(_loader=_fake_loader(tmp_path))


def test_incomplete_wheel_data_raises(tmp_path):
    with pytest.raises(EspeakDataError, match="incomplete"):
        ensure_espeak_data_path(_loader=_fake_loader(tmp_path, phontab=False))


def test_kittentts_load_checks_espeak_before_constructing(monkeypatch):
    """The guard runs before KittenTTS() — whose phonemizer init is the exit(1)."""
    import sys

    from services import tts_backend

    constructed = []
    monkeypatch.setitem(sys.modules, "kittentts", SimpleNamespace(KittenTTS=lambda *a: constructed.append(a)))

    def refuse():
        raise EspeakDataError("no data")

    monkeypatch.setattr(espeak_data, "ensure_espeak_data_path", refuse)
    with pytest.raises(EspeakDataError):
        tts_backend.KittenTTSBackend()._ensure_loaded()
    assert constructed == []
