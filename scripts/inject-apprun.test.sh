#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

OMNIVOICE_TAURI_TOOLS_DIR="$TMP/tools" \
OMNIVOICE_TARGET_ARCH=amd64 \
OMNIVOICE_WEBKIT_VERSION=2.48.7 \
  bash "$REPO_ROOT/scripts/inject-apprun.sh"

cmp -s \
  "$REPO_ROOT/frontend/src-tauri/appimage/AppRun" \
  "$TMP/tools/AppRun-x86_64"
[ -x "$TMP/tools/AppRun-x86_64" ]
[ "$(cat "$TMP/tools/bundled-webkitgtk-version")" = "2.48.7" ]

echo "PASS: Tauri AppImage tool cache seeded"
