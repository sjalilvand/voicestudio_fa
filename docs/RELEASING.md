# Releasing — self-updating builds for mac / linux / windows

This doc covers the release workflow after the auto-updater wiring landed. Read top-to-bottom the first time. After that, cutting a release is the three commands in §5.

## 1. One-time repo setup

The signing key was generated locally at `~/.tauri/omnivoice-updater.key` (private) and `~/.tauri/omnivoice-updater.key.pub` (public). The public key is already embedded in `frontend/src-tauri/tauri.conf.json` — that's what shipping clients use to verify updates.

The private key needs to live in **GitHub Actions Secrets** so CI can sign each release:

1. Read the private key contents:
   ```
   cat ~/.tauri/omnivoice-updater.key
   ```
2. GitHub → Settings → Secrets and variables → Actions → **New repository secret** (on `debpalash/VoiceStudio`, which is where the updater endpoint points):
   - Name: `TAURI_SIGNING_PRIVATE_KEY`
   - Value: paste the full contents (including the `untrusted comment:` header line)
3. Add a second secret:
   - Name: `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`
   - Value: leave blank (the key was generated without a password)

**Back the key up.** Copy `~/.tauri/omnivoice-updater.key` to a password manager or encrypted vault. If you lose it, you can never ship an update for any client that has the current public key — they'll be stranded and need a manual reinstall.

## 2. One-time account setup (you)

**Rotate the leaked GH token** (the `ghp_...` in `origin` remote). See the session transcript — already flagged. Do this before anything else.

No Apple Developer / Windows signing certs needed for v1. Apps ship unsigned; first-launch shows "unverified developer" warnings that users bypass with right-click → Open (mac) or "Run anyway" (Windows SmartScreen). Self-update still works — Tauri's updater verifies via its own signing key, independent of OS code signing.

## 3. What the updater does

On every app launch, the webview:
1. Fetches `https://github.com/debpalash/VoiceStudio/releases/latest/download/latest.json`
2. Compares the version in `latest.json` to the running app's version (from `tauri.conf.json`)
3. If newer, shows a native dialog: *"A new version (x.y.z) is available. Download and install now?"*
4. If user accepts, downloads the signed update bundle, verifies the minisign signature against the embedded pubkey, replaces the app in place, relaunches.

Failures (no network, 404, signature mismatch) are silent — the app continues to launch normally. Check the frontend devtools console for `Updater check failed` messages if you're debugging.

## 4. Version bumps

`frontend/package.json` is the **single source of truth** for the app version
(hard rule, owner-set 2026-06-16 — full rationale in CLAUDE.md → Conventions →
Versioning). Vite injects `__APP_VERSION__` from it, and
`frontend/src-tauri/tauri.conf.json` derives its bundle version from it
(`"version": "../package.json"` — never hand-edit a literal back in). Three
toolchain-required mirrors are bumped in lockstep:

- `frontend/src-tauri/Cargo.toml`
- `pyproject.toml`
- `backend/core/version.py` (`_FALLBACK_VERSION`)

Lockstep is guarded by `tests/test_app_version.py`. With `AUTO_VERSION_BUMP`
off (the current owner setting), `main` holds at the released version between
releases; the post-release bump to `X.Y.(Z+1)` happens only when the owner
asks. Keep bumps monotonic — the updater uses semver comparison, so `v0.2.0`
does not update clients already on `v0.2.1`.

## 5. Cutting a release

1. **CHANGELOG first (hard rule):** make sure `CHANGELOG.md` has a complete,
   user-facing `## [X.Y.Z] — DATE` section (rename `## [Unreleased]`).
   `release.yml` extracts that section verbatim as the GitHub Release body —
   a missing section ships a bare release.
2. Verify the version files match the tag you're about to cut:
   `uv run pytest tests/test_app_version.py -q`.
3. Tag and push:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

`electron-release.yml` builds Linux x64, Windows x64, macOS arm64 and macOS
x64 installers with updater metadata and packaged startup checks. Ordinary tag
pushes create drafts; a tag-scoped manual dispatch with `publish=true` publishes
after all four targets pass. Signing checks apply by default.

For the one-time transition tag, set `TAURI_SUNSET_TAG`, dispatch `release.yml`
on that tag with `draft=true`, and wait for its final Tauri installers and signed
updater feeds. Then dispatch `electron-release.yml` on the same tag. Automatic
Electron builds are skipped for this tag to avoid racing the Tauri draft.
Keep the release draft until both builds and their checks have passed.
See [Electron transition](#electron-transition-next-desktop-release) below for
signing requirements and the explicit owner-only unsigned exception.

## 5b. Deployment channels — all must ship (hard rule, owner-set 2026-07-16)

A version bump is not "released" until **every** channel below carries it.
Verify each one after the workflows finish — a missing channel is a release
bug to fix immediately, not backlog.

| Channel | Source | Produced by | How to verify |
|---|---|---|---|
| GitHub Release: Electron installers and updater manifests | the `vX.Y.Z` tag | `electron-release.yml`, explicit publish dispatch | All four platforms, Electron manifests, SHA256SUMS.txt, versioned CHANGELOG notes; retained Tauri feeds point to the final Tauri tag |
| Final Tauri installers and signed updater feeds | `TAURI_SUNSET_TAG` | `release.yml`, manual dispatch only | Both macOS architectures, Windows system/user installers, Linux AppImage, signed `latest.json` and `latest-user.json` |
| Desktop preview channel | frozen during transition | no scheduled publishing | Existing preview assets remain available; new desktop previews are paused |
| GHCR CUDA image: `:X.Y.Z`, `:X.Y`, `:stable` | the tag | `docker.yml` on tag push | `docker manifest inspect ghcr.io/debpalash/omnivoice-studio:X.Y.Z` |
| GHCR ROCm image: `:X.Y.Z-rocm`, `:X.Y-rocm`, `:stable-rocm` | the tag | `docker.yml` on tag push | same, with `-rocm` suffix |
| Docker Hub mirror of **all** the above tags | the tag | `docker.yml` (gated on `DOCKERHUB_*` secrets) | tag list at hub.docker.com/r/palashdeb/omnivoice-studio/tags |
| Docker Hub **overview page** | `deploy/dockerhub-overview.md` @ main | `docker.yml` on main pushes | **read the step log, not the job status** — the step is `continue-on-error` and 403s silently when `DOCKERHUB_TOKEN` lacks description-edit scope |
| Rolling Docker previews: `:latest`, `:main`, `:rocm` | **`main` only** | `docker.yml` on every main push | tag timestamps move with main |

**Preview/RC policy:** there are no RC tags (beta cadence — see CLAUDE.md).
Rolling Docker previews always build from `main`. Desktop preview publication
is paused during the Electron transition; never publish a side-branch preview.

## 6. Expect-to-fail-first-time on Windows and Linux

mac-ARM is tested locally. The other three platforms will likely hit PyInstaller issues on their first CI run because neither dependency set nor platform quirks have been exercised. Common failures to expect:

- **Windows**: `mlx_whisper` is mac-only — need to conditional-guard the import in `backend.spec`. `demucs`'s CUDA autodetect may pull wheels we don't want. Long-path limits during the PyInstaller bundle.
- **Linux**: `libasound` / `libwebkit2gtk` dev headers vs runtime confusion. AppImage FUSE assumptions on the runner.
- **mac-Intel**: should work, but torch wheels for x86_64 differ — watch for `nvidia-*` wheels sneaking in via the default torch.

When a target fails, either fix the root cause in the spec / workflow, or comment that matrix row out temporarily and keep the working targets shipping. The `fail-fast: false` setting means one failure doesn't kill the others.

## 7. Testing the updater locally (before shipping a tag)

Two options:

**Option A — dry run the manifest:**
After a release is published, hit the updater URL manually:
```
curl -L https://github.com/debpalash/VoiceStudio/releases/latest/download/latest.json | jq
```
You should see platform-keyed download URLs + minisign signatures. If that JSON looks right, clients will pick it up.

**Option B — full end-to-end:**
1. Install v0.1.0 on a fresh machine (or clean-installed Applications).
2. Cut v0.2.0 (bump, tag, push, wait for CI; the workflow publishes the release).
3. Launch the installed v0.1.0. Within seconds, the dialog should appear.
4. Accept → app downloads, verifies, replaces, relaunches as v0.2.0.

If step 3 silently does nothing, DevTools console in the app webview has the `Updater check failed:` log.

## 8. Rolling back

There's no "revert update" flow for clients — they'll only see a *newer* version. To roll back:
1. Delete the broken release from GitHub Releases (or mark it as pre-release).
2. Re-tag the previous good commit with a higher version (e.g., if you shipped bad `v0.2.0`, tag `v0.2.1` on the old `v0.1.0` commit).
3. Clients auto-update to the "new" v0.2.1 which is actually the old code.

Ugly but it works. Better plan: test with Option B above before publishing the draft.

## Retrying a partially published build

Use GitHub Actions **Re-run failed jobs** for the same release run. On retries,
the workflow removes only the current version's installers for that job's target
before Tauri uploads them again. A macOS retry also replaces that architecture's
versionless updater archive. Other versions, sibling platforms, and updater
manifests remain intact. Inventory or deletion permission/network failures stop
the job instead of hiding an upload collision.

## Electron transition (next desktop release)

Electron is the primary desktop distribution. electron-release.yml builds Linux
x64, Windows x64, macOS arm64 and macOS x64, checks packaged startup and updater
artifacts, then creates a draft. Publishing requires a tag-scoped manual dispatch
with publish=true. Tag pushes never publish automatically. electron-build.yml
remains the artifact-only rehearsal; run it before tagging.

Set TAURI_SUNSET_TAG to the final Tauri version tag. Run the manual release.yml
on that tag first; it rejects other refs. Automatic Tauri builds and scheduled
previews are retired. Keep the transition release draft until Electron on the
same tag completes. Electron requires the final signed latest.json and
latest-user.json assets; subsequent releases copy those feeds without changing
their immutable sunset payload URLs. Retain the sunset release and its assets.

Write versioned CHANGELOG notes before release. Review all four platform builds,
checksums, signing requirements and docs/electron-migration.md. Existing Electron
artifact names and app IDs remain stable for updater compatibility. This pipeline
ships stable releases; rolling preview publication is paused during transition.

Preparation is not proof of cross-platform packaging, signing, migration, or a
real installed update hop. Record those results before release. Keep Tauri source
and shared assets until remaining Electron resource references are relocated.
No tag, version bump, or publishing is authorized by workflow preparation alone.

Electron signing uses ELECTRON_CSC_LINK and ELECTRON_CSC_KEY_PASSWORD secrets.
Without them rehearsal/draft artifacts are unsigned or ad-hoc signed. Publishing
checks macOS signing/notarization and Windows Authenticode signatures by default.
The owner may explicitly choose the existing unsigned-release policy by dispatching
with `allow_unsigned=true` (both dispatch and rerun actors must be the repository owner); the release notes then disclose OS trust warnings and
unverified macOS automatic updates. Never select this exception without the owner's
choice. Tauri's signing keys do not sign Electron packages.

For the transition tag, automatic Electron release jobs are skipped. Build the
manual Tauri sunset draft first, then dispatch Electron on the same tag after
its signed updater feeds exist. Later tags build Electron automatically.
