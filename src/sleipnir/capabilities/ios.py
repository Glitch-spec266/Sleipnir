"""Linux/Windows-native iOS development through xtool and SwiftPM."""

from __future__ import annotations

import platform
import shutil
import subprocess
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
    notes: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return bool(self.xtool and self.swift and self.package_manifest and self.xtool_config)


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
    notes: list[str] = []
    if not xtool_config:
        notes.append(f"missing {root / 'xtool.yml'} (xtool project configuration)")
    if not package_manifest:
        notes.append(f"missing {root / 'Package.swift'} (SwiftPM manifest)")
    if xtool is None:
        notes.append("xtool is not on PATH; install it from https://xtool.sh")
    if swift is None:
        notes.append("Swift is not on PATH")
    return IOSProbe(
        system=platform.system(),
        xtool=xtool,
        swift=swift,
        package_manifest=package_manifest,
        xtool_config=xtool_config,
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
        "sdk": ["sdk", "list"] if not extra else ["sdk"],
        "new": ["new"],
        "build": ["dev", "build"],
        "ipa": ["dev", "build", "--ipa"],
        "run": ["dev", "run"],
        "devices": ["devices"],
        "install": ["install"],
        "launch": ["launch"],
    }
    if action not in commands:
        raise IOSCapabilityError(f"unknown iOS action {action!r}")
    return [executable, *commands[action], *extra]


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
    # install and launch act on the built product of the project in `root`,
    # so they need the same manifest as the commands that produce it.
    if action in {"build", "ipa", "run", "install", "launch"}:
        missing = [name for name in ("Package.swift", "xtool.yml") if not (root / name).is_file()]
        if missing:
            raise IOSCapabilityError(
                f"{root} is not an xtool SwiftPM app; missing {', '.join(missing)}"
            )
    audit.record("ios.xtool", {"action": action, "project": str(root), "arg_count": len(extra)})
    result = run(argv(action, extra, executable=tool), cwd=str(root), check=False)
    return int(result.returncode)


__all__ = ["IOSCapabilityError", "IOSProbe", "argv", "probe", "run"]
