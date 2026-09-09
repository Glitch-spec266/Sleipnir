use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, State, WindowEvent};

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct VoiceSettings {
    wake_name: String,
    local_wake: bool,
    start_at_login: bool,
    push_to_talk_shortcut: String,
    transcription: String,
    response_model: String,
    escalation: String,
    voice_provider: String,
    voice_id: String,
    accent: String,
    interruptible: bool,
}

impl Default for VoiceSettings {
    fn default() -> Self {
        Self {
            wake_name: "Sleipnir".into(),
            local_wake: true,
            start_at_login: false,
            push_to_talk_shortcut: "Space".into(),
            transcription: "local".into(),
            response_model: "openrouter/auto".into(),
            escalation: "automatic".into(),
            voice_provider: "system".into(),
            voice_id: "system-natural".into(),
            accent: "neutral".into(),
            interruptible: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct Preferences {
    run_root: PathBuf,
    voice: VoiceSettings,
}

struct DesktopState {
    preferences: Mutex<Preferences>,
    listening: Mutex<bool>,
    preferences_path: PathBuf,
}

fn initial_run_root() -> PathBuf {
    env::var_os("SLEIPNIR_RUN_ROOT")
        .map(PathBuf::from)
        .or_else(|| env::current_dir().ok())
        .unwrap_or_else(|| PathBuf::from("."))
}

fn load_preferences(path: &Path) -> Preferences {
    fs::read_to_string(path)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_else(|| Preferences {
            run_root: initial_run_root(),
            voice: VoiceSettings::default(),
        })
}

fn persist_preferences(path: &Path, preferences: &Preferences) -> Result<(), String> {
    let parent = path.parent().ok_or("invalid settings path")?;
    fs::create_dir_all(parent).map_err(|error| format!("create settings directory: {error}"))?;
    let temporary = path.with_extension("json.tmp");
    let encoded = serde_json::to_vec_pretty(preferences)
        .map_err(|error| format!("encode settings: {error}"))?;
    fs::write(&temporary, encoded).map_err(|error| format!("write settings: {error}"))?;
    fs::rename(&temporary, path).map_err(|error| format!("publish settings: {error}"))?;
    Ok(())
}

fn python_executable() -> String {
    env::var("SLEIPNIR_PYTHON").unwrap_or_else(|_| "python3".into())
}

fn core_snapshot(run_root: &Path) -> Result<Value, String> {
    let output = Command::new(python_executable())
        .args(["-m", "sleipnir.gui", "snapshot", "--run-root"])
        .arg(run_root)
        .output()
        .map_err(|error| format!("start local Sleipnir core: {error}"))?;
    if !output.status.success() {
        let detail = String::from_utf8_lossy(&output.stderr).trim().to_owned();
        return Err(if detail.is_empty() {
            "local Sleipnir core returned no dashboard".into()
        } else {
            detail
        });
    }
    serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("decode local dashboard: {error}"))
}

#[tauri::command]
fn load_dashboard(state: State<'_, DesktopState>) -> Result<Value, String> {
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    let listening = *state.listening.lock().map_err(|_| "voice lock poisoned")?;
    let mut snapshot = core_snapshot(&preferences.run_root)?;
    snapshot["voice"] = json!({
        "phase": if listening { "armed" } else { "off" },
        "heard": "",
        "level": 0.0,
        "privacyLabel": if listening { "Wake phrase stays on this device" } else { "Microphone is off" },
        "settings": preferences.voice,
    });
    Ok(snapshot)
}

#[tauri::command]
fn select_run_root(path: String, state: State<'_, DesktopState>) -> Result<(), String> {
    let candidate = PathBuf::from(path)
        .canonicalize()
        .map_err(|error| format!("open project: {error}"))?;
    if !candidate.join("plan.json").is_file() {
        return Err(format!(
            "{} does not contain plan.json",
            candidate.display()
        ));
    }
    let mut preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?;
    preferences.run_root = candidate;
    persist_preferences(&state.preferences_path, &preferences)
}

#[tauri::command]
fn set_voice_settings(
    settings: VoiceSettings,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    let name = settings.wake_name.trim();
    if !(2..=32).contains(&name.chars().count()) {
        return Err("wake name must contain 2 to 32 characters".into());
    }
    let mut preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?;
    preferences.voice = settings;
    persist_preferences(&state.preferences_path, &preferences)
}

#[tauri::command]
fn set_listening(enabled: bool, state: State<'_, DesktopState>) -> Result<(), String> {
    *state.listening.lock().map_err(|_| "voice lock poisoned")? = enabled;
    Ok(())
}

#[tauri::command]
fn send_message(text: String) -> Result<(), String> {
    if text.trim().is_empty() {
        return Ok(());
    }
    Err("The native agent service is not running yet; the instruction was not sent.".into())
}

#[tauri::command]
fn start_project(goal: String) -> Result<(), String> {
    if goal.trim().is_empty() {
        return Err("project goal cannot be empty".into());
    }
    Err("Project creation is not connected to the native agent service yet.".into())
}

#[tauri::command]
fn review_item(
    item_id: String,
    decision: String,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    if !item_id
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || "._-".contains(character))
    {
        return Err("invalid review id".into());
    }
    let root = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .run_root
        .clone();
    let proposal = root.join("proposals").join(format!("{item_id}.json"));
    if !proposal.is_file() {
        return Err("review proposal no longer exists".into());
    }
    match decision.as_str() {
        "approve" => {
            let output = Command::new("sleipnir")
                .args(["--run-root"])
                .arg(&root)
                .arg("apply-revision")
                .arg(&proposal)
                .output()
                .map_err(|error| format!("start revision review: {error}"))?;
            if output.status.success() {
                Ok(())
            } else {
                Err(String::from_utf8_lossy(&output.stderr).trim().to_owned())
            }
        }
        "reject" => fs::rename(&proposal, proposal.with_extension("json.rejected"))
            .map_err(|error| format!("mark proposal rejected: {error}")),
        "request_changes" => {
            fs::rename(&proposal, proposal.with_extension("json.changes-requested"))
                .map_err(|error| format!("mark proposal for changes: {error}"))
        }
        _ => Err("unknown review decision".into()),
    }
}

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            let config_dir = app.path().app_config_dir()?;
            let preferences_path = config_dir.join("preferences.json");
            app.manage(DesktopState {
                preferences: Mutex::new(load_preferences(&preferences_path)),
                listening: Mutex::new(false),
                preferences_path,
            });

            let show = MenuItem::with_id(app, "show", "Show Sleipnir", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &quit])?;
            let mut tray = TrayIconBuilder::new()
                .menu(&menu)
                .show_menu_on_left_click(false);
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.on_menu_event(|app, event| match event.id.as_ref() {
                "show" => show_main(app),
                "quit" => app.exit(0),
                _ => {}
            })
            .on_tray_icon_event(|tray, event| {
                if let TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                } = event
                {
                    show_main(tray.app_handle());
                }
            })
            .build(app)?;
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            load_dashboard,
            select_run_root,
            send_message,
            start_project,
            review_item,
            set_voice_settings,
            set_listening,
        ])
        .run(tauri::generate_context!())
        .expect("failed to run Sleipnir desktop");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_keep_wake_local_and_secrets_out_of_preferences() {
        let encoded = serde_json::to_string(&VoiceSettings::default()).unwrap();
        assert!(encoded.contains("localWake"));
        assert!(!encoded.to_lowercase().contains("api_key"));
        assert!(!encoded.to_lowercase().contains("token"));
    }
}
