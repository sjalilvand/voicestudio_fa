//! One registration seam for the native global-shortcut plugin and the
//! Wayland GlobalShortcuts portal.

use std::str::FromStr;
use std::sync::atomic::Ordering;
use std::sync::Mutex;

use serde::Serialize;
use tauri::{Emitter, Manager};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};

use crate::TrayHandle;

#[derive(Clone, Debug, Serialize)]
pub struct ShortcutInfo {
    pub accelerator: String,
    pub display: String,
    pub backend: &'static str,
}

pub struct DictationShortcutManager {
    native: Mutex<Option<Shortcut>>,
    effective: Mutex<ShortcutInfo>,
    #[cfg(target_os = "linux")]
    portal: crate::wayland_shortcut::PortalShortcutState,
}

impl DictationShortcutManager {
    pub fn new(accelerator: &str) -> Self {
        Self {
            native: Mutex::new(None),
            effective: Mutex::new(ShortcutInfo {
                accelerator: accelerator.to_owned(),
                display: display_accelerator(accelerator),
                backend: backend_name(),
            }),
            #[cfg(target_os = "linux")]
            portal: crate::wayland_shortcut::PortalShortcutState::default(),
        }
    }

    pub fn register_initial(app: tauri::AppHandle, accelerator: String) {
        let accelerator = match Shortcut::from_str(&accelerator) {
            Ok(_) => accelerator,
            Err(error) => {
                let fallback = crate::config::default_dictation_shortcut();
                log::warn!(
                    "Saved shortcut '{accelerator}' is invalid ({error}); using '{fallback}'"
                );
                fallback
            }
        };
        #[cfg(target_os = "linux")]
        if crate::wayland_shortcut::is_wayland_session() {
            let revision = app.state::<Self>().portal.reserve();
            crate::wayland_shortcut::register_initial(app, accelerator, revision);
            return;
        }

        let manager = app.state::<Self>();
        match manager.replace_native(&app, &accelerator) {
            Ok(()) => {
                manager.publish(&app, accelerator, None, "native");
            }
            Err(error) => log::warn!("Failed to register global shortcut: {error}"),
        }
    }

    pub fn replace(
        &self,
        app: &tauri::AppHandle,
        accelerator: &str,
    ) -> Result<ShortcutInfo, String> {
        Shortcut::from_str(accelerator)
            .map_err(|error| format!("Invalid shortcut '{accelerator}': {error}"))?;

        #[cfg(target_os = "linux")]
        if crate::wayland_shortcut::is_wayland_session() {
            let display = self.portal.replace(app.clone(), accelerator.to_owned())?;
            return Ok(self.publish(app, accelerator.to_owned(), Some(display), "portal"));
        }

        self.replace_native(app, accelerator)?;
        Ok(self.publish(app, accelerator.to_owned(), None, "native"))
    }

    pub fn info(&self) -> ShortcutInfo {
        self.effective
            .lock()
            .map(|info| info.clone())
            .unwrap_or_else(|_| ShortcutInfo {
                accelerator: String::new(),
                display: String::new(),
                backend: backend_name(),
            })
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn register_portal_initial(
        &self,
        app: &tauri::AppHandle,
        accelerator: String,
        revision: u64,
    ) -> Result<(), String> {
        Shortcut::from_str(&accelerator)
            .map_err(|error| format!("Invalid shortcut '{accelerator}': {error}"))?;
        let display = self
            .portal
            .replace_reserved(app.clone(), accelerator.clone(), revision)?;
        self.publish(app, accelerator, Some(display), "portal");
        Ok(())
    }

    fn replace_native(&self, app: &tauri::AppHandle, accelerator: &str) -> Result<(), String> {
        let parsed = Shortcut::from_str(accelerator)
            .map_err(|error| format!("Invalid shortcut '{accelerator}': {error}"))?;
        let global = app.global_shortcut();
        let mut slot = self
            .native
            .lock()
            .map_err(|_| "shortcut lock poisoned".to_string())?;
        let previous = slot.take();
        if let Some(shortcut) = previous.as_ref() {
            let _ = global.unregister(shortcut.clone());
        }
        if let Err(error) = global.register(parsed.clone()) {
            if let Some(shortcut) = previous {
                if global.register(shortcut.clone()).is_ok() {
                    *slot = Some(shortcut);
                }
            }
            return Err(format!("Failed to register '{accelerator}': {error}"));
        }
        *slot = Some(parsed);
        Ok(())
    }

    fn publish(
        &self,
        app: &tauri::AppHandle,
        accelerator: String,
        display: Option<String>,
        backend: &'static str,
    ) -> ShortcutInfo {
        let info = ShortcutInfo {
            display: display.unwrap_or_else(|| display_accelerator(&accelerator)),
            accelerator,
            backend,
        };
        if let Ok(mut current) = self.effective.lock() {
            *current = info.clone();
        }
        let recording = app
            .try_state::<crate::AppFlags>()
            .is_some_and(|flags| flags.dictating.load(Ordering::SeqCst));
        update_tray_hint(app, &info.display, recording);
        let _ = app.emit("dictation-shortcut-changed", &info);
        log::info!(
            "Dictation shortcut '{}' active through {}",
            info.accelerator,
            info.backend
        );
        info
    }
}

pub fn update_tray_hint(app: &tauri::AppHandle, display: &str, recording: bool) {
    let verb = if recording { "Stop" } else { "Start" };
    if let Ok(slot) = app.state::<TrayHandle>().dictate.lock() {
        if let Some(item) = slot.as_ref() {
            if let Err(error) = item.set_text(format!("{verb} Dictation  {display}")) {
                log::warn!("Could not update the dictation tray hint: {error}");
            }
        }
    }
}

pub fn display_accelerator(accelerator: &str) -> String {
    #[cfg(target_os = "macos")]
    {
        return accelerator
            .split('+')
            .map(|part| match part.to_ascii_lowercase().as_str() {
                "cmdorctrl" | "commandorcontrol" | "cmd" | "command" | "meta" | "super" => {
                    "⌘".to_owned()
                }
                "ctrl" | "control" => "⌃".to_owned(),
                "alt" | "option" => "⌥".to_owned(),
                "shift" => "⇧".to_owned(),
                _ => part.to_owned(),
            })
            .collect::<String>();
    }
    #[cfg(not(target_os = "macos"))]
    accelerator
        .split('+')
        .map(|part| match part.to_ascii_lowercase().as_str() {
            "cmdorctrl" | "commandorcontrol" | "ctrl" | "control" => "Ctrl",
            "cmd" | "command" | "meta" | "super" => "Super",
            "alt" | "option" => "Alt",
            "shift" => "Shift",
            _ => part,
        })
        .collect::<Vec<_>>()
        .join("+")
}

fn backend_name() -> &'static str {
    // The focused-window bridge is available before the OS registration
    // completes and remains the truthful fallback if that registration fails.
    "focused"
}

#[cfg(test)]
mod tests {
    use super::display_accelerator;

    #[test]
    fn formats_the_platform_shortcut_hint() {
        #[cfg(target_os = "macos")]
        assert_eq!(display_accelerator("CmdOrCtrl+Shift+Space"), "⌘⇧Space");
        #[cfg(not(target_os = "macos"))]
        assert_eq!(
            display_accelerator("CmdOrCtrl+Shift+Space"),
            "Ctrl+Shift+Space"
        );
        #[cfg(not(target_os = "macos"))]
        assert_eq!(display_accelerator("Cmd+Option+K"), "Super+Alt+K");
    }
}
