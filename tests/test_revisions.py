"""Plan revision application and computed blast radius."""

from __future__ import annotations

from conftest import requires_symlink
from test_executor import plan_of
from test_schema import finished, make_task

import pytest

from sleipnir.projection import fold_results
from sleipnir.revisions import RevisionError, apply_revision, persist_revision, read_staleness
from sleipnir.schema import RevisionChange, RevisionOp, TaskStatus, Tier


def test_retarget_preserves_completed_work_identity():
    plan = plan_of(make_task("a"))
    replacement = plan.by_id["a"].model_copy(update={"tier": Tier.MECHANICAL, "priority": 9})
    revised, audit = apply_revision(
        plan,
        [RevisionChange(op=RevisionOp.RETARGET_TASK, task_id="a", task=replacement)],
        reason="Move completed work to a cheaper route without invalidating it.",
        records=[finished("a", spec_hash=plan.by_id["a"].spec_hash())],
    )
    assert revised.revision == 1
    assert revised.by_id["a"].tier is Tier.MECHANICAL
    assert audit.superseded == [] and audit.staled == []


def test_respec_computes_superseded_task_and_stale_descendants():
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    replacement = plan.by_id["a"].model_copy(
        update={"description": "Implement a materially different upstream contract."}
    )
    records = [
        finished("a", spec_hash=plan.by_id["a"].spec_hash()),
        finished("b", spec_hash=plan.by_id["b"].spec_hash()),
    ]
    _, audit = apply_revision(
        plan,
        [RevisionChange(op=RevisionOp.RESPEC_TASK, task_id="a", task=replacement)],
        reason="The upstream contract was incomplete and needs a semantic correction.",
        records=records,
    )
    assert audit.superseded == ["a"]
    assert audit.staled == ["b"]


def test_retarget_refuses_a_disguised_semantic_change():
    plan = plan_of(make_task("a"))
    replacement = plan.by_id["a"].model_copy(update={"description": "Different meaning entirely."})
    with pytest.raises(RevisionError, match="routing fields only"):
        apply_revision(
            plan,
            [RevisionChange(op=RevisionOp.RETARGET_TASK, task_id="a", task=replacement)],
            reason="This incorrectly claims a semantic change is only routing.",
        )


def test_edge_change_must_leave_a_valid_dag():
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    with pytest.raises(RevisionError, match="cycle"):
        apply_revision(
            plan,
            [RevisionChange(op=RevisionOp.ADD_EDGE, task_id="a", dependency_id="b")],
            reason="This would create a cycle and must be rejected before persistence.",
        )


def test_revision_audit_drives_stale_projection_until_a_post_revision_success(tmp_path):
    plan = plan_of(make_task("a"), make_task("b", deps=["a"]))
    replacement = plan.by_id["a"].model_copy(
        update={"description": "Implement a materially different upstream contract."}
    )
    old_records = [
        finished("a", spec_hash=plan.by_id["a"].spec_hash()),
        finished("b", spec_hash=plan.by_id["b"].spec_hash()),
    ]
    revised, audit = apply_revision(
        plan,
        [RevisionChange(op=RevisionOp.RESPEC_TASK, task_id="a", task=replacement)],
        reason="The upstream contract changed and descendants require review.",
        records=old_records,
    )
    plan_path = tmp_path / "plan.json"
    revisions_path = tmp_path / "revisions.jsonl"
    persist_revision(plan_path, revisions_path, revised, audit)
    staled_at = read_staleness(revisions_path)
    assert fold_results(revised, old_records, staled_at=staled_at)["b"].status is TaskStatus.STALE

    fresh_b = finished("b", attempt=2, spec_hash=revised.by_id["b"].spec_hash())
    fresh_b.plan_revision = revised.revision
    assert (
        fold_results(revised, old_records + [fresh_b], staled_at=staled_at)["b"].status
        is TaskStatus.DONE
    )


@requires_symlink
def test_revision_persistence_refuses_a_symlinked_audit_log(tmp_path):
    plan = plan_of(make_task("a"))
    replacement = plan.by_id["a"].model_copy(update={"tier": Tier.MECHANICAL})
    revised, audit = apply_revision(
        plan,
        [RevisionChange(op=RevisionOp.RETARGET_TASK, task_id="a", task=replacement)],
        reason="Use a cheaper route without changing the task contract.",
    )
    outside = tmp_path / "outside.txt"
    outside.write_text("must stay unchanged")
    revisions = tmp_path / "revisions.jsonl"
    revisions.symlink_to(outside)
    with pytest.raises(RevisionError, match="symlinked revision log"):
        persist_revision(tmp_path / "plan.json", revisions, revised, audit)
    assert outside.read_text() == "must stay unchanged"
