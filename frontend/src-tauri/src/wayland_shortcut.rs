//! Wayland global shortcut support through xdg-desktop-portal.
//!
//! `tauri-plugin-global-shortcut` uses `global-hotkey`, whose Linux backend is
//! X11-only. Under XWayland its registration can still return `Ok(())`, but a
//! native Wayland compositor never sends it key events. The portal is the
//! compositor-owned, permission-aware API for this job.

use std::collections::HashMap;

use tauri::Emitter;
use zbus::{
    blocking::{Connection, Proxy},
    zvariant::{OwnedObjectPath, OwnedValue, Str},
};

const DESKTOP_DESTINATION: &str = "org.freedesktop.portal.Desktop";
const DESKTOP_PATH: &str = "/org/freedesktop/portal/desktop";
const GLOBAL_SHORTCUTS_INTERFACE: &str = "org.freedesktop.portal.GlobalShortcuts";
const REQUEST_INTERFACE: &str = "org.freedesktop.portal.Request";
const REGISTRY_INTERFACE: &str = "org.freedesktop.host.portal.Registry";
const SHORTCUT_ID: &str = "voice-dictation";

type VariantMap = HashMap<String, OwnedValue>;

const DESKTOP_ID: &str = "com.debpalash.omnivoice-studio";

fn desktop_entry_exists() -> bool {
    let filename = format!("{DESKTOP_ID}.desktop");
    let user_entry = dirs_next::data_dir()
        .map(|dir| dir.join("applications").join(&filename))
        .is_some_and(|path| path.is_file());
    if user_entry {
        return true;
    }
    std::env::var_os("XDG_DATA_DIRS")
        .map(|dirs| {
            std::env::split_paths(&dirs)
                .any(|dir| dir.join("applications").join(&filename).is_file())
        })
        .unwrap_or_else(|| {
            ["/usr/local/share", "/usr/share"].iter().any(|dir| {
                std::path::Path::new(dir)
                    .join("applications")
                    .join(&filename)
                    .is_file()
            })
        })
}

fn desktop_exec_path() -> Result<std::path::PathBuf, String> {
    // AppImage's current_exe() points inside its transient mount. APPIMAGE is
    // the stable launcher path the desktop entry must retain.
    if let Some(path) = std::env::var_os("APPIMAGE").filter(|path| !path.is_empty()) {
        return Ok(path.into());
    }
    std::env::current_exe().map_err(|error| format!("could not locate VoiceStudio: {error}"))
}

fn desktop_exec_value(path: &std::path::Path) -> String {
    let escaped = path
        .to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('`', "\\`")
        .replace('$', "\\$");
    format!("\"{escaped}\"")
}

/// The host portal resolves un-sandboxed apps through their desktop entry.
/// Deb packages already install one; dev builds and standalone AppImages may
/// not. Add an invisible identity entry only when none exists.
fn ensure_desktop_identity() -> Result<(), String> {
    if desktop_entry_exists() {
        return Ok(());
    }
    let applications = dirs_next::data_dir()
        .ok_or("could not locate the user data directory")?
        .join("applications");
    std::fs::create_dir_all(&applications)
        .map_err(|error| format!("could not create applications directory: {error}"))?;
    let entry = format!(
        "[Desktop Entry]\nType=Application\nName=VoiceStudio\nExec={}\nTerminal=false\nNoDisplay=true\nStartupWMClass=VoiceStudio\nX-VoiceStudio-Generated=true\n",
        desktop_exec_value(&desktop_exec_path()?)
    );
    let path = applications.join(format!("{DESKTOP_ID}.desktop"));
    std::fs::write(&path, entry)
        .map_err(|error| format!("could not create {}: {error}", path.display()))?;
    log::info!("Installed Wayland portal identity at {}", path.display());
    Ok(())
}

pub fn is_wayland_session() -> bool {
    std::env::var("XDG_SESSION_TYPE")
        .map(|kind| kind.eq_ignore_ascii_case("wayland"))
        .unwrap_or(false)
        || std::env::var_os("WAYLAND_DISPLAY").is_some()
}

/// Convert Tauri's cross-platform accelerator spelling to the portal format.
/// The portal may still let the user choose a different chord in its consent
/// dialog, so an unknown spelling is deliberately omitted rather than guessed.
fn portal_trigger(accelerator: &str) -> Option<String> {
    let mut modifiers = Vec::new();
    let mut key = None;

    for part in accelerator
        .split('+')
        .map(str::trim)
        .filter(|part| !part.is_empty())
    {
        match part.to_ascii_lowercase().as_str() {
            "cmdorctrl" | "commandorcontrol" | "ctrl" | "control" | "cmd" | "command" => {
                if !modifiers.contains(&"CTRL") {
                    modifiers.push("CTRL");
                }
            }
            "shift" => modifiers.push("SHIFT"),
            "alt" | "option" => modifiers.push("ALT"),
            "super" | "meta" => modifiers.push("LOGO"),
            _ if key.is_none() => key = Some(part),
            _ => return None,
        }
    }

    let key = key?;
    if modifiers.is_empty() {
        return None;
    }
    modifiers.push(key);
    Some(modifiers.join("+"))
}

fn variant_string(value: &str) -> OwnedValue {
    OwnedValue::from(Str::from(value))
}

fn request_path(connection: &Connection, token: &str) -> Result<OwnedObjectPath, String> {
    let sender = connection
        .unique_name()
        .ok_or("session bus did not assign a unique name")?
        .as_str()
        .trim_start_matches(':')
        .replace('.', "_");
    OwnedObjectPath::try_from(format!("{DESKTOP_PATH}/request/{sender}/{token}"))
        .map_err(|error| format!("invalid portal request path: {error}"))
}

fn response_for<F>(connection: &Connection, token: &str, call: F) -> Result<VariantMap, String>
where
    F: FnOnce() -> Result<OwnedObjectPath, zbus::Error>,
{
    // Subscribe before making the request: a fast portal is allowed to answer
    // immediately after returning the request handle.
    let expected = request_path(connection, token)?;
    let request = Proxy::new(
        connection,
        DESKTOP_DESTINATION,
        expected.as_str(),
        REQUEST_INTERFACE,
    )
    .map_err(|error| format!("portal request listener: {error}"))?;
    let mut responses = request
        .receive_signal("Response")
        .map_err(|error| format!("portal response listener: {error}"))?;

    let returned = call().map_err(|error| format!("portal request failed: {error}"))?;
    if returned != expected {
        return Err(format!(
            "portal returned unexpected request path {returned} (expected {expected})"
        ));
    }

    let message = responses
        .next()
        .ok_or("portal closed before answering the shortcut request")?;
    let (code, results): (u32, VariantMap) = message
        .body()
        .deserialize()
        .map_err(|error| format!("invalid portal response: {error}"))?;
    if code != 0 {
        return Err(format!(
            "portal shortcut request was declined (response {code})"
        ));
    }
    Ok(results)
}

fn run(app: tauri::AppHandle, accelerator: String) -> Result<(), String> {
    ensure_desktop_identity()?;
    let connection = Connection::session()
        .map_err(|error| format!("could not connect to the desktop portal: {error}"))?;

    // GNOME's host portal uses the installed desktop entry to associate this
    // un-sandboxed process with its desktop id.
    let registry = Proxy::new(
        &connection,
        DESKTOP_DESTINATION,
        DESKTOP_PATH,
        REGISTRY_INTERFACE,
    )
    .map_err(|error| format!("could not open the portal registry: {error}"))?;
    let registry_options: VariantMap = HashMap::new();
    if let Err(error) = registry.call::<_, _, ()>("Register", &(DESKTOP_ID, registry_options)) {
        // Development builds and portable AppImages may not have a desktop
        // entry for the host registry to resolve. Portal v1 does not require
        // this handshake, so continue and let CreateSession be authoritative.
        log::warn!("Wayland portal host registration skipped: {error}");
    }

    let portal = Proxy::new(
        &connection,
        DESKTOP_DESTINATION,
        DESKTOP_PATH,
        GLOBAL_SHORTCUTS_INTERFACE,
    )
    .map_err(|error| format!("could not open the global-shortcuts portal: {error}"))?;

    let process = std::process::id();
    let create_token = format!("vs_create_{process}");
    let session_token = format!("vs_session_{process}");
    let mut create_options = VariantMap::new();
    create_options.insert("handle_token".into(), variant_string(&create_token));
    create_options.insert(
        "session_handle_token".into(),
        variant_string(&session_token),
    );
    let mut create_results = response_for(&connection, &create_token, || {
        portal.call("CreateSession", &(create_options,))
    })?;
    let session_value = create_results
        .remove("session_handle")
        .ok_or("portal did not return a shortcut session")?;
    // The portal specification declares an object path, but deployed portal
    // versions historically returned a string. Accept both wire formats.
    let session = match session_value
        .try_clone()
        .ok()
        .and_then(|value| OwnedObjectPath::try_from(value).ok())
    {
        Some(path) => path,
        None => {
            let path = String::try_from(session_value).map_err(|error| {
                format!("portal returned an invalid shortcut session handle: {error}")
            })?;
            OwnedObjectPath::try_from(path)
                .map_err(|error| format!("portal returned an invalid session path: {error}"))?
        }
    };

    let mut shortcut_info = VariantMap::new();
    shortcut_info.insert(
        "description".into(),
        variant_string("Start and stop VoiceStudio dictation"),
    );
    if let Some(trigger) = portal_trigger(&accelerator) {
        shortcut_info.insert("preferred_trigger".into(), variant_string(&trigger));
    }
    let shortcuts = vec![(SHORTCUT_ID.to_string(), shortcut_info)];
    let bind_token = format!("vs_bind_{process}");
    let mut bind_options = VariantMap::new();
    bind_options.insert("handle_token".into(), variant_string(&bind_token));
    response_for(&connection, &bind_token, || {
        portal.call(
            "BindShortcuts",
            &(session.clone(), shortcuts, "", bind_options),
        )
    })?;

    log::info!("Wayland dictation shortcut registered through xdg-desktop-portal");
    let mut signals = portal
        .receive_all_signals()
        .map_err(|error| format!("could not listen for portal shortcuts: {error}"))?;
    for message in &mut signals {
        let header = message.header();
        let member = header
            .member()
            .map(|name| name.as_str().to_owned())
            .unwrap_or_default();
        if member != "Activated" && member != "Deactivated" {
            continue;
        }
        let (signal_session, shortcut_id, _timestamp, _options): (
            OwnedObjectPath,
            String,
            u64,
            VariantMap,
        ) = match message.body().deserialize() {
            Ok(body) => body,
            Err(error) => {
                log::warn!("Invalid Wayland shortcut signal: {error}");
                continue;
            }
        };
        if signal_session != session || shortcut_id != SHORTCUT_ID {
            continue;
        }
        if member == "Activated" {
            log::info!("Wayland shortcut pressed: dictation start");
            let _ = app.emit("tray-dictate", ());
        } else {
            log::info!("Wayland shortcut released: dictation stop");
            let _ = app.emit("tray-dictate-stop", ());
        }
    }
    Err("global-shortcuts portal closed the session".into())
}

pub fn register(app: tauri::AppHandle, accelerator: String) {
    if let Err(error) = std::thread::Builder::new()
        .name("wayland-global-shortcut".into())
        .spawn(move || {
            if let Err(error) = run(app, accelerator) {
                log::error!("Wayland dictation shortcut unavailable: {error}");
            }
        })
    {
        log::error!("Failed to start Wayland shortcut listener: {error}");
    }
}

#[cfg(test)]
mod tests {
    use super::{desktop_exec_value, portal_trigger};
    use std::path::Path;

    #[test]
    fn converts_tauri_accelerators_to_portal_triggers() {
        assert_eq!(
            portal_trigger("CmdOrCtrl+Shift+Space").as_deref(),
            Some("CTRL+SHIFT+Space")
        );
        assert_eq!(
            portal_trigger("Alt+Control+K").as_deref(),
            Some("ALT+CTRL+K")
        );
    }

    #[test]
    fn rejects_modifier_free_or_ambiguous_accelerators() {
        assert_eq!(portal_trigger("Space"), None);
        assert_eq!(portal_trigger("Ctrl+K+L"), None);
    }

    #[test]
    fn desktop_exec_paths_are_quoted_and_escaped() {
        assert_eq!(
            desktop_exec_value(Path::new("/tmp/Voice Studio/$build")),
            "\"/tmp/Voice Studio/\\$build\""
        );
    }
}
