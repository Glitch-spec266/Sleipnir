"""Symlink-safe opens must work on every supported platform, not just POSIX.

``O_NOFOLLOW`` and ``O_DIRECTORY`` do not exist in Windows Python, so a bare
``os.O_NOFOLLOW`` raises ``AttributeError`` at import-of-use time rather than
failing a security check.  The harness crashed on the first artifact it wrote:

    File "sleipnir/artifacts.py", line 190, in write_text
    AttributeError: module 'os' has no attribute 'O_DIRECTORY'

The guard those flags provide must survive the port.  A Windows build that
simply drops them would follow a junction out of the workspace -- and a
junction needs no privilege and no Developer Mode to create, so it is the
likely attack shape on a stock install.  These tests assert both halves: the
write works, and it still refuses a redirected path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sleipnir import platform
from sleipnir.artifacts import AttemptWorkspace, WorkspaceCollisionError
from sleipnir.capabilities import audit


def _link_or_skip(link: Path, target: Path) -> None:
    """Create a symlink, or skip when this OS/user cannot make one.

    Unprivileged Windows without Developer Mode refuses ``symlink_to``; a
    directory junction is the privilege-free equivalent and is what
    ``is_reparse_point`` exists to catch.
    """
    try:
        link.symlink_to(target)
        return
    except (OSError, NotImplementedError):
        pass
    if platform.IS_WINDOWS and target.is_dir():
        import subprocess

        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
        )
        if result.returncode == 0:
            return
    pytest.skip("this user cannot create a link of the required kind")


def _workspace(root: Path) -> AttemptWorkspace:
    workspace = AttemptWorkspace(run_root=root, task_id="t1", attempt=1)
    workspace.dir.mkdir(parents=True)
    return workspace


def test_write_text_writes_a_regular_file(tmp_path: Path) -> None:
    """The crash that made the orchestrator unusable on Windows."""
    workspace = _workspace(tmp_path)
    workspace.write_text("outcome.json", '{"ok": true}')
    assert (workspace.dir / "outcome.json").read_text(encoding="utf-8") == '{"ok": true}'


def test_write_text_overwrites_in_place(tmp_path: Path) -> None:
    """O_TRUNC semantics: a second write must not leave the first one's tail."""
    workspace = _workspace(tmp_path)
    workspace.write_text("outcome.json", "a long first value")
    workspace.write_text("outcome.json", "short")
    assert (workspace.dir / "outcome.json").read_text(encoding="utf-8") == "short"


def test_write_text_refuses_a_link_planted_by_the_worker(tmp_path: Path) -> None:
    """The reason the flags are there: a provider writes inside the workspace."""
    workspace = _workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    _link_or_skip(workspace.dir / "outcome.json", outside)

    with pytest.raises(WorkspaceCollisionError):
        workspace.write_text("outcome.json", "redirected")
    assert outside.read_text(encoding="utf-8") == "original"


def test_write_text_refuses_a_workspace_that_is_a_link(tmp_path: Path) -> None:
    """A redirected workspace directory must not be written through either."""
    real = tmp_path / "real"
    real.mkdir()
    workspace = AttemptWorkspace(run_root=tmp_path, task_id="t2", attempt=1)
    workspace.dir.parent.mkdir(parents=True, exist_ok=True)
    _link_or_skip(workspace.dir, real)

    with pytest.raises(WorkspaceCollisionError):
        workspace.write_text("outcome.json", "redirected")
    assert not (real / "outcome.json").exists()


def test_audit_record_appends(tmp_path: Path) -> None:
    """`capabilities.audit` used the same POSIX-only flag."""
    log = tmp_path / "audit" / "capabilities.jsonl"
    audit.record("test-action", {"detail": "value"}, log=log)
    audit.record("second-action", None, log=log)
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert "test-action" in lines[0]


def test_audit_record_refuses_a_linked_log(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text("", encoding="utf-8")
    log_dir = tmp_path / "audit"
    log_dir.mkdir()
    _link_or_skip(log_dir / "capabilities.jsonl", outside)

    with pytest.raises(OSError):
        audit.record("test-action", None, log=log_dir / "capabilities.jsonl")
    assert outside.read_text(encoding="utf-8") == ""


def test_platform_exposes_a_symlink_safe_open() -> None:
    """The helper the four call sites share, rather than four local guards."""
    assert hasattr(platform, "open_no_follow")
    assert not hasattr(os, "O_NOFOLLOW") or platform.IS_WINDOWS is False
