"""scripts/release.py: version suggestions, lockstep bump and changelog section."""
from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TODAY = datetime.date(2026, 10, 23)


@pytest.fixture(scope="module")
def release():
    spec = importlib.util.spec_from_file_location("release_script", ROOT / "scripts/release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("current", "channel", "expected"),
    [
        ("0.5.7", "stable", "0.5.8"),
        ("0.5.7", "beta", "0.5.8-beta.1"),
        ("0.5.8-beta.1", "beta", "0.5.8-beta.2"),
        ("0.5.8-beta.9", "beta", "0.5.8-beta.10"),
        ("0.5.8-beta.2", "stable", "0.5.8"),
    ],
)
def test_next_version(release, current, channel, expected):
    assert release.next_version(current, channel) == expected


def test_next_version_rejects_other_shapes(release):
    with pytest.raises(ValueError):
        release.next_version("0.5.8-rc.1", "beta")
    with pytest.raises(ValueError):
        release.next_version("0.5.8", "nightly")


def test_bump_files_moves_all_three_and_only_the_version(release, tmp_path):
    (tmp_path / "backend/core").mkdir(parents=True)
    (tmp_path / "package.json").write_text(
        '{\n  "name": "x",\n  "version": "0.5.7",\n  "dependencies": {"v": "1.0.0"}\n}\n'
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "x"\nversion = "0.5.7"\n[tool]\nversion = "9"\n'
    )
    (tmp_path / "backend/core/version.py").write_text('_FALLBACK_VERSION = "0.5.7"\n')
    release.bump_files(tmp_path, "0.5.8-beta.1")

    assert json.loads((tmp_path / "package.json").read_text())["version"] == "0.5.8-beta.1"
    assert 'version = "0.5.8-beta.1"' in (tmp_path / "pyproject.toml").read_text()
    assert 'version = "9"' in (tmp_path / "pyproject.toml").read_text()
    assert '_FALLBACK_VERSION = "0.5.8-beta.1"' in (tmp_path / "backend/core/version.py").read_text()


def test_bump_files_fails_loudly_when_a_mirror_is_missing(release, tmp_path):
    (tmp_path / "backend/core").mkdir(parents=True)
    (tmp_path / "package.json").write_text('{\n  "version": "0.5.7"\n}\n')
    (tmp_path / "pyproject.toml").write_text("[project]\n")
    (tmp_path / "backend/core/version.py").write_text("")
    with pytest.raises(ValueError, match="pyproject.toml"):
        release.bump_files(tmp_path, "0.5.8")


CHANGELOG = "# Changelog\n\n## [Unreleased]\n\n**Highlights**\n\n- A (#1)\n\n## [0.5.7] — 2026-10-01\n\n- Old (#2)\n"


def test_stable_renames_unreleased_and_starts_a_fresh_one(release):
    text = release.prepare_changelog(CHANGELOG, "0.5.8", TODAY)
    assert text.index("## [Unreleased]") < text.index("## [0.5.8] — 2026-10-23") < text.index("## [0.5.7]")
    unreleased, rest = text.split("## [0.5.8]")
    assert "- A (#1)" not in unreleased and "- A (#1)" in rest


def test_beta_copies_unreleased_so_it_stays_for_the_final_release(release):
    text = release.prepare_changelog(CHANGELOG, "0.5.8-beta.1", TODAY)
    assert text.count("- A (#1)") == 2
    assert text.index("## [Unreleased]") < text.index("## [0.5.8-beta.1] — 2026-10-23")


def test_existing_section_is_left_alone_and_empty_unreleased_is_refused(release):
    done = release.prepare_changelog(CHANGELOG, "0.5.7", TODAY)
    assert done == CHANGELOG
    with pytest.raises(ValueError, match="no \\[Unreleased\\] entries"):
        release.prepare_changelog("## [Unreleased]\n\n## [0.5.7] — x\n\n- a\n", "0.5.8", TODAY)


@pytest.mark.parametrize("version", ["0.5.8", "0.5.8-beta.3"])
def test_generated_changelog_passes_the_release_notes_extraction(release, version):
    """prepare_electron_release.py extracts `## [version]`; the section must be non-empty."""
    import re

    text = release.prepare_changelog(CHANGELOG, version, TODAY)
    section = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S
    )
    assert section and section[1].strip()


def _drive(release, monkeypatch, answers, *, dry_run, secrets_missing=()):
    """Run release() with scripted prompts and every side effect recorded, not run."""
    import argparse

    calls = []
    feed = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(feed))
    monkeypatch.setattr(release, "preflight", lambda tag=None: None)
    monkeypatch.setattr(release, "missing_signing_secrets", lambda: list(secrets_missing))
    monkeypatch.setattr(release, "sh", lambda *cmd, **kw: calls.append(cmd) or "")
    monkeypatch.setattr(release, "bump_files", lambda *a: calls.append(("bump", *a[1:])))
    monkeypatch.setattr(release, "dispatch_publish", lambda *a: calls.append(("dispatch", *a)))
    monkeypatch.setattr(
        release.Path, "write_text", lambda self, *a, **k: calls.append(("write", self.name))
    )
    monkeypatch.setattr(release, "prepare_changelog", lambda text, *a: text)
    release.release(argparse.Namespace(dry_run=dry_run))
    return calls


def _current(release):
    return json.loads((ROOT / "package.json").read_text())["version"]


def test_dry_run_shows_the_plan_and_changes_nothing(release, monkeypatch, capsys):
    calls = _drive(release, monkeypatch, ["beta", "", "draft"], dry_run=True)
    assert calls == []
    out = capsys.readouterr().out
    assert "prerelease, never latest" in out and "nothing changed" in out


def test_a_wrong_confirmation_cancels_before_any_change(release, monkeypatch):
    with pytest.raises(SystemExit, match="Cancelled"):
        _drive(release, monkeypatch, ["stable", "", "draft", "yes"], dry_run=False)


def test_a_version_of_the_other_channel_is_refused(release, monkeypatch):
    with pytest.raises(SystemExit, match="not a beta version"):
        _drive(release, monkeypatch, ["beta", "9.9.9"], dry_run=True)


def test_draft_pushes_the_tag_but_never_dispatches_a_publish(release, monkeypatch):
    tag = f"v{release.next_version(_current(release), 'beta')}"
    calls = _drive(release, monkeypatch, ["beta", "", "draft", tag], dry_run=False)
    assert ("git", "push", "origin", tag) in calls
    assert not any(c[0] == "dispatch" for c in calls)


def test_publish_without_signing_is_refused_unless_unsigned_is_accepted(release, monkeypatch):
    tag = f"v{release.next_version(_current(release), 'stable')}"
    with pytest.raises(SystemExit, match="configure signing"):
        _drive(release, monkeypatch, ["stable", "", "publish", "n"], dry_run=False,
               secrets_missing=["APPLE_ID"])
    calls = _drive(release, monkeypatch, ["stable", "", "publish", "y", tag], dry_run=False,
                   secrets_missing=["APPLE_ID"])
    assert ("dispatch", tag, True) in calls
