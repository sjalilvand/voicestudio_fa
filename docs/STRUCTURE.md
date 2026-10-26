# Project Structure

Every folder has a single job. Every file at the root earns its place.

## Layout

```
VoiceStudio/
│
├── README.md ⟵ user-facing overview (translations: docs/readme/README_CN.md, README_JA.md)
├── CHANGELOG.md                 ⟵ release history; Electron releases use the tagged section
├── CLEAN-ROOM (spec R1-medium §33a): root files entries (agent contract, license files, python manifest)
├── uv.lock                      ⟵ Python lockfile
├── package.json                 ⟵ monorepo manifest (Bun workspaces + Turborepo) and THE app
│                                   version (pyproject.toml + backend/core/version.py mirror it)
├── bun.lock                     ⟵ JS lockfile — repo-root, covers the electron/ workspace
├── turbo.json                   ⟵ turborepo pipeline
│
├── CLEAN-ROOM (spec R1-medium §33b): root config entries (review bots, skills lock, secret scan, submodules, python version)
├── .dockerignore                ⟵ Docker build context filter
├── alembic.ini                  ⟵ DB migration config (stays at root by alembic convention)
│
├── CLEAN-ROOM (spec R1-medium §33c): .gitignore entry
│
├── backend/                     ⟵ FastAPI server
│   CLEAN-ROOM (spec R1-medium §33d): backend/ subtree entries
│
├── electron/                    ⟵ the only desktop app and web UI (Electron + React 19)
│   ├── src/main/                lifecycle, backend supervisor, runtime setup, updater, native IPC
│   ├── src/preload/             typed contextBridge → window.voicestudio
│   ├── src/renderer/            desktop React app: routes/, features/, components/, i18n/locales/
│   ├── src/shared/              modules shared by the desktop and browser builds (api/, i18n/,
│   │                            store/, ui/, utils/) — not a runnable app
│   ├── tests/                   packaged-app, installer and workflow smoke tests
│   ├── build/                   packaging inputs: icons, entitlements, Info.plist
│   ├── scripts/                 dev launcher, AppImage update-info embedding
│   ├── vite.web.config.ts       browser build (`bun run build:web`) → frontend/dist/
│   └── electron-builder.config.mjs   installers: DMG/zip, NSIS, AppImage + deb
│
├── native/desktop-bridge/       ⟵ Rust helper used by Electron
│
├── frontend/dist/               ⟵ build output of `bun run build:web` (gitignored): the web UI
│                                   the backend serves in Docker and, from Electron packages, to LAN devices
│
├── omnivoice/                   ⟵ the underlying TTS model package
│   ├── models/
│   ├── cli/                     CLI entry points (omnivoice-infer, etc.)
│   ├── data/                    data utilities used by the model
│   ├── eval/                    evaluation scripts
│   ├── scripts/                 one-off utilities that ship with the package
│   ├── training/
│   └── utils/
│
├── CLEAN-ROOM (spec R1-medium §33e): tests/ subtree entries and scripts/ header + installer entry
│   ├── install.sh / install.ps1 shell + PowerShell installers served at voicestudio.sh/install
│   ├── dev-backend.mjs          `bun run dev:api` backend supervisor
│   ├── setup.py                 `bun run setup:api` post-sync platform setup (incl. ROCm opt-in)
│   ├── electron-smoke-test.mjs  `bun run smoke-test` packaged-app launch check
│   ├── prepare_electron_release.py, check_electron_release_assets.py   release asset gates
│   CLEAN-ROOM (spec R1-medium §33f): scripts/ tail, bin/, skills dirs, deploy/ subtree entries
│   ├── dockerhub-overview.md    synced to the Docker Hub overview page at release
│   └── install-worker/          live voicestudio.sh/install Cloudflare worker; bundles
│                                scripts/install.sh + install.ps1 (docs/install/script.md)
│
├── docs/                        ⟵ developer docs, screenshots, branding
│   ├── ROADMAP.md               where this project is going
│   ├── STRUCTURE.md             you are here
│   CLEAN-ROOM (spec R1-medium §33g): docs/ subtree, examples/, notebooks/, omnivoice-gallery/ entries
│
├── omnivoice_data/              ⟵ Docker bind-mount target (gitignored)
│                                   DB + HF cache live here when running via compose
│
├── .github/workflows/           ⟵ ci, electron-build, electron-release, docker, security,
│                                   docs-drift, evals, install-smoke, build-omnivoice-tts,
│                                   cla, commit-identity, cosyvoice-dependencies
└── .git/
```

## Rules of the root

1. **Nothing at the root is a runtime artifact.** Outputs, temp files, local DBs, crash logs — all go to `~/Library/Application Support/OmniVoice/` (or the OS equivalent), *never* into the repo. The one exception is `omnivoice_data/`, which exists as a bind-mount anchor for Docker.

<!-- CLEAN-ROOM (spec R1-medium §33h): rule 2 of the root rules -->

3. **Each subdirectory owns one concern.** If you can't describe what goes in a directory in one sentence, it's wrong.

4. **Every package has a manifest.** `backend/`, `electron/`, `omnivoice/` each have their own deps declared via `pyproject.toml` / `package.json` — they are independently testable. The JS lockfile is the **repo-root** `bun.lock` (Bun workspace), and `deploy/Dockerfile` installs from it with `--frozen-lockfile`.

<!-- CLEAN-ROOM (spec R1-medium §33i): the 'Where tests live' section -->

## What lives where

| Kind of thing | Goes in |
|---|---|
| User-facing product code | `backend/`, `electron/` |
| The TTS model (independent of the studio) | `omnivoice/` |
| CLEAN-ROOM (spec R1-medium §33j): row | engine adapter location |
| Everything executable but not user-facing | `scripts/` |
| CLEAN-ROOM (spec R1-medium §33k): rows | prebuilt sidecars; python tests |
| Electron / UI unit tests | next to the module, as `*.test.ts(x)` |
| Developer + user docs (Markdown) | `docs/` |
| Architecture decision records (ADRs) | `docs/adr/` |
| CLEAN-ROOM (spec R1-medium §33l): row | agent docs |
| Runnable demos and sample data | `examples/` |
| Runtime data (never committed) | `~/Library/Application Support/OmniVoice/` on Mac |

## What *doesn't* live at the root anymore

Removed in the cleanup pass:

| File | Why it was there | Where it went |
|---|---|---|
| `test_crash.py`, `test_server.py`, `test_whisper.py`, `test_mock.py`, `test_pyannote.py` | One-off debug scripts from an April 14 crash investigation. Imported symbols that no longer exist after the router refactor. | Deleted (already gitignored, referenced dead code). |
| `benchmark.py` | Another stale debug script; imported `backend.main._get_db` which no longer exists. | Deleted. |
| `output.wav`, `test.wav` | Runtime artifacts. | Deleted / moved out. |
| `crash_log.txt` | Runtime log. Now written to `$DATA_DIR/crash_log.txt`. | Deleted. |
| `omnivoice.zip` (148 MB) | Offline reference archive of the project itself. | Moved out of the repo to `../omnivoice.zip.bak`. |
| `data/` | Only contained `.DS_Store`. | Deleted. |
| `legacy_gradio/` | The pre-React Gradio UI. Kept for historical reference. | Archived to `research/legacy_gradio/`, then removed in the 2026-07-12 cleanup (git history). |
| Scattered `.DS_Store` files | macOS Finder droppings. | Deleted from every non-ignored directory. |

Removed in the 2026-07-12 cleanup pass (all preserved in git history):

| Dir | Why it was there | Where it went |
|---|---|---|
| `.planning/` (74 files) | GSD-era planning archive: phases, quick plans, issue clusters. The GSD workflow was retired 2026-07-08. | Deleted; the four load-bearing decision docs moved to `docs/adr/`. |
| CLEAN-ROOM (spec R1-medium §33m): row | .planning/ removal |
| `design/` | ASCII mockups of the pre-React target UX, superseded by the shipped app. | Deleted. |
| `research/` | Archived legacy Gradio UI + April-2026 competitor notes. | Deleted. |
| CLEAN-ROOM (spec R1-medium §33n): row | .agents/ removal |

## Scaling path (proposed, not yet executed)

The current flat layout works fine for the current size. If the project grows to include additional apps (a mobile companion, a plugin SDK, multiple backends), migrate to a Turborepo-style monorepo:

```
VoiceStudio/
├── apps/
│   ├── api/                 ← was backend/
│   └── desktop/             ← was electron/ (desktop + browser UI)
├── packages/
│   ├── omnivoice-model/     ← was omnivoice/
│   └── tts-adapters/        ← new; the pluggable TTS interface from ROADMAP phase 3
├── config/
│   └── docker/
├── tests/
└── docs/
```

**Do not execute this migration without a dedicated PR.** It breaks:
- `pyproject.toml` `[tool.hatch.build.targets.{sdist,wheel}]` paths
- `package.json` workspaces and scripts
- `turbo.json`, `Dockerfile`, `docker-compose.yml` paths
- Electron Builder, native-helper, updater and packaged-smoke paths
- every import that reads `from backend.main import …` (tests, scripts)
- the root `package.json` as the version source of truth and its mirrors

Migrate when adding the second `apps/*` or the second `packages/*`. Not before.

## Conventions

- **Filenames:** snake_case for Python, kebab-case or PascalCase for JS/TS components, lowercase for Markdown.
- CLEAN-ROOM (spec R1-medium §33o): test-mirroring convention bullet
- **One-off scripts** go into `scripts/` with a descriptive name, not `test_*.py` at the root.
- **New top-level directories** require a PR that updates *this file*.
