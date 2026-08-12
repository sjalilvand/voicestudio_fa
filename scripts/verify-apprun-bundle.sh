#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:?AppDir root is required}"
EXPECTED_APPRUN="${2:?expected AppRun is required}"
EXPECTED_MARKER="${3:?expected WebKitGTK marker is required}"

fail() {
  echo "FAIL — $1" >&2
  exit 1
}

[ -x "$ROOT/AppRun" ] || fail "final AppImage launcher is missing or not executable"

if cmp -s "$ROOT/AppRun" "$EXPECTED_APPRUN"; then
  : # linuxdeploy did not install launcher hooks.
elif [ -x "$ROOT/AppRun.wrapped" ] \
  && cmp -s "$ROOT/AppRun.wrapped" "$EXPECTED_APPRUN" \
  && grep -Fq 'exec "$this_dir"/AppRun.wrapped "$@"' "$ROOT/AppRun"; then
  : # GTK/GStreamer hooks wrap the custom launcher by design.
else
  fail "custom AppRun missing from final AppImage launcher chain"
fi

[ -s "$ROOT/usr/lib/.bundled-webkitgtk-version" ] \
  || fail "bundled WebKitGTK version marker missing"
cmp -s "$ROOT/usr/lib/.bundled-webkitgtk-version" "$EXPECTED_MARKER" \
  || fail "bundled WebKitGTK version marker is stale or mismatched"

echo "OK — AppImage uses the custom launcher and current WebKitGTK marker"
