"""Shared setup for backend/tests — import path + hermetic data dir.

Historically every module in this directory stubbed
``sys.modules["core.config"]`` with a bare 3-4 attribute ``ModuleType``
pointing at its own ``mkdtemp``. That stub leaked **process-wide at
collection time**: pytest imports test modules while collecting, so in any
mixed invocation (``pytest tests/... backend/tests/...``) every *later* lazy
import of ``core.config`` resolved the stub instead of the real module —
``tests/test_router_smoke.py``'s ``from main import app`` died with
ImportError (missing config attrs), and
``monkeypatch.setattr("core.config.X", ...)`` died with AttributeError
(``core`` never gets a ``config`` attribute when the name is satisfied
straight from ``sys.modules``). That was the root cause of the
order-pollution combos around test_longform_e2e (8 AttributeErrors) and
test_router_smoke (24 fixture ImportErrors).

The real ``core.config`` derives every path from ``OMNIVOICE_DATA_DIR`` at
import time, so pointing that env var at a throwaway dir *before* any test
module imports it gives the same hermeticity (issue #878: never touch the
developer's real app state) with zero ``sys.modules`` surgery. This mirrors
``tests/conftest.py``; in a mixed run whichever conftest loads first wins
(``setdefault`` semantics) and both point at a throwaway tmpdir.

Do NOT reintroduce module-level ``sys.modules`` stubs in this directory —
import the real module and rely on this conftest instead.
"""
import os
import sys
import tempfile

# Backend runs with `--app-dir backend`, so tests must do the same.
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

if not os.environ.get("OMNIVOICE_DATA_DIR"):
    os.environ["OMNIVOICE_DATA_DIR"] = tempfile.mkdtemp(prefix="omnivoice-test-data-")
if not os.environ.get("OMNIVOICE_ENV_FILE"):
    os.environ["OMNIVOICE_ENV_FILE"] = os.path.join(
        os.environ["OMNIVOICE_DATA_DIR"], "user-env"
    )
# TTS checkpoint sentinel — mirrors tests/conftest.py (whichever loads first
# wins via setdefault). Without it, any test booting the real app lifespan
# resolves the real k2-fsa/OmniVoice checkpoint and `preload_model()` could
# kick off a multi-GB background download on a networked machine.
os.environ.setdefault("OMNIVOICE_MODEL", "test")


import pytest


@pytest.fixture
def asr_model_installed(monkeypatch, request):
    """Neutralize the no-ASR-installed preflight (asr_model_missing_error →
    None) for tests that exercise ASR-consumer *mechanics* (batch/dub/
    dictation) and assume ASR weights are present — the hermetic test env has
    no HF model cache, so the consumers would otherwise answer the typed
    ``asr_model_missing`` 409 before the code under test even runs. The
    preflight has its own suite (tests/test_asr_model_missing.py). Opt in per
    module with ``pytestmark = pytest.mark.usefixtures("asr_model_installed")``.

    Patches BOTH the freshly imported module and any module-typed alias the
    test module itself holds (``import services.asr_backend as ab``): in a
    full-suite run an earlier test can purge ``services.*`` from sys.modules,
    leaving the alias pointing at a STALE pre-purge module object whose
    globals a single sys.modules-based setattr would miss.
    (Mirror of the fixture in tests/conftest.py — conftests don't cross the
    tests/ ↔ backend/tests/ directory boundary.)"""
    import types

    from services import asr_backend

    targets = {id(asr_backend): asr_backend}
    test_module = getattr(request, "module", None)
    if test_module is not None:
        for val in vars(test_module).values():
            if (isinstance(val, types.ModuleType)
                    and getattr(val, "__name__", "") == "services.asr_backend"):
                targets[id(val)] = val
    for mod in targets.values():
        monkeypatch.setattr(mod, "asr_model_missing_error", lambda **_kw: None)


@pytest.fixture(autouse=True)
def _clear_asr_installed_memo():
    """The ASR preflight memoizes installed-POSITIVE repos process-wide
    (services.asr_backend._INSTALLED_REPO_MEMO). Tests stub ``is_cached`` both
    ways, so a memoized positive must never leak between tests. Touches the
    memo only when the module is already imported. (Mirror of the guard in
    tests/conftest.py.)"""
    mod = sys.modules.get("services.asr_backend")
    if mod is not None:
        getattr(mod, "_INSTALLED_REPO_MEMO", set()).clear()
    yield
    mod = sys.modules.get("services.asr_backend")
    if mod is not None:
        getattr(mod, "_INSTALLED_REPO_MEMO", set()).clear()
