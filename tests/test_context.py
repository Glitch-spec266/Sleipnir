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
