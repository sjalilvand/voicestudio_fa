#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERIFY="$REPO_ROOT/scripts/verify-apprun-bundle.sh"
EXPECTED="$REPO_ROOT/frontend/src-tauri/appimage/AppRun"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

make_root() {
  local root="$1"
  mkdir -p "$root/usr/lib"
  printf '%s\n' '2.52.3' > "$root/usr/lib/.bundled-webkitgtk-version"
}

printf '%s\n' '2.52.3' > "$TMP/expected-marker"

make_root "$TMP/direct"
install -m 755 "$EXPECTED" "$TMP/direct/AppRun"
bash "$VERIFY" "$TMP/direct" "$EXPECTED" "$TMP/expected-marker"

make_root "$TMP/wrapped"
install -m 755 "$EXPECTED" "$TMP/wrapped/AppRun.wrapped"
cat > "$TMP/wrapped/AppRun" <<'WRAPPER'
#!/usr/bin/env bash
this_dir="$(dirname "$(readlink -f "${0}")")"
exec "$this_dir"/AppRun.wrapped "$@"
WRAPPER
chmod 755 "$TMP/wrapped/AppRun"
bash "$VERIFY" "$TMP/wrapped" "$EXPECTED" "$TMP/expected-marker"

make_root "$TMP/broken"
printf '%s\n' '#!/usr/bin/env bash' 'exit 0' > "$TMP/broken/AppRun"
chmod 755 "$TMP/broken/AppRun"
if bash "$VERIFY" "$TMP/broken" "$EXPECTED" "$TMP/expected-marker" >/dev/null 2>&1; then
  echo "FAIL: stock launcher was accepted without the custom launcher" >&2
  exit 1
fi

echo "PASS: direct, wrapped, and broken AppImage launcher chains classified"
