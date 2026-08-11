"""`desktop-prod:run` must not destroy the developer's data (#1333).

`scripts/desktop-prod.sh` exists to emulate a first install, so wiping is its
default: it removes the app data dir, the backend data dir (``~/.omnivoice`` —
the SQLite database, every voice profile, and all outputs), the Tauri logs and
the WebKit profile. `--keep-data` is the only thing that suppresses that.

`--skip-build` is an INDEPENDENT flag that only skips the cargo compile. The
package script advertised as a re-launch — its own header calls it "re-launch
last build (skip compile)" — passed `--skip-build` alone, so every "just run it
again" silently deleted the user's voice profiles and project database. That is
the gap this test closes: the wipe stays opt-out, but the *re-launch* aliases
have to opt out of it.

Mechanical on purpose (token-economy convention): a rule a reviewer would have
to remember belongs in a test, not in anyone's head.
"""
import importlib.util
import json
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PKG = os.path.join(_ROOT, "package.json")
_SH = os.path.join(_ROOT, "scripts", "desktop-prod.sh")
_APPIMAGE_PROCESSES = os.path.join(_ROOT, "scripts", "desktop_prod_processes.py")

# Scripts whose NAME promises a re-launch of an existing build rather than a
# fresh-install emulation. Add new aliases here when they appear.
_RELAUNCH_SCRIPTS = ("desktop-prod:run", "desktop-prod:run:pill")


def _scripts() -> dict:
    with open(_PKG, encoding="utf-8") as fh:
        return json.load(fh)["scripts"]


def test_relaunch_scripts_keep_data():
    """A re-launch must not wipe ~/.omnivoice."""
    scripts = _scripts()
    for name in _RELAUNCH_SCRIPTS:
        assert name in scripts, f"{name} disappeared from package.json"
        cmd = scripts[name]
        assert "--skip-build" in cmd, f"{name} is meant to skip the build: {cmd}"
        assert "--keep-data" in cmd, (
            f"{name} passes --skip-build without --keep-data, so it still runs the "
            f"wipe block in desktop-prod.sh and deletes the user's voice profiles, "
            f"SQLite db and outputs on every re-launch (#1333). Command: {cmd}"
        )


def test_fresh_install_emulation_still_wipes():
    """The other side of the branch: the default must stay a real fresh run,
    otherwise this test would 'pass' by making every script harmless."""
    scripts = _scripts()
    assert "--keep-data" not in scripts["desktop-prod"], (
        "desktop-prod is the fresh-install emulation — it must still wipe"
    )
    # `desktop-fresh:run` is deliberately NOT in _RELAUNCH_SCRIPTS: that script
    # is a stricter new-user emulation, so wiping is the point of its name.
    assert "--keep-data" not in scripts["desktop-fresh:run"]


def test_skip_build_does_not_imply_keep_data_in_the_script():
    """The fix belongs in the package scripts, not in the flag parsing.

    Making `--skip-build` imply `--keep-data` inside desktop-prod.sh would take
    away a legitimate combination — a fresh-data run that skips the 1-3 min
    compile. Pin that the two stay independent so a later 'simplification'
    doesn't quietly remove it.
    """
    with open(_SH, encoding="utf-8") as fh:
        src = fh.read()
    assert "--skip-build)  SKIP_BUILD=true ;;" in src, (
        "desktop-prod.sh's --skip-build no longer sets only SKIP_BUILD; if it now "
        "also sets KEEP_DATA, the fresh-data-without-recompile combination is gone"
    )
    # And the wipe stays gated on KEEP_DATA alone.
    assert 'if [ "$KEEP_DATA" = false ]; then' in src


def test_running_instances_are_killed_regardless_of_data_policy():
    """Killing the live app must not be gated on the wipe (#1333 review).

    The app registers ``tauri_plugin_single_instance``, and its callback ignores
    the incoming argv — it just refocuses the window the RUNNING process already
    owns. Starting a second copy over a live one therefore does nothing visible:
    ``desktop-prod:run`` would refocus the OLD build instead of the one just
    compiled, and ``desktop-prod:run:pill`` would leave the user in studio mode
    with ``--pill`` silently discarded.

    That was previously masked: the kill lived inside the ``KEEP_DATA = false``
    branch, so every run happened to kill first *because* every run wiped.
    Adding ``--keep-data`` to the re-launch aliases removed the wipe and would
    have taken the kill with it.
    """
    with open(_SH, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    call_lines = [
        i for i, ln in enumerate(lines)
        if ln.strip() == "kill_running_instances"
    ]
    assert call_lines, "kill_running_instances is never called"

    guard = next(
        i for i, ln in enumerate(lines)
        if ln.strip() == 'if [ "$KEEP_DATA" = false ]; then'
    )
    assert any(i < guard for i in call_lines), (
        "kill_running_instances is only called inside the KEEP_DATA=false wipe "
        "branch, so a --keep-data run launches on top of the live app and "
        "single-instance just refocuses the old window (#1333)"
    )

def test_kill_is_scoped_to_this_checkouts_build():
    """The kill may not reach an installed /Applications copy (#1333 review).

    Now that ``kill_running_instances`` runs on EVERY invocation rather than
    only on wipe runs, its pattern matters in a way it did not before. A bare
    ``"VoiceStudio.app"`` matches the installed release app too, so a
    developer running ``desktop-prod:run`` while using the shipped app would
    have it killed underneath them — losing unsaved work in a session this
    script never started. Previously that was masked: the kill only ran when
    the developer had explicitly asked for a wipe.

    Scoping the pattern to ``${TAURI_DIR}/target/debug/`` keeps it to what this
    checkout built. ``pgrep -f`` sees the absolute path, of which the
    repo-relative prefix is a substring, and both launch shapes (raw binary and
    ``.app`` bundle) live under it.
    """
    with open(_SH, encoding="utf-8") as fh:
        src = fh.read()

    body = src.split("kill_running_instances() {", 1)[1].split("\n}", 1)[0]
    pgrep = next(
        ln.strip() for ln in body.splitlines()
        if "pgrep -f" in ln and not ln.strip().startswith("#")
    )
    assert "target/debug/" in pgrep, (
        "kill_running_instances' pgrep pattern is not scoped to this checkout's "
        f"build output, so it can match an installed app: {pgrep}"
    )
    assert "${APP_NAME}.app" not in pgrep, (
        "kill_running_instances matches any 'VoiceStudio.app', including "
        f"the installed one in /Applications: {pgrep}"
    )
    # The installed copy still has to be surfaced — single-instance keys on the
    # bundle id, so ignoring it silently swaps one confusing failure for another.
    assert "warn_installed_instance" in body, (
        "an installed instance is neither killed nor mentioned; single-instance "
        "will swallow the launch and the developer gets no explanation"
    )


def test_linux_extracted_appimage_and_backend_are_stopped_before_wipe(tmp_path):
    """Extraction hides the checkout path from argv, but APPIMAGE survives.

    Reproduce the production failure with a fake procfs: the Tauri process and
    backend inherit the same owned APPIMAGE, while a similarly named build from
    another checkout and an unrelated process must remain untouched.
    """
    build_root = tmp_path / "repo" / "frontend" / "src-tauri" / "target" / "debug"
    proc_root = tmp_path / "proc"

    def process(pid: int, *environment: str) -> None:
        process_dir = proc_root / str(pid)
        process_dir.mkdir(parents=True)
        (process_dir / "environ").write_bytes(
            ("\0".join(environment) + "\0").encode()
        )

    owned = build_root / "bundle" / "appimage" / "VoiceStudio_0.4.2_amd64.AppImage"
    process(101, f"APPIMAGE={owned}", "HOME=/home/test")
    process(102, f"APPIMAGE={owned}", "ROLE=backend")
    process(
        201,
        f"APPIMAGE={build_root}-other/bundle/appimage/VoiceStudio_0.4.2_amd64.AppImage",
    )
    process(202, f"APPIMAGE={owned}.untrusted")
    process(203, "HOME=/home/test")

    spec = importlib.util.spec_from_file_location(
        "desktop_prod_processes", _APPIMAGE_PROCESSES
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    opened = []

    def fake_pidfd_open(pid: int, flags: int) -> int:
        opened.append((pid, flags))
        return os.open(os.devnull, os.O_RDONLY)

    owned = module.open_owned_processes(
        build_root, proc_root, pidfd_open=fake_pidfd_open
    )
    found = [str(pid) for pid, _ in owned]
    for _, pidfd in owned:
        os.close(pidfd)

    assert found == ["101", "102"]
    assert [pid for pid, _ in opened] == [101, 102, 201, 202, 203]

    src = open(_SH, encoding="utf-8").read()
    call = 'python3 scripts/desktop_prod_processes.py "$TAURI_BUILD_ROOT"'
    assert call in src
    assert src.index(call) < src.index('if [ "$KEEP_DATA" = false ]; then')
