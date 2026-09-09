"""Build and target-name the standalone Python core expected by Tauri."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def host_triple() -> str:
    output = subprocess.check_output(["rustc", "-vV"], text=True)
    for line in output.splitlines():
        if line.startswith("host: "):
            return line.removeprefix("host: ").strip()
    raise RuntimeError("rustc did not report a host triple")


def main() -> int:
    desktop = Path(__file__).resolve().parents[1]
    root = desktop.parent
    build = desktop / "sidecar-build"
    destination = desktop / "src-tauri" / "binaries"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onefile",
            "--name",
            "sleipnir-core",
            "--distpath",
            str(build / "dist"),
            "--workpath",
            str(build / "work"),
            "--specpath",
            str(build),
            str(desktop / "sidecar.py"),
        ],
        cwd=root,
        check=True,
    )
    suffix = ".exe" if sys.platform == "win32" else ""
    source = build / "dist" / f"sleipnir-core{suffix}"
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"sleipnir-core-{host_triple()}{suffix}"
    shutil.copy2(source, target)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
