---
phase: 260518-lp7
plan: 01
subsystem: desktop-shell/tauri
tags: [ux, tauri, dictation, pill-mode, tray]
requires:
  - branch: worktree-agent-aa531fed864ec700a (forked off fix/widget-hide-when-idle at ac3fb93)
provides:
  - "Pill-mode launch leaves widget hidden (pre-positioned)"
  - "Tray 'Start Dictation' shows + positions + focuses widget before emitting tray-dictate"
affects:
  - frontend/src-tauri/src/lib.rs
tech-stack:
  added: []  # no new deps
  patterns:
    - "Inline duplication of the global-shortcut show-block (lines 184-199 pattern) in the tray dictate handler — helper extraction rejected to keep the diff minimal per plan risks"
key-files:
  created: []
  modified:
    - frontend/src-tauri/src/lib.rs
decisions:
  - "Inline the position+show+focus block in tray dictate handler instead of extracting a show_widget_for_dictation helper. Rationale: avoids new use statements, keeps the diff to a single function body, matches the plan's 'Keep the diff minimal' risk note. A future refactor PR can DRY both call sites against the global shortcut handler."
  - "When the widget window cannot be resolved in the tray dictate handler (the outer `else`), log a warning and still emit tray-dictate. Mirrors the global shortcut handler's silent behavior on None (line 199) but adds a log breadcrumb since the tray path is more user-visible."
metrics:
  completed: 2026-05-18
  duration_seconds: ~360
  files_changed: 1
  lines_added: 27
  lines_removed: 11
---

# Phase 260518-lp7 Plan 01: Hide Dictation Pill Widget When Idle Summary

Pill widget no longer appears on pill-mode launch — it stays hidden (pre-positioned) until the user activates it via global shortcut (Cmd+Shift+Space) or tray "Start Dictation". The tray dictate handler now shows + positions + focuses the widget before emitting `tray-dictate`, closing a pre-existing silent-recording bug.

## What Changed

Two surgical edits to `frontend/src-tauri/src/lib.rs`:

### Edit 1 — pill_mode_setup branch (~lines 379-406 → 397-423 post-edit)

**Before:** Widget window was positioned at top-center, then `win.show()` + `win.set_focus()` was called, making the idle "Ready" pill visible on every pill-mode launch.

**After:** Position block retained (so the eventual first show appears at top-center without a frame-jump), but `win.show()` and `win.set_focus()` removed. A single `log::info!("Pill mode: widget window pre-positioned (hidden until activated)")` replaces the old success/failure match arm. The `None =>` arm for "widget window not found" is unchanged.

Comment above the block rewritten from "PILL MODE = the widget IS the app. Show it immediately ..." to: "Pill mode: widget stays HIDDEN until activated by global shortcut or tray 'Start Dictation'. Pre-position it now so the first show appears at top-center without an animation/frame flicker. Trade-off accepted vs the original 'looks-launch-failed' concern: the tray icon + 'OmniVoice Dictation' tooltip provide the app-running signal."

### Edit 2 — Tray "dictate" handler (~lines 331-343 → 343-372 post-edit)

**Before:** Start branch emitted `tray-dictate` with no UI change — recording would begin silently behind the hidden widget. Outer `else` (widget window None) did the same.

**After:** Inner `else` (widget hidden, start path) now mirrors the global-shortcut handler at lines 184-199:
- `win.primary_monitor()` probe → `set_position(LogicalPosition::new(x, 60.0))` with x computed from monitor width/scale, fallback to `win.center()` on probe failure.
- `win.show()` → `win.set_focus()` → `app.emit("tray-dictate", ())`.

Outer `else` (widget window not found) now logs a warning before emitting (helps debugging vs the prior silent emit). The visible-toggle path (`if win.is_visible() { emit tray-dictate-stop }`) is unchanged.

## Helper-vs-Inline Decision

**Chose inline.** Rationale documented in commit message and decisions frontmatter:

- The plan permitted either approach: "If extracting the helper feels like scope creep (e.g., lifetimes get awkward or it adds more lines than it saves), instead inline the position+show+focus block directly".
- Extracting `fn show_widget_for_dictation(app: &tauri::AppHandle)` would have required either adding a free function near the top of `lib.rs` (touching unrelated namespace) or threading the call signature through. Either path adds more lines than it saves for a single new call site.
- The risks section explicitly warned: "If the executor extracts show_widget_for_dictation, they should NOT also retrofit the global shortcut handler in this commit. Keep the diff minimal." Inlining avoids any temptation to retrofit.
- A future refactor PR can DRY all three call sites (single-instance handler, global shortcut handler, tray dictate handler) against one helper.

## Verification

### Automated

```
$ cargo check --manifest-path frontend/src-tauri/Cargo.toml 2>&1 | tail -3
   Checking sysinfo v0.33.1
   Checking tauri-plugin-single-instance v2.4.2
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 49.42s
```

No errors, no warnings on `omnivoice-studio` crate.

```
$ grep -n "win\.show()" frontend/src-tauri/src/lib.rs
87:                let _ = win.show();      # single_instance handler (untouched)
197:                let _ = win.show();     # global shortcut handler (untouched)
294:                let _ = win.show();     # tray "show" handler (untouched)
351:                let _ = win.show();     # tray "dictate" start branch (NEW — Edit 2)
365:                let _ = win.show();     # tray "settings" handler (untouched)
```

Five `win.show()` call sites total. **Zero** in the `pill_mode_setup` branch (confirms Edit 1). One new at line 351 in the tray dictate start branch (confirms Edit 2). The other four are pre-existing and unchanged.

```
$ grep -n "Widget stays HIDDEN\|widget window pre-positioned" frontend/src-tauri/src/lib.rs
398:   // Pill mode: widget stays HIDDEN until activated by global
416:   log::info!("Pill mode: widget window pre-positioned (hidden until activated)");
```

New comment + new log line both present.

### Git

```
$ git log -1 --oneline
001d975 fix(widget): hide dictation pill when idle, show only when activated

$ git show --stat HEAD
 frontend/src-tauri/src/lib.rs | 38 +++++++++++++++++++++++++++-----------
 1 file changed, 27 insertions(+), 11 deletions(-)

$ git status --short
(clean)

$ git diff --diff-filter=D --name-only HEAD~1 HEAD
(no deletions)
```

Commit touches only `lib.rs`. Working tree clean. No accidental file deletions.

## Manual Test Plan (for user after merge)

The user will validate the GUI behavior after the orchestrator merges to `fix/widget-hide-when-idle` and the PR lands. Suggested checks:

1. **Pill-mode launch:** `bun desktop -- --pill` (or set `launch_as_widget=true` in config and relaunch). Expected: tray icon appears with "OmniVoice Dictation" tooltip; NO pill visible on screen.
2. **Global shortcut activation:** Press Cmd+Shift+Space. Expected: pill appears at top-center of primary monitor; recording starts; releasing the shortcut hides it after the existing ~1.5s grace.
3. **Tray "Start Dictation" activation:** Click tray icon → "Start Dictation". Expected: pill appears at top-center; recording starts. Clicking "Start Dictation" again while the pill is visible should emit `tray-dictate-stop` (toggle behavior preserved).
4. **Multi-monitor:** Verify the pill positions at top-center of the *primary* monitor (existing behavior — unchanged).
5. **Studio mode regression check:** `bun desktop` without `--pill`. Expected: studio window opens normally; widget stays hidden; Cmd+Shift+Space still works.

## Deviations from Plan

None — plan executed exactly as written. Both surgical edits applied; cargo check passed; single atomic commit on the per-agent worktree branch (orchestrator will merge to `fix/widget-hide-when-idle`); no SUMMARY/STATE commit (orchestrator owns those).

## Known Stubs

None.

## Self-Check: PASSED

- `frontend/src-tauri/src/lib.rs` — FOUND (modified, 587 lines post-edit)
- Commit `001d975` — FOUND on branch `worktree-agent-aa531fed864ec700a`
- `cargo check` — exit code 0, no warnings on our crate
- No files outside `lib.rs` touched in the commit (verified via `git show --stat HEAD`)
- No accidental deletions (verified via `git diff --diff-filter=D HEAD~1 HEAD`)
