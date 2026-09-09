# Sleipnir — Windows 11 verification report

Handoff branch: `handoff-win11-testing`
Revision tested: `72e12db859bee335b35b0af463c1ecf9630f5166` (detached, clean)
Date of run: 2026-09-08

**Verdict: the automated gate does not pass.** 114–115 of 593 tests fail on native
Windows 11. Every failure traces to one of four causes, and three of the four are
single-root-cause defects in the port itself rather than broad breakage. The
Windows-specific machinery the handoff called highest-risk — job objects, NTFS
junction containment, CTRL_BREAK/taskkill, the run-lock offset, GDI capture,
SendInput encoding — is sound and passes. What is missing is a Windows
implementation of the "do not follow a symlink when opening a file" primitive,
which four modules call directly through POSIX `os.open` flags instead of through
the platform seam.

Nothing in the repository was modified. No fixes have been applied.

---

## 1. Environment

| Fact | Value |
| --- | --- |
| OS | Microsoft Windows 11 Home, build 26200 (10.0.26200) |
| Architecture | AMD64 |
| Python | 3.13.14 — Microsoft Store distribution (`PythonSoftwareFoundation.Python.3.13`) |
| `py` launcher | Not installed; used `python` per the handoff's fallback |
| Git | 2.54.0.windows.1, with `sh` at `C:\Program Files\Git\usr\bin\sh.EXE` |
| Terminal host | Windows Terminal |
| Elevation | Session is **elevated**; a second restricted-token run was made (see §3) |
| Developer Mode | Off |
| Antivirus / EDR | Windows Defender only |
| Monitors | Single display, 1536×960 logical / 1920×1200 physical |
| Display scale | 125% (AppliedDPI 120) |

Deviations from the handoff worth stating plainly:

- The handoff asks for a **non-administrator PowerShell first**. This session runs
  elevated. A non-elevated run was reproduced with a restricted token
  (`runas /trustlevel:0x20000`) and is reported separately in §3; it is a close
  approximation of a standard user, not a true separate non-admin logon.
- `py -3.12` is unavailable, so the bare `python` fallback was used. That resolved
  to Microsoft Store Python, which turned out to matter — see W5.

---

## 2. Automated gate results

Three configurations were run. All three collected 593 tests.

| Configuration | Failed | Passed | Skipped | Duration |
| --- | --- | --- | --- | --- |
| A — elevated, Store-Python venv (`.venv\Scripts\python.exe`) | 115 | 475 | 3 | 19.0 s |
| B — elevated, base interpreter (no venv redirector) | 114 | 476 | 3 | 8.2 s |
| C — restricted token (non-admin), base interpreter | 115 | 468 | 10 | 10.6 s |

Failure causes, configuration B:

| Count | Cause |
| --- | --- |
| ~87 | `AttributeError: module 'os' has no attribute 'O_DIRECTORY'` |
| 25 | `AttributeError: module 'os' has no attribute 'O_NOFOLLOW'` |
| 2 | `KeyError: 'start_new_session'` |
| 1 | Windows path-casing comparison in a test |

Other gate commands:

| Command | Result |
| --- | --- |
| `pytest --collect-only -q` | exit 0, 593 tests collected |
| `python -m compileall -q src\sleipnir` | exit 0, silent |
| `python -m pip check` | exit 0, "No broken requirements found." |
| `git diff --check` | exit 0, silent |
| `git status --short` | only untracked evidence files; no source file modified |
| `sleipnir --help` | exit 0, starts cleanly, imports no POSIX-only module |
| `sleipnir doctor` | exit 1 — see W6 |

### What passed, and matters

These are the contracts the handoff named as highest-risk. They hold.

- **NTFS junction containment.** All `requires_junction` tests pass, non-elevated
  and with Developer Mode off. Junction creation needed neither.
- **Path containment generally.** Drive-letter, UNC, backslash-traversal and
  workspace-escape tests pass.
- **`CREATE_NEW_PROCESS_GROUP` / `CTRL_BREAK_EVENT` / `taskkill /F /T`.** All
  process-group and tree-kill tests pass.
- **Run-lock offset.** The `msvcrt` mandatory-lock-at-offset trick works; another
  process can still read the owner PID while the lock is held.
- **Windows job object hard-parent-kill drill.**
  `test_windows_job_guard_terminates_after_hard_parent_kill` **passes** on a normal
  interpreter, elevated and non-elevated. It fails only under the Store-Python venv,
  for reasons that are not the job object's — see W5.
- **Input encoding contracts.** Unicode including astral characters, reversed chord
  release, extended keys, virtual-desktop coordinates, wheel direction, GDI BGRA
  conversion and PNG encoding all pass.
- **Shell selection.** `doctor` reports `posix`, and the seam resolves
  `C:\Program Files\Git\usr\bin\sh.EXE`. The repository's POSIX acceptance-command
  dialect is preserved. No fallback to `cmd.exe`, no warning.

---

## 3. Non-administrator run

Under a restricted token: 115 failed, 468 passed, **10 skipped**.

The seven additional skips are the symlink tests, with an honest reason string:
"this account cannot create symlinks (needs Windows Developer Mode or elevation)".
That is the behaviour the handoff predicted and is correct.

Four tests, however, create symlinks **without** the `requires_symlink` guard, so on
a stock non-elevated account they hard-fail instead of skipping — see W4.

`test_windows_job_guard_terminates_after_hard_parent_kill` passed non-elevated. No
Windows behaviour observed in this run required administrator rights.

---

## 4. Findings

Ordered by impact. IDs are for reference in follow-up work.

### W1 — `artifacts.py` opens workspace files with POSIX-only flags (≈87 failures)

`src/sleipnir/artifacts.py:190` calls
`os.open(self.dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)`, and line 194 uses
`os.O_NOFOLLOW` with `dir_fd=`. Neither constant exists on Windows, and
`os.supports_dir_fd` is the empty set there, so the directory-relative approach is
unavailable outright.

Impact: every attempt-workspace write fails. That is the executor's central write
path, so it takes down most of `test_executor.py`, `test_cli.py`, `test_adapters.py`
and `test_orchestrator.py` with it.

This is not a "loses its safety property on Windows" bug — it raises, so it fails
closed. But the harness cannot write a single attempt outcome on Windows.

Suggested direction: add a no-follow open to the platform seam
(`platform/__init__.py` already owns `is_reparse_point`, which is the Windows half of
the same idea). On Windows the equivalent is `CreateFileW` with
`FILE_FLAG_OPEN_REPARSE_POINT` (plus `FILE_FLAG_BACKUP_SEMANTICS` for a directory
handle), or an ordinary open followed by a reparse-point and containment check on the
resulting handle. The `dir_fd` relative-open needs a different shape on Windows
regardless.

### W2 — `capabilities/audit.py` crashes on every audited action (25 failures, and every `sleipnir computer` command)

`src/sleipnir/capabilities/audit.py:60` uses `os.O_NOFOLLOW` when appending to the
audit log. `audit.record()` runs after the action, so on Windows the action succeeds
and then the process dies with a traceback and a non-zero exit.

Observed live, not only in tests:

```
sleipnir computer screenshot evidence\desktop.png
  → evidence\desktop.png written correctly (1920×1200, valid PNG)
  → then: AttributeError: module 'os' has no attribute 'O_NOFOLLOW'
  → exit 1, and the path is never printed
```

The same happens for `computer type`, `computer copy`, `computer paste` and the
browser and secret-handoff capabilities. Every host-control command on Windows
reports failure after succeeding. This is the inverse of the failure mode the handoff
warned about, and it is worse for scripting: a caller checking the exit code will
conclude nothing happened.

Two more call sites share the cause: `capabilities/browser.py:70` and
`capabilities/handoff.py:94`.

### W3 — Two console tests assert a POSIX-only spawn kwarg (2 failures)

`tests/test_console.py:351` and `:650` assert
`calls[0]["kwargs"]["start_new_session"] is True`. The source is correct — `chat.py`
and `process.py` both spread `platform.CHILD_SPAWN_KWARGS`, which is
`{"creationflags": CREATE_NEW_PROCESS_GROUP}` on Windows. Only the tests hardcode the
Linux value.

`test_spawn_requests_its_own_group` in `tests/test_process.py` already shows the
portable form: iterate `platform.CHILD_SPAWN_KWARGS` and compare each entry.

### W4 — Four symlink tests are missing the `requires_symlink` guard (non-admin only)

These call `Path.symlink_to()` unguarded and so fail with a privilege error on a
stock non-elevated account rather than skipping:

- `tests/test_capabilities.py:338` `test_clipboard_image_rejects_a_symlinked_destination`
- `tests/test_capabilities.py:601` `test_browser_pid_is_published_without_following_an_old_symlink`
- `tests/test_capabilities.py:639` `test_browser_rejects_a_symlinked_profile_before_launch`
- `tests/test_executor.py:583` `test_workspace_claim_rejects_artifacts_symlink_before_external_mutation`

`requires_symlink` already exists in `tests/conftest.py` and is applied to seven
sibling tests. This is a gating omission, not a behaviour bug.

### W5 — Microsoft Store Python breaks the parent-death guard, silently

This is the most interesting finding, and the reason configuration A differs from B.

A venv created from Microsoft Store Python gets a `Scripts\python.exe` that is a
**redirector**: it launches the real interpreter as a separate child process. Measured
directly — `Popen.pid = 29588` while the child's own `os.getpid()` reports `26048`.

Consequences on that interpreter:

- Every pid Sleipnir records for a child is the redirector's, one hop above the real
  process.
- `process_guard.py`'s `os.getppid()` watch therefore watches the wrong process, and
  the guard itself is never a member of the job object it opened. Verified: the
  provider grandchild *is* in the job; the guard is not.
- `test_windows_job_guard_terminates_after_hard_parent_kill` fails. Re-run on the base
  interpreter, with pid identity intact, it passes.

Two separate things follow. First, the handoff should require a python.org (or
`py` launcher) interpreter and say that Store Python is not a valid host for this
gate — because a `python --version` fallback on a default Windows 11 box lands on it,
exactly as it did here. Second, and more importantly for the product: on that
interpreter the Windows parent-death guarantee degrades to nothing and says nothing.
`process_guard.py` already treats a failed job open or assign as "no isolation for
this dispatch rather than a refusal to run it" — but it does not check the
`AssignProcessToJobObject` return value at all, so there is no signal even in
principle. Checking it and emitting one honest warning would turn a silent loss of a
kill guarantee into a visible one.

### W6 — `doctor` recommends a Linux package on Windows, and always reports "incomplete"

`sleipnir doctor` output on this machine:

```
  session                      windows
  input injection (SendInput)  yes
  interactive desktop session  yes
  input daemon running         n/a (none needed)
  screenshot                   gdi (BitBlt)
  browser control              NO
  shell for plan checks        posix
  ! Codex's worker sandbox is kernel-enforced on Linux and macOS but not here; ...
  ! playwright is not installed — run `sleipnir setup`
  ! wl-clipboard is not installed — run `sleipnir setup`

host control: incomplete — run `sleipnir setup`
```

`src/sleipnir/capabilities/clipboard.py` is Wayland-only: `available()` is
`shutil.which("wl-paste") is not None`, with no Windows or macOS backend and no
platform seam. So on Windows:

- `clipboard.available()` is permanently False,
- `cli.py:1045` tells a Windows user to install `wl-clipboard`, a Wayland tool,
- `cli.py:1046` folds that into `ready`, so `doctor` can never say "ready" and always
  exits 1.

`sleipnir setup` on Windows (`_windows_setup_steps`) offers no clipboard step, so
following the advice is impossible.

Separately, the handoff's acceptance criteria ask `doctor` to report **whether the
process is elevated**. It does not. Everything else the criteria list — Windows
identification, selected shell, GDI capture, honest warnings — is present and correct.

### W7 — A test compares Windows paths as case-sensitive strings (1 failure, environment-dependent)

`tests/test_process.py:177` compares
`str(Path(__file__).parents[1] / "src" / "sleipnir" / "process_guard.py")` against the
argv entry, which the source produces via `Path(...).resolve()`. On Windows `resolve()`
returns the true on-disk casing, so the two differ whenever the invoking path's casing
differs from disk:

```
- ...C--Users-USER-downloads-sleipnir-main\...\process_guard.py
+ ...C--Users-USER-Downloads-Sleipnir-main\...\process_guard.py
```

It passed in the restricted-token run, where the path was supplied with matching
casing — which is exactly what makes it a portability bug rather than a real defect:
it fails or passes on the casing of the string the user typed. `os.path.normcase`, or
resolving both sides, fixes it.

---

## 5. Manual desktop smoke tests

### Screen capture — passes

`sleipnir computer screenshot` produced a valid 1920×1200 PNG of the whole virtual
desktop: correct orientation, correct color channels (BGRA→RGB conversion is right —
verified against known application colors), not clipped, nothing cropped.

Worth recording: the capture is **DPI-aware**. At 125% scale the un-aware
`GetSystemMetrics(SM_CXVIRTUALSCREEN)` reports 1536×960, while Sleipnir captured the
full 1920×1200 physical desktop. That is the correct behaviour and it is easy to get
wrong. Single monitor only, so the "monitors left/above the primary" case is untested.

The command still exited 1 because of W2.

### Typing, copy and paste — not completed

I could not complete these safely and did not force them. This session drives
PowerShell as a background process, and Windows' foreground lock refused every attempt
to move focus to a scratch Notepad window — `SetForegroundWindow`, `ShowWindow` and
`WScript.Shell.AppActivate` all reported success or were ignored while Chrome remained
foreground, confirmed by reading the foreground window title back each time.

One consequence to disclose: my first typing attempt fired before I had added that
foreground check, so the string `Sleipnir --help` + newline + an emoji was delivered to
the focused Chrome window (a Google search tab) rather than to Notepad. Nothing was
destroyed and no credential field was involved, but it is a stray input event on a live
desktop and you should know it happened. Every attempt after that verified the
foreground window first and aborted rather than typing blind.

These three items therefore still need a human at the keyboard:

1. `computer type "Sleipnir --help\nUnicode: 😀"` into an empty Notepad, checking the
   exact two lines and the emoji.
2. `computer copy` / `computer paste` round trip.
3. Optional `key ctrl a`, `key home`, `click right`, `scroll 1`, `scroll -1`.

What can be stated from source and from the passing tests: the Windows chord table at
`capabilities/computer/__init__.py:102` is `{"copy": ("ctrl","c"), "paste": ("ctrl","v")}`
— correctly Windows chords, not the Linux terminal `ctrl+shift+` variants — and the
SendInput encoding tests for astral characters, chord ordering and extended keys all
pass. The mechanism is right; only the live desktop observation is missing.

### Interactive console — partially verified

Run non-interactively with stdin closed, `sleipnir` starts, enters the alternate
screen buffer and draws its frame with box-drawing characters intact — no mojibake in
the output stream, no crash entering raw console mode, no error on stderr. It then
blocks waiting for input, as expected.

Not verified, and needing a human in a real console: typed characters and Backspace,
arrow-key navigation of the command menu, Enter submitting, Ctrl+C exiting cleanly,
and terminal mode restored on exit. Legacy `conhost.exe` untested.

One small observation: with a non-tty stdin the console blocks rather than declining;
detecting that and exiting with a message would be friendlier, though it is not a
platform-gate failure.

---

## 6. Recommended order of work

Nothing below has been applied.

1. **W1 + W2 together.** They are one missing primitive. Add a no-follow open (and a
   Windows directory-handle equivalent) to `platform/`, then route `artifacts.py`,
   `capabilities/audit.py`, `capabilities/browser.py` and `capabilities/handoff.py`
   through it. This alone should clear ~112 of the ~114 failures. Fixing it at the seam
   rather than at four call sites is also what the seam's own docstring asks for.
2. **W6 clipboard.** Give `clipboard.py` a platform seam, or at minimum stop counting
   it toward `ready` on platforms with no backend and stop naming a Wayland package on
   Windows. Also add elevation to `doctor`, which the handoff's own acceptance criteria
   expect.
3. **W3, W4, W7.** Test-side portability fixes, all small, all with an existing
   in-repo pattern to copy.
4. **W5.** Check the `AssignProcessToJobObject` return value and warn once when the
   guarantee is unavailable; and amend the handoff to require a non-Store Python.
5. Re-run the gate, then have a human complete the three live desktop items and the
   real-console checks in §5.

---

## 7. Evidence

Committed alongside this report in `win11-evidence/`. The Windows username has been
replaced with `USER` throughout; nothing else was edited.

| File | Contents |
| --- | --- |
| `collect.txt` | `pytest --collect-only -q` |
| `pytest-full.txt` | full suite, configuration A |
| `pytest-basepython.txt` | full suite, configuration B |
| `nonadmin.txt` | full suite, configuration C (restricted token) |
| `pytest-windows-focus.txt` | `test_process.py test_context.py test_capabilities.py` |
| `doctor.txt` | `sleipnir doctor` |

The desktop capture is **deliberately not committed**: it shows the tester's live
desktop, including browser tabs and a taskbar clock. It stays with the tester. The log
files had the Windows username replaced with `USER`; no tokens, credentials or provider
transcripts are present in any of them, and no `.claude`, `.codex` or `.sleipnir`
content was collected.

## 8. Observed versus inferred

Observed directly: every test count, exit code and traceback above; the pid-identity
measurement for Store Python; the job-membership measurement showing the guard outside
its own job; the screenshot dimensions and DPI comparison; the `doctor` output; the
resolved `sh` path; the console's first frame.

Inferred, and stated as such: that W1 and W2 share one root cause and one fix is a
reading of the code, not a tested claim — no fix was written or run. That the Store
Python redirector is the *only* reason the job-guard test failed rests on the test
passing on the base interpreter in both elevation states, which is strong but is
one interpreter's worth of evidence. The multi-monitor capture path is untested, not
inferred to work.
