"""Input contracts are enforced as filesystem security boundaries."""

from __future__ import annotations

import pytest
from conftest import make_junction, requires_junction, requires_symlink
from test_schema import make_task

from sleipnir import platform
from sleipnir.artifacts import AttemptWorkspace, WorkspaceCollisionError
from sleipnir.context import resolve_inputs
from sleipnir.schema import ArtifactRef, InputContract


@requires_symlink
def test_repository_file_symlink_cannot_escape_the_run_root(tmp_path):
    run_root = tmp_path / "run"
    run_root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("DO-NOT-EXFILTRATE")
    (run_root / "linked.txt").symlink_to(secret)
    task = make_task("consumer", inputs=InputContract(files=["linked.txt"]))

    resolved = resolve_inputs(
        task,
        goal="Build safely.",
        run_root=run_root,
        summaries={},
        artifact_dir_for=lambda _: None,
    )
    assert "DO-NOT-EXFILTRATE" not in resolved.prompt
    assert "file:linked.txt" in resolved.missing


@requires_symlink
def test_dependency_artifact_symlink_cannot_escape_its_attempt(tmp_path):
    artifact_dir = tmp_path / "producer"
    artifact_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("DO-NOT-EXFILTRATE")
    (artifact_dir / "out.py").symlink_to(secret)
    task = make_task(
        "consumer",
        deps=["producer"],
        inputs=InputContract(
            artifacts=[ArtifactRef(
                task_id="producer",
                path="out.py",
                reason="The full implementation is required.",
            )]
        ),
    )

    resolved = resolve_inputs(
        task,
        goal="Build safely.",
        run_root=tmp_path,
        summaries={},
        artifact_dir_for=lambda _: artifact_dir,
    )
    assert "DO-NOT-EXFILTRATE" not in resolved.prompt
    assert "artifact:producer/out.py" in resolved.missing


def test_a_declared_dependency_artifact_is_staged_and_referenced_not_inlined(tmp_path):
    """A staged dependency is available by path without paying to paste it twice.

    Live, 2026-08-26: a planned test task declared the library task's module,
    received its source inline, wrote `import roman` — and pytest could not
    find `roman` because nothing put the file in the workspace. An acceptance
    command that executes a dependency's output needs the file, not a listing.
    """
    artifact_dir = tmp_path / "producer"
    artifact_dir.mkdir()
    # write_bytes, not write_text: staging reads the file as raw bytes (see
    # AttemptWorkspace.stage_inputs), and write_text's default newline
    # translation turns "\n" into "\r\n" on Windows -- a real byte-count
    # mismatch (11 vs. 10) that has nothing to do with the behaviour this
    # test checks.
    (artifact_dir / "roman.py").write_bytes(b"VALUE = 4\n")
    task = make_task(
        "consumer",
        deps=["producer"],
        inputs=InputContract(
            artifacts=[ArtifactRef(
                task_id="producer",
                path="roman.py",
                reason="The tests import and execute this module.",
            )]
        ),
    )

    resolved = resolve_inputs(
        task,
        goal="Build safely.",
        run_root=tmp_path,
        summaries={},
        artifact_dir_for=lambda _: artifact_dir,
    )

    assert [(src.name, dest) for src, dest, _ in resolved.staged] == [("roman.py", "roman.py")]
    assert "`roman.py`" in resolved.prompt
    assert "VALUE = 4" not in resolved.prompt
    assert resolved.total_bytes == len("VALUE = 4\n".encode())


@requires_symlink
def test_a_symlinked_dependency_artifact_is_never_staged(tmp_path):
    artifact_dir = tmp_path / "producer"
    artifact_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("DO-NOT-EXFILTRATE")
    (artifact_dir / "out.py").symlink_to(secret)
    task = make_task(
        "consumer",
        deps=["producer"],
        inputs=InputContract(
            artifacts=[ArtifactRef(
                task_id="producer",
                path="out.py",
                reason="The full implementation is required.",
            )]
        ),
    )

    resolved = resolve_inputs(
        task,
        goal="Build safely.",
        run_root=tmp_path,
        summaries={},
        artifact_dir_for=lambda _: artifact_dir,
    )
    assert resolved.staged == []


def test_staged_artifact_is_capped_at_its_declared_input_budget(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "producer"
    artifact_dir.mkdir()
    (artifact_dir / "large.txt").write_bytes(b"0123456789")
    task = make_task(
        "consumer",
        deps=["producer"],
        inputs=InputContract(
            artifacts=[ArtifactRef(
                task_id="producer",
                path="large.txt",
                reason="The consumer needs a bounded sample of this input.",
                max_bytes=4,
            )]
        ),
    )

    resolved = resolve_inputs(
        task,
        goal="Build safely.",
        run_root=tmp_path,
        summaries={},
        artifact_dir_for=lambda _: artifact_dir,
    )
    workspace = AttemptWorkspace(tmp_path, task.id, 1)
    workspace.prepare_fresh()

    def whole_file_read_is_forbidden(_path):
        raise AssertionError("staging must read only the declared prefix")

    # Slicing a whole-file read still produces the right output, but defeats
    # the bounded input contract for a large dependency artifact.
    monkeypatch.setattr(type(artifact_dir / "large.txt"), "read_bytes", whole_file_read_is_forbidden)
    workspace.stage_inputs(resolved.staged)

    with (workspace.dir / "large.txt").open("rb") as handle:
        assert handle.read() == b"0123"
    assert resolved.total_bytes == 4


def test_a_dependency_is_not_staged_over_this_task_s_own_output(tmp_path):
    """Otherwise the input and the work would be the same file.

    `collect_outputs` decides whether a task produced anything by looking at
    the declared path. Staging a dependency there makes it present before the
    worker starts, so an attempt that produced nothing would still look done.
    """
    artifact_dir = tmp_path / "producer"
    artifact_dir.mkdir()
    (artifact_dir / "out.py").write_text("VALUE = 4\n")
    task = make_task(
        "consumer",
        deps=["producer"],
        inputs=InputContract(
            artifacts=[ArtifactRef(
                task_id="producer",
                path="out.py",
                reason="This task rewrites the module in place.",
            )]
        ),
    )

    resolved = resolve_inputs(
        task,
        goal="Build safely.",
        run_root=tmp_path,
        summaries={},
        artifact_dir_for=lambda _: artifact_dir,
    )

    assert resolved.staged == []
    assert "VALUE = 4" in resolved.prompt   # still readable, just not on disk


@requires_junction
def test_a_junction_is_a_reparse_point_even_though_it_is_not_a_symlink(tmp_path):
    """The single fact the whole junction defence rests on.

    ``Path.is_symlink()`` is False for a junction, so the pre-port containment
    checks would have walked straight through one. Pinned here because the
    regression is silent: every other test in this file would still pass.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / "link"
    make_junction(link, outside)

    assert not link.is_symlink()
    assert platform.is_reparse_point(link)


@requires_junction
def test_attempt_workspace_junction_is_refused_before_anything_is_written(tmp_path):
    """``prepare()`` is where the reparse check is the *only* guard.

    The containment walk in ``contained_regular_file`` is backed up by a
    ``resolve()`` comparison, so a junction there is caught twice. Here it is
    not: if this check missed a junction, every artifact, stdout and summary
    of the attempt would be written straight into the junction's target.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = AttemptWorkspace(tmp_path, "a", 1)
    workspace.dir.parent.mkdir(parents=True)
    make_junction(workspace.dir, outside)

    with pytest.raises(WorkspaceCollisionError, match="unsafe attempt workspace"):
        workspace.prepare()
    assert list(outside.iterdir()) == []


@requires_junction
def test_attempt_workspace_parent_junction_is_refused(tmp_path):
    """Same gap one level up: the per-task directory, not the attempt's own."""
    outside = tmp_path / "outside"
    outside.mkdir()
    workspace = AttemptWorkspace(tmp_path, "a", 1)
    (tmp_path / "artifacts").mkdir()
    make_junction(workspace.dir.parent, outside)

    with pytest.raises(WorkspaceCollisionError, match="symlink"):
        workspace.prepare()
    assert list(outside.iterdir()) == []
