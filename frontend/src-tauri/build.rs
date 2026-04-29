use std::path::PathBuf;

// Create a placeholder `binaries/uv-<target-triple>` file if one doesn't
// already exist for the current target. Tauri's `bundle.externalBin`
// config is validated at every build (including `cargo check`), and it
// hard-errors when the source binary is missing — which it is in dev,
// because the real `uv` binary is only fetched during release builds in
// CI. The placeholder is empty (zero bytes) and cannot actually be run;
// `find_bundled_uv()` at runtime falls back to PATH or the download path
// when the bundled file isn't a real executable. CI overwrites this file
// with the real binary fetched from astral-sh/uv before the tauri-action
// bundle step.
fn ensure_uv_placeholder() {
    let triple = std::env::var("TARGET").unwrap_or_default();
    if triple.is_empty() {
        return;
    }
    let manifest_dir = std::env::var("CARGO_MANIFEST_DIR").unwrap_or_else(|_| ".".into());
    let binaries_dir = PathBuf::from(&manifest_dir).join("binaries");
    let _ = std::fs::create_dir_all(&binaries_dir);
    let suffix = if triple.contains("windows") { ".exe" } else { "" };
    let target_path = binaries_dir.join(format!("uv-{}{}", triple, suffix));
    if !target_path.exists() {
        let _ = std::fs::write(&target_path, b"");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(meta) = std::fs::metadata(&target_path) {
                let mut perms = meta.permissions();
                perms.set_mode(0o755);
                let _ = std::fs::set_permissions(&target_path, perms);
            }
        }
    }
}

fn main() {
    ensure_uv_placeholder();
    tauri_build::build();
}
