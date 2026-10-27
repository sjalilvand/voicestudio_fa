"""Every text-mode subprocess call in the backend must say how to handle bad bytes (#3612).

On Windows, ``subprocess.run(..., capture_output=True, text=True)`` decodes the
child's output in a reader thread. When the output is not valid in the locale
encoding (PowerShell's OEM code page, a localized tool, a GPU name with a
trademark sign), that thread dies and ``result.stdout`` is silently ``None``.
The caller's ``result.stdout.splitlines()`` then raised, and because the GPU
probe runs at import time the whole backend failed to start. ``errors=...``
(normally ``"replace"``) makes the decode total, so stdout is always a str.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CALLS = {"run", "check_output", "Popen", "call", "check_call"}


def _text_mode_calls_without_errors(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if name not in _CALLS:
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        text_mode = any(
            isinstance(kw.get(arg), ast.Constant) and kw[arg].value is True
            for arg in ("text", "universal_newlines")
        )
        if text_mode and "errors" not in kw:
            yield node.lineno


def test_text_mode_subprocess_calls_never_drop_their_output():
    offenders = []
    for path in sorted((ROOT / "backend").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if "/tests/" in rel or rel.startswith("backend/tests"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        offenders += [f"{rel}:{line}" for line in _text_mode_calls_without_errors(tree)]
    assert not offenders, (
        "text-mode subprocess calls need errors='replace' (or another handler), "
        "or a bad byte leaves stdout None on Windows: " + ", ".join(offenders)
    )


def test_the_checker_sees_a_bare_text_call():
    tree = ast.parse("subprocess.run(['x'], capture_output=True, text=True)")
    assert list(_text_mode_calls_without_errors(tree)) == [1]
    tree = ast.parse("subprocess.run(['x'], text=True, errors='replace')")
    assert list(_text_mode_calls_without_errors(tree)) == []
