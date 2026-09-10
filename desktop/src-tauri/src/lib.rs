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
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent};
use tauri_plugin_autostart::ManagerExt as AutoStartExt;
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::process::{Command as ShellCommand, CommandEvent};
use tauri_plugin_shell::ShellExt;

struct CoreOutput {
    success: bool,
    stdout: Vec<u8>,
    stderr: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
#[serde(rename_all = "camelCase")]
struct VoiceSettings {
    wake_name: String,
    local_wake: bool,
    listening_enabled: bool,
    start_at_login: bool,
    push_to_talk_shortcut: String,
    transcription: String,
    ambient_provider: String,
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
            // Ambient listening is the product: a wake word that is off until
            // the operator finds a toggle is a wake word that does not exist.
            listening_enabled: true,
            start_at_login: false,
            push_to_talk_shortcut: "CommandOrControl+Shift+Space".into(),
            transcription: "local".into(),
            ambient_provider: "auto".into(),
            response_model: "auto".into(),
            escalation: "automatic".into(),
            voice_provider: "system".into(),
            voice_id: "system-natural".into(),
            accent: "neutral".into(),
            interruptible: true,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(default)]
#[serde(rename_all = "camelCase")]
struct Preferences {
    run_root: PathBuf,
    voice: VoiceSettings,
    settings: AppSettings,
    sessions: HashMap<String, String>,
}

impl Default for Preferences {
    fn default() -> Self {
        Self {
            run_root: initial_run_root(),
            voice: VoiceSettings::default(),
            settings: AppSettings::default(),
            sessions: HashMap::new(),
        }
    }
}

struct DesktopState {
    preferences: Mutex<Preferences>,
    listening: Mutex<bool>,
    push_to_talk: Mutex<bool>,
    preferences_path: PathBuf,
    messages: Mutex<Vec<Value>>,
    project_starting: Mutex<bool>,
    history_loaded: Mutex<bool>,
    voice_listener: Mutex<Option<CommandChild>>,
    turn_in_flight: Mutex<bool>,
    /// The action the previous turn stopped on, awaiting one spoken "yes".
    ///
    /// Answering a form takes a dozen consequential actions, so asking per
    /// action made the task unreachable rather than merely guarded. The grant
    /// covers the next turn only, and never covers credentials.
    pending_approval: Mutex<Option<String>>,
}

/// Holds the microphone shut and the turn slot claimed for one exchange.
///
/// Both the wake listener and the push-to-talk orb reach `send_message`, and
/// neither knew about the other: a second wake phrase -- including Sleipnir
/// hearing its own reply -- started a second agent, and both spoke at once.
/// Releasing on `Drop` is what makes an early error return safe.
struct TurnGuard {
    app: AppHandle,
}

impl TurnGuard {
    fn claim(app: &AppHandle) -> Option<Self> {
        let state = app.try_state::<DesktopState>()?;
        {
            let mut busy = state.turn_in_flight.lock().ok()?;
            if *busy {
                return None;
            }
            *busy = true;
        }
        set_listener_muted(&state, true);
        Some(Self { app: app.clone() })
    }
}

impl Drop for TurnGuard {
    fn drop(&mut self) {
        if let Some(state) = self.app.try_state::<DesktopState>() {
            set_listener_muted(&state, false);
            if let Ok(mut busy) = state.turn_in_flight.lock() {
                *busy = false;
            }
        }
    }
}

/// Tell the wake listener to stop consuming audio, or to resume.
///
/// Piper renders through the speakers while `parecord` is still capturing, so
/// without this Sleipnir wakes itself on its own reply.
fn set_listener_muted(state: &DesktopState, muted: bool) {
    let line: &[u8] = if muted {
        b"{\"type\":\"mute\"}\n"
    } else {
        b"{\"type\":\"unmute\"}\n"
    };
    if let Ok(mut listener) = state.voice_listener.lock() {
        if let Some(child) = listener.as_mut() {
            let _ = child.write(line);
        }
    }
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
        .unwrap_or_default()
}

/// The containment check, not `is_symlink()`.
///
/// On POSIX this *is* `is_symlink()`, so substituting it never narrows the
/// guard.  On Windows a junction reports `is_symlink()` false and would be
/// walked straight through.  Mirrors `sleipnir.platform.is_reparse_point`.
#[cfg(windows)]
fn is_reparse_point(path: &Path) -> bool {
    use std::os::windows::fs::MetadataExt;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0)
        .unwrap_or(false)
}

#[cfg(not(windows))]
fn is_reparse_point(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
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

fn command_available(name: &str) -> bool {
    env::var_os("PATH").is_some_and(|paths| {
        env::split_paths(&paths).any(|directory| {
            let candidate = directory.join(name);
            if candidate.is_file() {
                return true;
            }
            cfg!(windows)
                && env::var_os("PATHEXT").is_some_and(|extensions| {
                    extensions
                        .to_string_lossy()
                        .split(';')
                        .any(|extension| directory.join(format!("{name}{extension}")).is_file())
                })
        })
    })
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
            "transcribe" => "sleipnir.voice.transcription",
            "speak" => "sleipnir.voice.synthesis",
            "listen" => "sleipnir.voice.listener",
            "project" => "sleipnir.gui_project",
            "history" => "sleipnir.gui_history",
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

fn stop_voice_listener(state: &DesktopState) {
    if let Ok(mut listener) = state.voice_listener.lock() {
        if let Some(child) = listener.take() {
            let _ = child.kill();
        }
    }
}

fn start_voice_listener(app: &AppHandle, state: &DesktopState) -> Result<(), String> {
    stop_voice_listener(state);
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    if !preferences.voice.listening_enabled || !preferences.voice.local_wake {
        return Ok(());
    }
    let arguments = vec!["--wake-name".into(), preferences.voice.wake_name.into()];
    let (mut receiver, child) = core_command(app, "listen", arguments)?
        .spawn()
        .map_err(|error| format!("start local wake listener: {error}"))?;
    *state
        .voice_listener
        .lock()
        .map_err(|_| "voice listener lock poisoned")? = Some(child);

    let listener_app = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = receiver.recv().await {
            match event {
                CommandEvent::Stdout(line) => {
                    if let Ok(payload) = serde_json::from_slice::<Value>(&line) {
                        match payload["type"].as_str() {
                            Some("ready") => {
                                let _ = listener_app.emit_to("orb", "voice-phase", "armed");
                            }
                            Some("command") => {
                                if let Some(text) = payload["text"].as_str() {
                                    let _ = listener_app.emit_to("orb", "voice-phase", "thinking");
                                    let _ = listener_app.emit_to("main", "voice-instruction", text);
                                }
                            }
                            // A warning is how the listener says it heard
                            // something it could not use -- a clipping mic, a
                            // failed transcription. Dropping it leaves the
                            // operator with a machine that appears deaf and
                            // says nothing about why.
                            Some("warning") => {
                                if let Some(text) = payload["text"].as_str() {
                                    append_message(&listener_app, "sleipnir", text.to_owned(), "voice-warning");
                                }
                            }
                            Some("error") => {
                                let detail = payload["text"]
                                    .as_str()
                                    .unwrap_or("local wake listener stopped")
                                    .to_owned();
                                append_message(&listener_app, "sleipnir", detail, "voice-error");
                                let _ = listener_app.emit_to("orb", "voice-phase", "error");
                            }
                            _ => {}
                        }
                    }
                }
                CommandEvent::Error(error) => {
                    append_message(&listener_app, "sleipnir", error, "voice-error");
                    let _ = listener_app.emit_to("orb", "voice-phase", "error");
                }
                CommandEvent::Terminated(_) => break,
                _ => {}
            }
        }
    });
    Ok(())
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

async fn encrypted_history(app: &AppHandle, preferences_path: &Path) -> Result<Vec<Value>, String> {
    let config_dir = preferences_path
        .parent()
        .ok_or("invalid desktop config directory")?;
    let output = run_core(
        app,
        "history",
        vec![
            "--history".into(),
            config_dir.join("history.enc.jsonl").into_os_string(),
            "--history-key".into(),
            config_dir.join("history.key").into_os_string(),
        ],
    )
    .await?;
    let result: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("decode encrypted history: {error}"))?;
    if !output.success || result["status"] == "error" {
        return Err(result["text"]
            .as_str()
            .unwrap_or("encrypted history could not be opened")
            .to_owned());
    }
    let entries = result["entries"]
        .as_array()
        .ok_or("encrypted history returned no entries")?;
    Ok(entries
        .iter()
        .enumerate()
        .filter_map(|(index, entry)| {
            let role = entry["role"].as_str()?;
            let text = entry["text"].as_str()?;
            if !matches!(role, "operator" | "sleipnir" | "tool") {
                return None;
            }
            Some(json!({
                "id": format!("history-{}", index + 1),
                "at": entry["at"].as_str().unwrap_or("earlier"),
                "role": role,
                "text": text,
                "route": entry["route"].as_str().unwrap_or("conversation"),
            }))
        })
        .collect())
}

#[tauri::command]
async fn load_dashboard(app: AppHandle, state: State<'_, DesktopState>) -> Result<Value, String> {
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    let listening = *state.listening.lock().map_err(|_| "voice lock poisoned")?;
    let push_to_talk = *state
        .push_to_talk
        .lock()
        .map_err(|_| "push-to-talk lock poisoned")?;
    let mut snapshot = core_snapshot(&app, &preferences.run_root).await?;
    snapshot["voice"] = json!({
        "phase": if push_to_talk { "hearing" } else if listening { "armed" } else { "off" },
        "heard": "",
        "level": 0.0,
        "privacyLabel": if listening { "Wake phrase stays on this device" } else { "Microphone is off" },
        "settings": preferences.voice,
    });
    snapshot["settings"] = serde_json::to_value(&preferences.settings)
        .map_err(|error| format!("encode desktop settings: {error}"))?;
    let activated = |name: &str| env::var_os(name).is_some_and(|value| !value.is_empty());
    snapshot["providers"] = json!({
        "ollama": command_available("ollama"),
        "openrouter": activated(&preferences.settings.provider_env.openrouter),
        "gemini": activated(&preferences.settings.provider_env.gemini),
        "nvidia": activated(&preferences.settings.provider_env.nvidia),
    });
    let should_load_history = {
        let mut loaded = state
            .history_loaded
            .lock()
            .map_err(|_| "history state lock poisoned")?;
        let should_load = !*loaded;
        *loaded = true;
        should_load
    };
    if should_load_history {
        match encrypted_history(&app, &state.preferences_path).await {
            Ok(entries) => {
                *state.messages.lock().map_err(|_| "message lock poisoned")? = entries;
            }
            Err(error) => append_message(&app, "sleipnir", error, "history-error"),
        }
    }
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
    if !candidate.is_dir() {
        return Err(format!("{} is not a directory", candidate.display()));
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
    app: AppHandle,
    settings: VoiceSettings,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    let name = settings.wake_name.trim();
    if !(2..=32).contains(&name.chars().count()) {
        return Err("wake name must contain 2 to 32 characters".into());
    }
    if !matches!(settings.transcription.as_str(), "local" | "gemini") {
        return Err("unknown transcription mode".into());
    }
    if !matches!(
        settings.ambient_provider.as_str(),
        "auto" | "ollama" | "gemini" | "openrouter" | "nvidia-nim"
    ) {
        return Err("unknown ambient provider".into());
    }
    if !matches!(
        settings.voice_provider.as_str(),
        "system" | "gemini" | "openrouter"
    ) {
        return Err("unknown voice provider".into());
    }
    let should_listen = settings.local_wake && settings.listening_enabled;
    let mut preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?;
    let previous = preferences.voice.clone();
    if previous.push_to_talk_shortcut != settings.push_to_talk_shortcut {
        app.global_shortcut()
            .unregister(previous.push_to_talk_shortcut.as_str())
            .map_err(|error| format!("release old push-to-talk shortcut: {error}"))?;
        if let Err(error) = app
            .global_shortcut()
            .register(settings.push_to_talk_shortcut.as_str())
        {
            let _ = app
                .global_shortcut()
                .register(previous.push_to_talk_shortcut.as_str());
            return Err(format!("register push-to-talk shortcut: {error}"));
        }
    }
    let startup_result = if settings.start_at_login {
        app.autolaunch().enable()
    } else {
        app.autolaunch().disable()
    };
    if let Err(error) = startup_result {
        if previous.push_to_talk_shortcut != settings.push_to_talk_shortcut {
            let _ = app
                .global_shortcut()
                .unregister(settings.push_to_talk_shortcut.as_str());
            let _ = app
                .global_shortcut()
                .register(previous.push_to_talk_shortcut.as_str());
        }
        return Err(format!("update start-at-login: {error}"));
    }
    preferences.voice = settings;
    persist_preferences(&state.preferences_path, &preferences)?;
    drop(preferences);
    *state.listening.lock().map_err(|_| "voice lock poisoned")? = should_listen;
    start_voice_listener(&app, &state)
}

#[tauri::command]
fn set_listening(
    app: AppHandle,
    enabled: bool,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    *state.listening.lock().map_err(|_| "voice lock poisoned")? = enabled;
    let mut preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?;
    preferences.voice.listening_enabled = enabled;
    persist_preferences(&state.preferences_path, &preferences)?;
    drop(preferences);
    if enabled {
        start_voice_listener(&app, &state)?;
    } else {
        stop_voice_listener(&state);
    }
    app.emit_to("orb", "listening-changed", enabled)
        .map_err(|error| format!("update voice listener: {error}"))
}

#[tauri::command]
async fn transcribe_audio(
    app: AppHandle,
    audio: Vec<u8>,
    mime_type: String,
    state: State<'_, DesktopState>,
) -> Result<String, String> {
    if audio.is_empty() {
        return Err("recording is empty".into());
    }
    if audio.len() > 12 * 1024 * 1024 {
        return Err("recording exceeds the 12 MiB safety limit".into());
    }
    if !mime_type.starts_with("audio/") || mime_type.len() > 100 {
        return Err("unsupported recording content type".into());
    }
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    let arguments = vec![
        "--mode".into(),
        preferences.voice.transcription.into(),
        "--mime-type".into(),
        mime_type.into(),
        "--gemini-env".into(),
        preferences.settings.provider_env.gemini.into(),
    ];
    let output = run_core_with_stdin(&app, "transcribe", arguments, &audio).await?;
    let result: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("decode local transcription response: {error}"))?;
    if !output.success || result["status"] == "error" {
        return Err(result["text"]
            .as_str()
            .unwrap_or("transcription failed")
            .to_owned());
    }
    result["text"]
        .as_str()
        .map(str::to_owned)
        .ok_or_else(|| "transcription returned no command".into())
}

#[tauri::command]
async fn speak_text(
    app: AppHandle,
    text: String,
    state: State<'_, DesktopState>,
) -> Result<Value, String> {
    let clean = text.trim();
    if clean.is_empty() || clean.len() > 64 * 1024 {
        return Err("speech text is empty or too large".into());
    }
    let preferences = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .clone();
    if !matches!(
        preferences.voice.voice_provider.as_str(),
        "system" | "gemini" | "openrouter"
    ) {
        return Err("selected voice provider is not available".into());
    }
    let arguments = vec![
        "--provider".into(),
        preferences.voice.voice_provider.into(),
        "--preset".into(),
        preferences.voice.voice_id.into(),
        "--openrouter-env".into(),
        preferences.settings.provider_env.openrouter.into(),
        "--gemini-env".into(),
        preferences.settings.provider_env.gemini.into(),
    ];
    let output = run_core_with_stdin(&app, "speak", arguments, clean.as_bytes()).await?;
    let result: Value = serde_json::from_slice(&output.stdout)
        .map_err(|error| format!("decode speech response: {error}"))?;
    if !output.success || result["status"] == "error" {
        return Err(result["text"]
            .as_str()
            .unwrap_or("speech synthesis failed")
            .to_owned());
    }
    Ok(result["audio"].clone())
}

#[tauri::command]
fn handoff_instruction(app: AppHandle, text: String) -> Result<(), String> {
    let clean = text.trim();
    if clean.is_empty() || clean.len() > 1_048_576 {
        return Err("voice instruction is empty or too large".into());
    }
    show_main(&app);
    app.emit_to("main", "voice-instruction", clean)
        .map_err(|error| format!("handoff voice instruction: {error}"))
}

#[tauri::command]
fn clear_history(state: State<'_, DesktopState>) -> Result<(), String> {
    let config_dir = state
        .preferences_path
        .parent()
        .ok_or("invalid desktop config directory")?;
    let history = config_dir.join("history.enc.jsonl");
    if is_reparse_point(&history) {
        return Err("refusing to clear a linked history file".into());
    }
    if history.exists() {
        fs::remove_file(&history).map_err(|error| format!("clear encrypted history: {error}"))?;
    }
    state
        .messages
        .lock()
        .map_err(|_| "message lock poisoned")?
        .clear();
    *state
        .history_loaded
        .lock()
        .map_err(|_| "history state lock poisoned")? = true;
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
) -> Result<Value, String> {
    if text.trim().is_empty() {
        return Err("instruction cannot be empty".into());
    }
    let _turn = TurnGuard::claim(&app).ok_or("Sleipnir is still working on the previous request")?;
    // A pending approval turns the operator's next word into a decision about
    // the task Sleipnir stopped on, rather than a fresh instruction.
    let awaiting = state
        .pending_approval
        .lock()
        .map_err(|_| "approval lock poisoned")?
        .clone();
    let mut task_grant = false;
    let mut text = text;
    if let Some(action) = awaiting {
        *state
            .pending_approval
            .lock()
            .map_err(|_| "approval lock poisoned")? = None;
        match approval_answer(&text) {
            Some(true) => {
                task_grant = true;
                text = action;
            }
            Some(false) => {
                return Ok(json!({
                    "status": "complete",
                    "text": "Understood, I have left it alone.",
                    "route": "ambient",
                }));
            }
            None => {}
        }
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
        "--ambient-provider".into(),
        preferences.voice.ambient_provider.clone().into(),
    ];
    if task_grant {
        arguments.push("--task-grant".into());
    }
    if selected == "ambient"
        && !matches!(
            preferences.voice.response_model.trim(),
            "" | "auto" | "openrouter/auto"
        )
    {
        arguments.extend([
            "--model".into(),
            preferences.voice.response_model.clone().into(),
        ]);
    }
    if let Some(session_id) = preferences.sessions.get(&selected).cloned() {
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
    if let Some(pending) = result["approval"].as_str() {
        // Remember the instruction, not the tool name: re-issuing has to ask
        // for the same task again, with the grant attached.
        *state
            .pending_approval
            .lock()
            .map_err(|_| "approval lock poisoned")? = Some(text.clone());
        let _ = pending;
    }
    if let Some(session_id) = result["sessionId"].as_str() {
        let mut persisted = state
            .preferences
            .lock()
            .map_err(|_| "settings lock poisoned")?;
        persisted
            .sessions
            .insert(selected.clone(), session_id.into());
        persist_preferences(&state.preferences_path, &persisted)?;
    }
    let mut messages = state.messages.lock().map_err(|_| "message lock poisoned")?;
    let next = messages.len() + 1;
    messages.push(json!({"id": format!("native-{next}"), "at": "now", "role": "operator", "text": text, "route": "conversation"}));
    messages.push(json!({"id": format!("native-{}", next + 1), "at": "now", "role": "sleipnir", "text": result["text"], "route": result["route"]}));
    Ok(result)
}

/// Classify a spoken reply to an approval question.
///
/// Anything that is neither a yes nor a no is a new instruction, not a silent
/// refusal: guessing either way would be worse than asking again.
fn approval_answer(text: &str) -> Option<bool> {
    let clean = text.trim().trim_matches(|c: char| c.is_ascii_punctuation()).to_lowercase();
    const YES: [&str; 10] = ["yes", "yeah", "yep", "yup", "sure", "ok", "okay", "go ahead", "do it", "please do"];
    const NO: [&str; 8] = ["no", "nope", "nah", "stop", "cancel", "don't", "do not", "never mind"];
    if YES.contains(&clean.as_str()) {
        return Some(true);
    }
    if NO.contains(&clean.as_str()) {
        return Some(false);
    }
    None
}

fn append_message(app: &AppHandle, role: &str, text: String, route: &str) {
    if let Some(state) = app.try_state::<DesktopState>() {
        if let Ok(mut messages) = state.messages.lock() {
            let next = messages.len() + 1;
            messages.push(json!({
                "id": format!("native-{next}"),
                "at": "now",
                "role": role,
                "text": text,
                "route": route,
            }));
        }
    }
}

#[tauri::command]
fn start_project(
    app: AppHandle,
    goal: String,
    state: State<'_, DesktopState>,
) -> Result<(), String> {
    let clean = goal.trim().to_owned();
    if clean.is_empty() {
        return Err("project goal cannot be empty".into());
    }
    if clean.len() > 64 * 1024 {
        return Err("project goal exceeds the 64 KiB safety limit".into());
    }
    let root = state
        .preferences
        .lock()
        .map_err(|_| "settings lock poisoned")?
        .run_root
        .clone();
    if root.join("plan.json").exists() {
        return Err("this workspace already has a plan; choose another directory".into());
    }
    let mut starting = state
        .project_starting
        .lock()
        .map_err(|_| "project lock poisoned")?;
    if *starting {
        return Err("a project is already being planned".into());
    }
    *starting = true;
    drop(starting);
    append_message(&app, "operator", clean.clone(), "project");
    append_message(
        &app,
        "sleipnir",
        "Planning the project in the background.".into(),
        "planner",
    );

    let task_app = app.clone();
    tauri::async_runtime::spawn(async move {
        let plan_output = run_core_with_stdin(
            &task_app,
            "project",
            vec!["--workspace".into(), root.as_os_str().to_owned()],
            clean.as_bytes(),
        )
        .await;
        let planned = match plan_output {
            Ok(output) => match serde_json::from_slice::<Value>(&output.stdout) {
                Ok(result) if output.success && result["status"] != "error" => {
                    append_message(
                        &task_app,
                        "sleipnir",
                        result["text"]
                            .as_str()
                            .unwrap_or("Project plan created.")
                            .to_owned(),
                        "planner",
                    );
                    true
                }
                Ok(result) => {
                    append_message(
                        &task_app,
                        "sleipnir",
                        result["text"]
                            .as_str()
                            .unwrap_or("Project planning failed.")
                            .to_owned(),
                        "error",
                    );
                    false
                }
                Err(error) => {
                    append_message(
                        &task_app,
                        "sleipnir",
                        format!("Could not decode planner response: {error}"),
                        "error",
                    );
                    false
                }
            },
            Err(error) => {
                append_message(&task_app, "sleipnir", error, "error");
                false
            }
        };
        let _ = task_app.emit_to("main", "dashboard-changed", ());
        if planned {
            append_message(
                &task_app,
                "sleipnir",
                "Plan ready. Routed execution is running in the background.".into(),
                "orchestrator",
            );
            let _ = task_app.emit_to("main", "dashboard-changed", ());
            match run_core(
                &task_app,
                "cli",
                vec![
                    "--run-root".into(),
                    root.as_os_str().to_owned(),
                    "orchestrate".into(),
                ],
            )
            .await
            {
                Ok(output) if output.success => append_message(
                    &task_app,
                    "sleipnir",
                    "Project workflow finished. Review the verified output.".into(),
                    "orchestrator",
                ),
                Ok(output) => append_message(
                    &task_app,
                    "sleipnir",
                    String::from_utf8_lossy(&output.stderr).trim().to_owned(),
                    "error",
                ),
                Err(error) => append_message(&task_app, "sleipnir", error, "error"),
            }
        }
        if let Some(state) = task_app.try_state::<DesktopState>() {
            if let Ok(mut starting) = state.project_starting.lock() {
                *starting = false;
            }
        }
        let _ = task_app.emit_to("main", "dashboard-changed", ());
    });
    Ok(())
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

fn show_orb(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("orb") {
        let _ = window.show();
    }
}

#[tauri::command]
fn show_main_window(app: AppHandle) {
    show_main(&app);
    if let Some(window) = app.get_webview_window("orb") {
        let _ = window.hide();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .arg("--background")
                .build(),
        )
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    let active = event.state == ShortcutState::Pressed;
                    if let Some(state) = app.try_state::<DesktopState>() {
                        if let Ok(mut push_to_talk) = state.push_to_talk.lock() {
                            *push_to_talk = active;
                        }
                        if active {
                            stop_voice_listener(&state);
                        } else if state
                            .listening
                            .lock()
                            .map(|listening| *listening)
                            .unwrap_or(false)
                        {
                            let _ = start_voice_listener(app, &state);
                        }
                    }
                    if active {
                        show_orb(app);
                    }
                    let _ = app.emit_to("orb", "voice-activity", active);
                    if !active {
                        if let Some(window) = app.get_webview_window("orb") {
                            let _ = window.hide();
                        }
                    }
                })
                .build(),
        )
        .setup(|app| {
            let config_dir = app.path().app_config_dir()?;
            let preferences_path = config_dir.join("preferences.json");
            let preferences = load_preferences(&preferences_path);
            let shortcut = preferences.voice.push_to_talk_shortcut.clone();
            let start_at_login = preferences.voice.start_at_login;
            let listening_enabled = preferences.voice.listening_enabled;
            app.manage(DesktopState {
                preferences: Mutex::new(preferences),
                listening: Mutex::new(listening_enabled),
                push_to_talk: Mutex::new(false),
                preferences_path,
                messages: Mutex::new(Vec::new()),
                project_starting: Mutex::new(false),
                history_loaded: Mutex::new(false),
                voice_listener: Mutex::new(None),
                turn_in_flight: Mutex::new(false),
                pending_approval: Mutex::new(None),
            });
            let _ = app.global_shortcut().register(shortcut.as_str());
            let _ = if start_at_login {
                app.autolaunch().enable()
            } else {
                app.autolaunch().disable()
            };
            if listening_enabled {
                let state = app.state::<DesktopState>();
                if let Err(error) = start_voice_listener(app.handle(), &state) {
                    append_message(app.handle(), "sleipnir", error, "voice-error");
                }
            }
            if env::args().any(|argument| argument == "--background") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }

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
            show_main_window,
            transcribe_audio,
            handoff_instruction,
            speak_text,
            clear_history,
        ])
        .build(tauri::generate_context!())
        .expect("failed to build Sleipnir desktop");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            if let Some(state) = app.try_state::<DesktopState>() {
                stop_voice_listener(&state);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_an_unambiguous_answer_decides_a_pending_approval() {
        for yes in ["yes", "Yes.", "go ahead", "DO IT!", "sure"] {
            assert_eq!(approval_answer(yes), Some(true), "{yes}");
        }
        for no in ["no", "Nope", "cancel", "never mind", "stop."] {
            assert_eq!(approval_answer(no), Some(false), "{no}");
        }
        // Anything else is a fresh instruction. Reading it as consent would
        // act without permission; reading it as refusal would drop the work.
        for other in ["what is on my screen", "yes but only the first one", ""] {
            assert_eq!(approval_answer(other), None, "{other}");
        }
    }

    #[test]
    fn defaults_keep_wake_local_and_secrets_out_of_preferences() {
        let encoded = serde_json::to_string(&VoiceSettings::default()).unwrap();
        assert!(encoded.contains("localWake"));
        assert!(!encoded.to_lowercase().contains("api_key"));
        assert!(!encoded.to_lowercase().contains("token"));
    }

    #[test]
    fn provider_sessions_survive_a_preferences_round_trip() {
        let mut preferences = Preferences::default();
        preferences
            .sessions
            .insert("claude".into(), "session-abc".into());

        let encoded = serde_json::to_string(&preferences).unwrap();
        let decoded: Preferences = serde_json::from_str(&encoded).unwrap();

        assert_eq!(
            decoded.sessions.get("claude").map(String::as_str),
            Some("session-abc")
        );
    }

    #[test]
    fn preferences_written_before_sessions_existed_still_load() {
        // The field is `#[serde(default)]`; an older file must not fail to parse
        // and strand the operator's run root and provider settings.
        let legacy = r#"{"runRoot":"/tmp/legacy"}"#;
        let decoded: Preferences = serde_json::from_str(legacy).unwrap();

        assert_eq!(decoded.run_root, PathBuf::from("/tmp/legacy"));
        assert!(decoded.sessions.is_empty());
    }

    #[test]
    fn preferences_carry_session_handles_and_no_conversation_content() {
        // Structural, not a substring scan: `settings.transcription` is a
        // legitimate field naming the STT engine, and a naive search for
        // "transcript" matches it.  What must be pinned is the shape — only
        // these four keys, so a field carrying conversation content cannot be
        // added to ordinary preferences without this failing.
        let mut preferences = Preferences::default();
        preferences
            .sessions
            .insert("codex".into(), "session-xyz".into());

        let encoded = serde_json::to_value(&preferences).unwrap();
        let mut keys: Vec<&str> = encoded
            .as_object()
            .expect("preferences serialise to an object")
            .keys()
            .map(String::as_str)
            .collect();
        keys.sort_unstable();

        assert_eq!(keys, ["runRoot", "sessions", "settings", "voice"]);

        // A session id is a handle to a provider conversation, never its text.
        let sessions = encoded["sessions"].as_object().unwrap();
        assert_eq!(sessions.len(), 1);
        assert_eq!(sessions["codex"], json!("session-xyz"));
    }
}
