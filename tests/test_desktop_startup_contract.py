"""Startup-order gate: every window must be created after app state is managed.

A window declared in ``tauri.conf.json`` is created during ``Builder::build()``,
which runs before the ``setup`` hook.  Its webview then invokes commands against
state that ``app.manage()`` has not registered yet, and every command taking
``State<'_, DesktopState>`` fails with "state not managed for field `state`".
The user-visible symptom is a permanent "Core unavailable." screen on a machine
whose core is perfectly healthy, so the failure looks like a broken sidecar and
sends anyone debugging it in the wrong direction.

The fix is ordering: declare no windows in the config and build them inside
``setup`` after ``manage``.  Ordering is not self-documenting -- re-adding one
window to the config silently reintroduces the bug -- so it is asserted here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DESKTOP = Path(__file__).resolve().parent.parent / "desktop"
CONFIG = DESKTOP / "src-tauri" / "tauri.conf.json"
LIB = DESKTOP / "src-tauri" / "src" / "lib.rs"

pytestmark = pytest.mark.skipif(
    not CONFIG.is_file() or not LIB.is_file(),
    reason="desktop crate is not present in this checkout",
)


def test_config_declares_no_windows() -> None:
    """Config-declared windows load before `setup` can manage state."""
    windows = json.loads(CONFIG.read_text(encoding="utf-8"))["app"]["windows"]
    assert windows == [], (
        "tauri.conf.json declares windows, so their webviews invoke commands "
        "before setup() calls app.manage(). Build them in setup() instead."
    )


def test_windows_are_built_after_state_is_managed() -> None:
    """`WebviewWindowBuilder` must not run before `app.manage`."""
    source = LIB.read_text(encoding="utf-8")
    managed = source.index("app.manage(")
    builds = [match.start() for match in re.finditer(r"WebviewWindowBuilder::new", source)]
    assert builds, "no window is built in Rust; the app would start with no window"
    assert all(position > managed for position in builds), (
        "a window is built before app.manage(), so its first command can race "
        "state registration"
    )


def test_every_labelled_window_still_exists() -> None:
    """Moving windows into Rust must not silently drop one.

    `emit_to("orb", ...)` and `get_webview_window("main")` fail quietly against a
    label nothing creates, which would leave the voice orb permanently dead.
    """
    source = LIB.read_text(encoding="utf-8")
    built = set(re.findall(r'WebviewWindowBuilder::new\(\s*app,\s*"([^"]+)"', source))
    assert {"main", "orb"} <= built, f"missing window labels: {{'main', 'orb'}} - {built}"
