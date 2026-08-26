"""Input contracts are enforced as filesystem security boundaries."""

from __future__ import annotations

from test_schema import make_task

from sleipnir.context import resolve_inputs
from sleipnir.schema import ArtifactRef, InputContract


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


def test_a_declared_dependency_artifact_is_staged_into_the_workspace(tmp_path):
    """Reading it in the prompt is not enough to run it.

    Live, 2026-08-26: a planned test task declared the library task's module,
    received its source inline, wrote `import roman` — and pytest could not
    find `roman` because nothing put the file in the workspace. An acceptance
    command that executes a dependency's output needs the file, not a listing.
    """
    artifact_dir = tmp_path / "producer"
    artifact_dir.mkdir()
    (artifact_dir / "roman.py").write_text("VALUE = 4\n")
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

    assert [(src.name, dest) for src, dest in resolved.staged] == [("roman.py", "roman.py")]


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
