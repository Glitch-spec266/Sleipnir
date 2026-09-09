"""Secret-safe project planning entry point for the desktop sidecar."""

from __future__ import annotations

import io
import json
import sys
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

from sleipnir.cli import main as cli_main

MAX_GOAL_BYTES = 64 * 1024


def create_project_plan(
    goal: str,
    *,
    workspace: Path,
    runner: Callable[[list[str]], int] = cli_main,
) -> dict[str, Any]:
    clean = goal.strip()
    if not clean:
        raise ValueError("project goal cannot be empty")
    if len(clean.encode("utf-8")) > MAX_GOAL_BYTES:
        raise ValueError("project goal exceeds the 64 KiB safety limit")
    root = workspace.resolve()
    if not root.is_dir():
        raise ValueError(f"workspace does not exist: {root}")
    if (root / "plan.json").exists():
        raise ValueError("this workspace already has a plan; choose another directory")
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = runner(["--run-root", str(root), "plan", clean])
    detail = "\n".join(part for part in (stdout.getvalue().strip(), stderr.getvalue().strip()) if part)
    if code:
        raise RuntimeError(detail[-2_000:] or f"planner exited {code}")
    return {"status": "complete", "text": detail[-4_000:] or "Project plan created."}


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 2 or argv[0] != "--workspace":
        print(json.dumps({"status": "error", "text": "usage: --workspace PATH"}))
        return 2
    raw = sys.stdin.buffer.read(MAX_GOAL_BYTES + 1)
    try:
        if len(raw) > MAX_GOAL_BYTES:
            raise ValueError("project goal exceeds the 64 KiB safety limit")
        result = create_project_plan(raw.decode("utf-8"), workspace=Path(argv[1]))
    except Exception as error:  # noqa: BLE001 - native boundary returns a clean envelope
        print(json.dumps({"status": "error", "text": str(error)}))
        return 2
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["MAX_GOAL_BYTES", "create_project_plan", "main"]
