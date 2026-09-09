# Windows 11 verification handoff

This branch exists to verify Sleipnir's Windows backend on real Windows 11
hardware. The merged implementation is commit `99a1097`; it passed on Linux
with 577 tests run and 16 platform-gated tests skipped, but the Windows-only
`ctypes.WinDLL`, job-object, NTFS-junction, `SendInput`, GDI, console, and shell
paths cannot be proven from Linux.

Please run the tests from a normal, **non-administrator** PowerShell first.
That is the supported everyday posture and exposes privilege assumptions. A
second elevated run is optional and must be reported separately.

## 1. Clone and prepare

Prerequisites: Windows 11 x64, Git, and Python 3.12 or 3.13. Git for Windows is
recommended because Sleipnir prefers its POSIX `sh` for acceptance commands.
Do not use WSL: these tests must see native `sys.platform == "win32"`.

```powershell
git clone https://github.com/Glitch-spec266/Sleipnir.git
Set-Location Sleipnir
git fetch origin handoff-win11-testing
git switch --detach origin/handoff-win11-testing
git rev-parse HEAD
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e . pytest
```

The revision printed by `git rev-parse HEAD` should match the tip of
`origin/handoff-win11-testing`. Keep the checkout detached and clean while
testing. Do not add API keys; the suite blocks real OAuth credential and usage
endpoint reads by default.

**Do not use Microsoft Store Python for this gate.** Install from python.org (or
use the `py` launcher, which never resolves to the Store build). A virtualenv
created from Store Python gets a `Scripts\python.exe` that re-executes the real
interpreter as a *separate child process*, so every pid the suite records for a
child names a redirector one hop above the interpreter. That makes the
parent-death drill measure the wrong process and fail as though the job object
were broken. The suite now detects this and skips
`test_windows_job_guard_terminates_after_hard_parent_kill` with an explanatory
reason rather than failing — but a run with that test skipped does not satisfy
this gate. On a default Windows 11 install, a bare `python` is exactly the Store
build, so check before you start:

```powershell
python -c "import sys; print(sys.base_prefix)"   # must not contain WindowsApps
```

If `py -3.12` is unavailable but `python --version` reports 3.12 or newer and is
not the Store build, replace it with `python`. Record `python --version`,
`git --version`, Windows
edition/build (`winver`), CPU architecture, terminal host, elevation state,
display scale, and monitor layout in the report.

## 2. Automated gate

Run each command even if an earlier one fails. Save complete, unedited output.

```powershell
& .\.venv\Scripts\python.exe -m pytest --collect-only -q | Tee-Object collect.txt
& .\.venv\Scripts\python.exe -m pytest -q -ra | Tee-Object pytest-full.txt
& .\.venv\Scripts\python.exe -m pytest -q -ra tests/test_process.py tests/test_context.py tests/test_capabilities.py | Tee-Object pytest-windows-focus.txt
& .\.venv\Scripts\python.exe -m compileall -q src\sleipnir
& .\.venv\Scripts\python.exe -m pip check
git diff --check
git status --short
& .\.venv\Scripts\sleipnir.exe --help
& .\.venv\Scripts\sleipnir.exe doctor | Tee-Object doctor.txt
```

Acceptance criteria:

- The full suite has no failures or errors. Platform-specific skips are allowed
  only when their reasons are shown by `-ra` and explained in the report.
- `test_windows_job_guard_terminates_after_hard_parent_kill` runs and passes.
- All `requires_junction` tests run and pass. NTFS junction creation should not
  require Developer Mode or elevation.
- Symlink tests may skip on a stock non-elevated machine. If Developer Mode is
  enabled, they should run and pass. Do not elevate solely to turn these skips
  into passes.
- `compileall`, `pip check`, and `git diff --check` are silent/successful.
- `git status --short` lists only the evidence text files created above (or is
  clean if output was saved elsewhere); source files must remain unchanged.
- `sleipnir --help` starts without importing POSIX-only modules.
- `doctor` identifies Windows, reports the selected shell, GDI capture, whether
  the process is elevated, and any honest warnings rather than crashing.

The highest-risk automated contracts are:

- Windows Job Object `KILL_ON_JOB_CLOSE` removes a provider subtree after its
  launcher is hard-killed.
- `CREATE_NEW_PROCESS_GROUP` and `CTRL_BREAK_EVENT` provide the graceful stop
  path; `taskkill /F /T` provides the forced tree kill.
- The run lock uses an offset beyond the PID text so mandatory `msvcrt` locking
  does not prevent another process from reading the owner PID.
- Drive-letter, UNC, backslash traversal, symlink, and NTFS-junction paths
  cannot escape the run or artifact workspace.
- Unicode input (including astral characters), reversed chord release, extended
  keys, virtual-desktop coordinates, wheel direction, GDI BGRA conversion, and
  PNG encoding preserve their cross-platform contracts.

## 3. Manual desktop smoke tests

These commands cause real keyboard/mouse input. Close sensitive applications,
open Notepad with a new empty document, keep it non-elevated, and be ready to
move focus back to PowerShell. Never test against a password field, UAC prompt,
banking app, game, or other sensitive/elevated window.

First test capture without moving focus:

```powershell
New-Item -ItemType Directory -Force evidence | Out-Null
& .\.venv\Scripts\sleipnir.exe computer screenshot evidence\desktop.png
Get-Item evidence\desktop.png | Format-List FullName,Length
```

Open `evidence\desktop.png` and verify that it is a valid, correctly oriented
capture of the entire virtual desktop. With multiple monitors, confirm that
monitors left/above the primary are included and not clipped. Repeat once at a
non-100% display scale if practical, and record the scale and monitor geometry.

For typing, run the following, immediately focus Notepad during the two-second
delay, and confirm the exact two-line result including the emoji:

```powershell
Start-Sleep -Seconds 2; & .\.venv\Scripts\sleipnir.exe computer type "Sleipnir --help`nUnicode: 😀"
```

Expected Notepad contents:

```text
Sleipnir --help
Unicode: 😀
```

Then select the text in Notepad, return to PowerShell, run the copy command with
the delay, focus Notepad, move to the end, and repeat for paste. Confirm Windows
uses `Ctrl+C` / `Ctrl+V` behavior (not the Linux terminal chords):

```powershell
Start-Sleep -Seconds 2; & .\.venv\Scripts\sleipnir.exe computer copy
Start-Sleep -Seconds 2; & .\.venv\Scripts\sleipnir.exe computer paste
```

Optionally test `key ctrl a`, `key home`, `click right`, `scroll 1`, and
`scroll -1` in a disposable Notepad document. Do not automate absolute mouse
movement unless you have recorded the virtual desktop bounds; a wrong move can
interact with the wrong monitor.

Expected limitations are not failures: `SendInput` cannot reach an elevated
target from a non-elevated Sleipnir process, cannot operate the UAC secure
desktop, and is detectable as injected input. Report any silent success claim
when ordinary Notepad receives nothing; that is a failure.

## 4. Interactive console smoke test

Run in Windows Terminal and then in legacy `conhost.exe` if available:

```powershell
& .\.venv\Scripts\sleipnir.exe
```

Verify that the UI draws without mojibake, typed characters and Backspace work,
arrow keys navigate the command menu, Enter submits, Ctrl+C exits cleanly, and
the terminal mode is restored afterward. Do not send a provider message unless
you intentionally want a live paid/subscription call; command editing and exit
are sufficient for this platform gate.

## 5. Shell behavior

Record whether `doctor` chose Git's `sh` or `cmd.exe`. With Git for Windows
installed, it should resolve `sh` and preserve the repository's POSIX-style
acceptance-command dialect. If it falls back to `cmd.exe`, preserve the exact
warning. Do not set `SLEIPNIR_SHELL` unless doing a separate, clearly labelled
override test.

## 6. Report back

Create an issue or send the maintainer one archive containing `collect.txt`,
`pytest-full.txt`, `pytest-windows-focus.txt`, `doctor.txt`, the screenshot,
and a Markdown report with:

- commit SHA and all environment facts requested in section 1;
- every command's exit code, pass/fail/skip counts, duration, and skip reasons;
- whether Developer Mode, elevation, antivirus/EDR, and multiple monitors were
  present;
- results of capture, Unicode typing, copy/paste, console input, and shell
  selection;
- exact traceback and reproduction steps for every failure;
- whether the failure repeats in a fresh non-admin PowerShell;
- a distinction between observed facts and guesses about root cause.

Before sharing, inspect all logs and the image for usernames, paths, window
contents, tokens, or other private material. Redact secrets while preserving
the technical error. Do not attach `.claude`, `.codex`, `.sleipnir`, browser
profiles, provider transcripts, or credential files.

The run is complete only when the automated gate passes and the real desktop,
console, shell-selection, junction-containment, and hard-parent-kill behaviors
have each been observed on native Windows 11.
