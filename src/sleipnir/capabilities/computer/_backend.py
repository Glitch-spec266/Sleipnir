"""Shared types the public API and both concrete backends agree on.

Deliberately import-free of ``__init__.py``, ``_linux.py`` and
``_windows.py``: all three of those import from here, so this has to sit
underneath them or the package would not import at all.
"""

from __future__ import annotations

from dataclasses import dataclass


class CapabilityError(RuntimeError):
    """A host capability was asked for and is genuinely unavailable.

    Raised rather than silently degraded: an agent told "click at 400,300" that
    quietly does nothing is worse than one that stops and says the pointer is
    not wired up. One class, shared by both backends, so a caller never has
    to know which platform raised it.
    """


@dataclass(frozen=True)
class Probe:
    """What this machine can actually do, for ``sleipnir doctor``.

    The field names are Linux-shaped (ydotool/uinput vocabulary) because
    that backend came first; the Windows backend repopulates the same five
    fields with its own equivalents rather than getting a parallel shape,
    so ``cmd_doctor`` needs no structural change, only platform-aware
    labels for what each field means on this host:

    * ``input_injection``  -- can the backend inject input at all
      (``ydotool`` installed / ``SendInput`` reachable)
    * ``daemon_running``   -- Linux: ``ydotoold`` is listening. Windows has
      no daemon, so this is always ``True`` (nothing to start).
    * ``screenshot_tool``  -- name of whatever will actually be invoked
    * ``uinput_writable``  -- Linux: ``/dev/uinput`` permission. Windows:
      whether ``SendInput`` has a real interactive session to inject into
      (a Session-0 service has none). Elevation is reported through
      ``notes`` instead of this field: an unelevated Sleipnir cannot reach
      an elevated window's input queue, but unelevated is the ordinary,
      unbroken state for almost every app on the desktop, so it should not
      by itself flip ``ready`` to ``False``.
    * ``session_type``     -- Linux: ``XDG_SESSION_TYPE``. Windows: a fixed
      ``"windows"``.
    """

    input_injection: bool
    daemon_running: bool
    screenshot_tool: str | None
    uinput_writable: bool
    session_type: str
    notes: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.input_injection and self.uinput_writable and bool(self.screenshot_tool)


__all__ = ["CapabilityError", "Probe"]
