use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::env;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, State, WindowEvent};
use tauri_plugin_shell::process::{Command as ShellCommand, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct CoreOutput {
    success: bool,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

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

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AdvancedModules {
    mission: bool,
    chronicle: bool,
    helm: bool,
    tools: bool,
    audit: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct ProviderEnvironment {
    openrouter: String,
    gemini: String,
    nvidia: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct AppSettings {
    color_scheme: String,
    adaptive_scheme: bool,
    advanced_modules: AdvancedModules,
    telemetry_enabled: bool,
    permission_mode: String,
    provider_env: ProviderEnvironment,
}

impl Default for AppSettings {
    fn default() -> Self {
        Self {
            color_scheme: "orbit".into(),
            adaptive_scheme: true,
            advanced_modules: AdvancedModules {
                mission: true,
                chronicle: true,
                helm: true,
                tools: true,
                audit: true,
            },
            telemetry_enabled: true,
            permission_mode: "ask".into(),
            provider_env: ProviderEnvironment {
                openrouter: "OPENROUTER_API_KEY".into(),
                gemini: "GEMINI_API_KEY".into(),
                nvidia: "NVIDIA_API_KEY".into(),
            },
        }
    }
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
    settings: AppSettings,
}

struct DesktopState {
    preferences: Mutex<Preferences>,
    listening: Mutex<bool>,
    preferences_path: PathBuf,
    messages: Mutex<Vec<Value>>,
    sessions: Mutex<HashMap<String, String>>,
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
            settings: AppSettings::default(),
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

fn core_command(
    app: &AppHandle,
    entrypoint: &str,
    arguments: Vec<OsString>,
) -> Result<ShellCommand, String> {
    let command = if cfg!(debug_assertions) || env::var_os("SLEIPNIR_PYTHON").is_some() {
        let mut command = app.shell().command(python_executable());
        let module = match entrypoint {
            "gui" => "sleipnir.gui",
            "agent" => "sleipnir.gui_agent",
            _ => "sleipnir.cli",
        };
        command = command.args(["-m", module]);
        command.args(arguments)
    } else {
        let mut command = app
            .shell()
            .sidecar("sleipnir-core")
            .map_err(|error| format!("resolve bundled Sleipnir core: {error}"))?;
        if entrypoint != "cli" {
            command = command.arg(entrypoint);
        }
        command.args(arguments)
    };
    Ok(command)
}

async fn run_core(
    app: &AppHandle,
    entrypoint: &str,
    arguments: Vec<OsString>,
) -> Result<CoreOutput, String> {
    let output = core_command(app, entrypoint, arguments)?
        .output()
        .await
        .map_err(|error| format!("start local Sleipnir core: {error}"))?;
    Ok(CoreOutput {
        success: output.status.success(),
        stdout: output.stdout,
        stderr: output.stderr,
    })
}

async fn run_core_with_stdin(
    app: &AppHandle,
    entrypoint: &str,
    arguments: Vec<OsString>,
    input: &[u8],
) -> Result<CoreOutput, String> {
    let (mut receiver, mut child) = core_command(app, entrypoint, arguments)?
        .spawn()
        .map_err(|error| format!("start local Sleipnir core: {error}"))?;
    child
        .write(input)
        .map_err(|error| format!("send instruction to local core: {error}"))?;
    drop(child);
    let mut code = None;
    let mut stdout = Vec::new();
    let mut stderr = Vec::new();
    while let Some(event) = receiver.recv().await {
        match event {
            CommandEvent::Stdout(line) => {
                stdout.extend(line);
                stdout.push(b'\n');
            }
            CommandEvent::Stderr(line) => {
                stderr.extend(line);
                stderr.push(b'\n');
            }
            CommandEvent::Terminated(payload) => code = payload.code,
            CommandEvent::Error(error) => stderr.extend(error.as_bytes()),
            _ => {}
        }
        if stdout.len() + stderr.len() > 16 * 1024 * 1024 {
            return Err("local agent response exceeded 16 MiB".into());
        }
    }
    Ok(CoreOutput {
        success: code == Some(0),
        stdout,
        stderr,
    })
}

async fn core_snapshot(app: &AppHandle, run_root: &Path) -> Result<Value, String> {
    let output = run_core(
        app,
        "gui",
        vec![
            "snapshot".into(),
            "--run-root".into(),
            run_root.as_os_str().to_owned(),
        ],
    )
    .await?;
    if !output.success {
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
async fn load_dashboard(app: AppHandle, state: State<'_, DesktopState>) -> Result<Value, String> {
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    let listening = *state.listening.lock().map_err(|_| "voice lock poisoned")?;
    let mut snapshot = core_snapshot(&app, &preferences.run_root).await?;
    snapshot["voice"] = json!({
        "phase": if listening { "armed" } else { "off" },
        "heard": "",
        "level": 0.0,
        "privacyLabel": if listening { "Wake phrase stays on this device" } else { "Microphone is off" },
        "settings": preferences.voice,
    });
    snapshot["settings"] = serde_json::to_value(preferences.settings)
        .map_err(|error| format!("encode desktop settings: {error}"))?;
    snapshot["messages"] = Value::Array(
        state
            .messages
            .lock()
            .map_err(|_| "message lock poisoned")?
            .clone(),
    );
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
fn set_app_settings(settings: AppSettings, state: State<'_, DesktopState>) -> Result<(), String> {
    if !matches!(
        settings.color_scheme.as_str(),
        "orbit" | "index" | "glasshouse"
    ) {
        return Err("unknown color scheme".into());
    }
    if !matches!(settings.permission_mode.as_str(), "ask" | "always") {
        return Err("unknown permission mode".into());
    }
    let variable_is_valid = |name: &str| {
        !name.is_empty()
            && name.len() <= 100
            && name.chars().all(|character| {
                character.is_ascii_uppercase() || character.is_ascii_digit() || character == '_'
            })
    };
    if ![
        &settings.provider_env.openrouter,
        &settings.provider_env.gemini,
        &settings.provider_env.nvidia,
    ]
    .into_iter()
    .all(|name| variable_is_valid(name))
    {
        return Err(
            "provider key variable names must use uppercase letters, digits, and underscores"
                .into(),
        );
    }
    let mut preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?;
    preferences.settings = settings;
    persist_preferences(&state.preferences_path, &preferences)
}

#[tauri::command]
async fn send_message(
    app: AppHandle,
    text: String,
    route: Option<String>,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    if text.trim().is_empty() {
        return Ok(());
    }
    let selected = route.unwrap_or_else(|| "ambient".into());
    if !matches!(selected.as_str(), "ambient" | "claude" | "codex") {
        return Err("unknown instruction route".into());
    }
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    let config_dir = state
        .preferences_path
        .parent()
        .ok_or("invalid desktop config directory")?
        .to_path_buf();
    let mut arguments = vec![
        "--workspace".into(),
        preferences.run_root.as_os_str().to_owned(),
        "--route".into(),
        selected.clone().into(),
        "--permission-mode".into(),
        preferences.settings.permission_mode.clone().into(),
        "--history".into(),
        config_dir.join("history.enc.jsonl").into_os_string(),
        "--history-key".into(),
        config_dir.join("history.key").into_os_string(),
        "--openrouter-env".into(),
        preferences.settings.provider_env.openrouter.clone().into(),
        "--gemini-env".into(),
        preferences.settings.provider_env.gemini.clone().into(),
        "--nvidia-env".into(),
        preferences.settings.provider_env.nvidia.clone().into(),
    ];
    if let Some(session_id) = state
        .sessions
        .lock()
        .map_err(|_| "session lock poisoned")?
        .get(&selected)
        .cloned()
    {
        arguments.extend(["--session-id".into(), session_id.into()]);
    }
    let output = run_core_with_stdin(&app, "agent", arguments, text.as_bytes()).await?;
    let result: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("decode local agent response: {error}"))?;
    if !output.success || result["status"] == "error" {
        return Err(result["text"]
            .as_str()
            .unwrap_or("local agent failed")
            .to_owned());
    }
    if let Some(session_id) = result["sessionId"].as_str() {
        state
            .sessions
            .lock()
            .map_err(|_| "session lock poisoned")?
            .insert(selected.clone(), session_id.into());
    }
    let mut messages = state.messages.lock().map_err(|_| "message lock poisoned")?;
    let next = messages.len() + 1;
    messages.push(json!({"id": format!("native-{next}"), "at": "now", "role": "operator", "text": text, "route": "conversation"}));
    messages.push(json!({"id": format!("native-{}", next + 1), "at": "now", "role": "sleipnir", "text": result["text"], "route": result["route"]}));
    Ok(())
}

#[tauri::command]
fn start_project(goal: String) -> Result<(), String> {
    if goal.trim().is_empty() {
        return Err("project goal cannot be empty".into());
    }
    Err("Project creation is not connected to the native agent service yet.".into())
}

#[tauri::command]
async fn review_item(
    app: AppHandle,
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
            let output = run_core(
                &app,
                "cli",
                vec![
                    "--run-root".into(),
                    root.as_os_str().to_owned(),
                    "apply-revision".into(),
                    proposal.as_os_str().to_owned(),
                ],
            )
            .await?;
            if output.success {
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
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            let config_dir = app.path().app_config_dir()?;
            let preferences_path = config_dir.join("preferences.json");
            app.manage(DesktopState {
                preferences: Mutex::new(load_preferences(&preferences_path)),
                listening: Mutex::new(false),
                preferences_path,
                messages: Mutex::new(Vec::new()),
                sessions: Mutex::new(HashMap::new()),
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
            set_app_settings,
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
