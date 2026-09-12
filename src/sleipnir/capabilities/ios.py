"""Linux/Windows-native iOS development through xtool and SwiftPM."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sleipnir.capabilities import audit


class IOSCapabilityError(RuntimeError):
    """The requested iOS operation is unavailable or malformed."""


@dataclass(frozen=True, slots=True)
class IOSProbe:
    system: str
    xtool: str | None
    swift: str | None
    package_manifest: bool
    xtool_config: bool
    sdk_installed: bool
    notes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(
            self.xtool
            and self.swift
            and self.package_manifest
            and self.xtool_config
            and self.sdk_installed
        )


def probe(root: Path | None = None) -> IOSProbe:
    """Inspect prerequisites without downloading SDKs or contacting Apple.

    ``root`` resolves when called, never at import: a default of ``Path.cwd()``
    is evaluated once when the module loads, so a long-lived process — the
    console, which can move its run root with ``/run-root`` — would keep
    answering about whatever directory it started in.
    """
    root = (Path.cwd() if root is None else root).resolve()
    xtool = shutil.which("xtool")
    swift = shutil.which("swift")
    package_manifest = (root / "Package.swift").is_file()
    xtool_config = (root / "xtool.yml").is_file()
    sdk_installed = False
    if xtool is not None:
        try:
            status = subprocess.run(
                [xtool, "sdk", "status"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
            sdk_installed = status.returncode == 0
        except (OSError, subprocess.SubprocessError):
            sdk_installed = False
    notes: list[str] = []
    if not xtool_config:
        notes.append(f"missing {root / 'xtool.yml'} (xtool project configuration)")
    if not package_manifest:
        notes.append(f"missing {root / 'Package.swift'} (SwiftPM manifest)")
    if xtool is None:
        notes.append("xtool is not on PATH; install it from https://xtool.sh")
    if swift is None:
        notes.append("Swift is not on PATH")
    if xtool is not None and not sdk_installed:
        notes.append("Darwin Swift SDK is not installed; run `sleipnir ios setup`")
    return IOSProbe(
        system=platform.system(),
        xtool=xtool,
        swift=swift,
        package_manifest=package_manifest,
        xtool_config=xtool_config,
        sdk_installed=sdk_installed,
        notes=tuple(notes),
    )


def argv(
    action: str,
    extra: Sequence[str] = (),
    *,
    executable: str = "xtool",
) -> list[str]:
    """Translate Sleipnir's stable surface to xtool's current CLI."""
    commands = {
        "setup": ["setup"],
        "auth": ["auth", "status"] if not extra else ["auth"],
        "logout": ["auth", "logout"],
        # `xtool sdk list` does not exist; the real verbs are install / remove
        # / build / status. Verified against xtool 1.19.0 --help.
        "sdk": ["sdk", "status"] if not extra else ["sdk"],
        "sdk-remove": ["sdk", "remove"],
        "new": ["new"],
        "build": ["dev", "build"],
        # An IPA that is not signed cannot be installed or submitted. xtool's
        # --ipa and --sign flags are independent in 1.19.0.
        "ipa": ["dev", "build", "--sign", "--ipa"],
        # SideStore, AltStore and TrollStore re-sign with the operator's own
        # Apple ID on the device. Signing here would need Apple Developer
        # authentication we may not have, and the signature would be thrown
        # away by the installer regardless.
        "ipa-unsigned": ["dev", "build", "--ipa"],
        "run": ["dev", "run"],
        "xcodeproj": ["dev", "generate-xcode-project"],
        "devices": ["devices"],
        "install": ["install"],
        "uninstall": ["uninstall"],
        "launch": ["launch"],
    }
    if action not in commands:
        raise IOSCapabilityError(f"unknown iOS action {action!r}")
    argv = [executable, *commands[action], *extra]
    # `xtool devices` defaults to --wait, so with no device attached it blocks
    # forever rather than reporting an empty list. An operator who genuinely
    # wants to wait can still pass --wait through `extra`.
    if action == "devices" and not any(arg in {"--wait", "--no-wait"} for arg in extra):
        argv.append("--no-wait")
    return argv


def run(
    action: str,
    *,
    root: Path,
    extra: Sequence[str] = (),
    executable: str | None = None,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    """Run xtool directly (never through a shell) in an explicit project root."""
    root = root.resolve()
    if not root.is_dir():
        raise IOSCapabilityError(f"iOS project root is not a directory: {root}")
    tool = executable or shutil.which("xtool")
    if tool is None:
        raise IOSCapabilityError("xtool is not on PATH; install it from https://xtool.sh")
    if action == "xcodeproj" and platform.system() == "Linux":
        # xtool 1.19.0 documents this subcommand as a no-op on Linux. Reporting
        # success would be worse than an honest platform boundary.
        raise IOSCapabilityError(
            "xtool's generate-xcode-project command does nothing on Linux; "
            "Sleipnir supports building the SwiftPM iOS app here, not opening Xcode projects"
        )
    if action in {"build", "ipa", "ipa-unsigned", "run", "xcodeproj"}:
        missing = [name for name in ("Package.swift", "xtool.yml") if not (root / name).is_file()]
        if missing:
            raise IOSCapabilityError(
                f"{root} is not an xtool SwiftPM app; missing {', '.join(missing)}"
            )
    audit.record("ios.xtool", {"action": action, "project": str(root), "arg_count": len(extra)})
    # xtool is SwiftNIO-based and registers stdin with epoll. A tool subprocess
    # inherits /dev/null, which epoll_ctl rejects with EPERM, and xtool aborts
    # with an unsymbolicated 20-frame stack trace that looks nothing like the
    # cause. Measured on xtool 1.19.0.
    #
    # A real terminal is both pollable and the only case where xtool's own
    # prompts are answerable, so it is inherited. Everything else gets a pipe,
    # which is pollable and reaches xtool as an immediate EOF.
    interactive = False
    try:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        interactive = False
    result = run(
        argv(action, extra, executable=tool),
        cwd=str(root),
        check=False,
        stdin=None if interactive else subprocess.PIPE,
    )
    return int(result.returncode)


__all__ = ["IOSCapabilityError", "IOSProbe", "argv", "probe", "run"]
