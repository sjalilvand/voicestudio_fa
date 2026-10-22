#!/usr/bin/env python3
"""Interactive release helper: Stable or Beta, draft or publish, then confirm.

    uv run python scripts/release.py                 # ask everything
    uv run python scripts/release.py --dry-run       # show the plan, change nothing
    uv run python scripts/release.py --publish TAG   # publish an existing draft

Runs from a clean, up-to-date `main`. Bumps the three version files in lockstep,
refreshes uv.lock, writes the CHANGELOG section, runs the version guards,
commits, pushes, tags, and either leaves the build as a draft (tag push) or
dispatches `electron-release.yml` with `publish`. Nothing leaves the machine
until you type the tag name to confirm. See docs/RELEASING.md.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_electron_release import channel_for  # noqa: E402

GUARD_TESTS = [
    "tests/test_app_version.py",
    "tests/test_voicestudio_branding.py",
    "tests/test_changelog_style.py",
]
SIGNING_SECRETS = ("ELECTRON_MACOS_CSC_LINK", "ELECTRON_WINDOWS_CSC_LINK", "APPLE_ID")
_VERSION = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?")


def next_version(current: str, channel: str) -> str:
    """Suggest the next version: beta -> beta.N+1 or next patch beta.1; stable -> final."""
    match = _VERSION.fullmatch(current)
    if not match:
        raise ValueError(f"Not a stable or beta version: {current}")
    major, minor, patch, beta = (int(g) if g else None for g in match.groups())
    base = f"{major}.{minor}.{patch}"
    if channel == "stable":
        return base if beta is not None else f"{major}.{minor}.{patch + 1}"
    if channel != "beta":
        raise ValueError(f"Unknown channel: {channel}")
    if beta is not None:
        return f"{base}-beta.{beta + 1}"
    return f"{major}.{minor}.{patch + 1}-beta.1"


def bump_files(root: Path, version: str) -> None:
    """Set the canonical version and its two toolchain mirrors."""
    targets = [
        ("package.json", r'(?m)^(\s*"version":\s*")[^"]+(")'),
        ("pyproject.toml", r'(?m)^(version\s*=\s*")[^"]+(")'),
        ("backend/core/version.py", r'(?m)^(_FALLBACK_VERSION\s*=\s*")[^"]+(")'),
    ]
    for name, pattern in targets:
        path = root / name
        text = path.read_text(encoding="utf-8")
        updated, count = re.subn(pattern, rf"\g<1>{version}\g<2>", text, count=1)
        if count != 1:
            raise ValueError(f"Could not find the version in {name}")
        path.write_text(updated, encoding="utf-8")


def prepare_changelog(text: str, version: str, today: datetime.date) -> str:
    """Return the changelog with a `## [version]` section; a no-op if one exists.

    Stable renames `[Unreleased]` and starts a fresh one. Beta copies it, so the
    next beta or the final stable release still carries the full list.
    """
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        return text
    match = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not match or not match.group(1).strip():
        raise ValueError("CHANGELOG.md has no [Unreleased] entries to release")
    body = match.group(1).strip("\n")
    heading = f"## [{version}] — {today.isoformat()}"
    if channel_for(version) == "stable":
        section = f"## [Unreleased]\n\n{heading}\n\n{body}\n\n"
    else:
        section = f"## [Unreleased]\n\n{body}\n\n{heading}\n\n{body}\n\n"
    return text[: match.start()] + section + text[match.end():]


def sh(*cmd: str, check: bool = True, capture: bool = False) -> str:
    result = subprocess.run(
        cmd, cwd=ROOT, check=check, text=True, capture_output=capture, encoding="utf-8"
    )
    return (result.stdout or "").strip() if capture else ""


def ask(question: str, choices: list[str], default: str | None = None) -> str:
    hint = "/".join(c.upper() if c == default else c for c in choices)
    while True:
        answer = input(f"{question} [{hint}] ").strip().lower() or (default or "")
        if answer in choices:
            return answer
        print(f"  Please answer one of: {', '.join(choices)}")


def preflight(tag: str | None = None) -> None:
    problems = []
    if sh("git", "branch", "--show-current", capture=True) != "main":
        problems.append("not on main (releases are always cut from main)")
    if sh("git", "status", "--porcelain", "--untracked-files=no", capture=True):
        problems.append("tracked files have uncommitted changes")
    sh("git", "fetch", "-q", "origin", "main")
    if sh("git", "rev-parse", "HEAD", capture=True) != sh("git", "rev-parse", "origin/main", capture=True):
        problems.append("main is not identical to origin/main (pull or push first)")
    if subprocess.run(["gh", "auth", "status"], cwd=ROOT, capture_output=True).returncode:
        problems.append("gh is not authenticated")
    if tag and sh("git", "ls-remote", "--tags", "origin", tag, capture=True):
        problems.append(f"tag {tag} already exists on origin")
    if problems:
        raise SystemExit("Cannot release:\n  - " + "\n  - ".join(problems))


def missing_signing_secrets() -> list[str]:
    result = subprocess.run(
        ["gh", "secret", "list", "--json", "name", "--jq", ".[].name"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if result.returncode:
        return list(SIGNING_SECRETS)  # cannot tell; ask rather than assume signed
    present = set(result.stdout.split())
    return [name for name in SIGNING_SECRETS if name not in present]


def dispatch_publish(tag: str, allow_unsigned: bool) -> None:
    sh(
        "gh", "workflow", "run", "electron-release.yml", "--ref", "main",
        "-f", f"release_tag={tag}", "-f", "publish=true",
        "-f", f"allow_unsigned={str(allow_unsigned).lower()}",
    )


def publish_existing(tag: str) -> None:
    channel = channel_for(tag.removeprefix("v"))
    preflight()
    unsigned = False
    if missing_signing_secrets():
        unsigned = ask("Signing secrets missing or unreadable. Ship UNSIGNED installers?", ["y", "n"], "n") == "y"
    print(f"\nPublish {tag} ({channel}) from its existing build{' (unsigned)' if unsigned else ''}.")
    if input(f"Type {tag} to confirm: ").strip() != tag:
        raise SystemExit("Cancelled.")
    dispatch_publish(tag, unsigned)
    print("Dispatched electron-release.yml with publish=true. Watch: gh run list --workflow electron-release.yml")


def release(args: argparse.Namespace) -> None:
    current = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    preflight()
    channel = ask("Release channel?", ["stable", "beta"])
    suggestion = next_version(current, channel)
    version = input(f"Version [{suggestion}]: ").strip() or suggestion
    if channel_for(version) != channel:
        raise SystemExit(f"{version} is not a {channel} version")
    tag = f"v{version}"
    preflight(tag)
    mode = ask("Draft (build only, publish later) or publish now?", ["draft", "publish"], "draft")
    unsigned = False
    if mode == "publish" and missing_signing_secrets():
        print("Signing secrets are missing or unreadable (Mac/Windows signing).")
        unsigned = ask("Ship UNSIGNED installers?", ["y", "n"], "n") == "y"
        if not unsigned:
            raise SystemExit("Cancelled: configure signing, or choose draft.")

    print(f"""
Release plan
  channel   {channel}  ({'GitHub prerelease, never latest; :beta Docker' if channel == 'beta' else 'GitHub latest; :stable Docker'})
  version   {current} -> {version}   tag {tag}
  mode      {mode}{'  (UNSIGNED installers)' if unsigned else ''}
  steps     bump 3 version files + uv lock + CHANGELOG, run guards,
            commit + push main, push tag{', then publish' if mode == 'publish' else ' (draft release; publish later with --publish)'}""")
    if args.dry_run:
        print("\n--dry-run: nothing changed.")
        return
    if input(f"\nThis pushes to main and tags. Type {tag} to confirm: ").strip() != tag:
        raise SystemExit("Cancelled.")

    bump_files(ROOT, version)
    changelog = ROOT / "CHANGELOG.md"
    changelog.write_text(
        prepare_changelog(changelog.read_text(encoding="utf-8"), version, datetime.date.today()),
        encoding="utf-8",
    )
    sh("uv", "lock")
    sh("uv", "run", "pytest", *GUARD_TESTS, "-q")
    sh("git", "add", "package.json", "pyproject.toml", "backend/core/version.py", "uv.lock", "CHANGELOG.md")
    sh("git", "commit", "-m", f"chore(release): {tag}")
    sh("git", "push", "origin", "main")
    sh("git", "tag", tag)
    sh("git", "push", "origin", tag)
    if mode == "publish":
        # The tag push starts a build-only run; the dispatch builds and publishes.
        runs = sh("gh", "run", "list", "--workflow", "electron-release.yml", "--branch", tag,
                  "--event", "push", "--json", "databaseId", "--jq", ".[].databaseId", capture=True)
        for run_id in runs.split():
            sh("gh", "run", "cancel", run_id, check=False)
        dispatch_publish(tag, unsigned)
        print(f"\nPublishing {tag}. Then verify: docs/RELEASING.md → Beta channel / verification table.")
    else:
        print(f"\nDraft build started for {tag}. Publish later: uv run python scripts/release.py --publish {tag}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="show the plan and change nothing")
    parser.add_argument("--publish", metavar="TAG", help="publish an existing draft build of TAG")
    args = parser.parse_args()
    if args.publish:
        publish_existing(args.publish)
    else:
        release(args)


if __name__ == "__main__":
    main()
