"""The phase gate must stay constant-size and must not wake the brain cheaply.

Two properties carry the whole design: a verdict never grows with the number of
tasks (it is counts and failed ids only), and the brain is woken only when the
workers have genuinely stopped *and* something is wrong.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sleipnir.gate import (
    GroupState,
    escalation_changes,
    evaluate_gate,
    stronger_tier,
)
from sleipnir.projection import TaskState
from sleipnir.schema import (
    ExpectedOutput,
    OutputContract,
    OutputKind,
    Plan,
    RevisionOp,
    Task,
    TaskStatus,
    Tier,
)


def task(task_id: str, *, group: str = "core", tier: Tier = Tier.CODE, **kwargs) -> Task:
    return Task(
        id=task_id,
        description=f"do the thing called {task_id}",
        tier=tier,
        group=group,
        outputs=OutputContract(
            outputs=[
                ExpectedOutput(
                    name="out",
                    kind=OutputKind.FILE,
                    path=f"{task_id}.txt",
                    description="the produced file",
                )
            ]
        ),
        **kwargs,
    )


T0 = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def plan_of(*tasks: Task) -> Plan:
    return Plan(plan_id="p", goal="ship the thing end to end", created_at=T0, tasks=list(tasks))


def states(**pairs: TaskStatus) -> dict[str, TaskState]:
    return {
        task_id: TaskState(task_id=task_id, status=status) for task_id, status in pairs.items()
    }


# --- verdicts ------------------------------------------------------------


def test_a_group_passes_only_when_every_task_is_done():
    plan = plan_of(task("a"), task("b"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.DONE, b=TaskStatus.DONE))
    assert verdict.groups[0].state is GroupState.PASSED
    assert verdict.complete is True

    partial = evaluate_gate(plan, states(a=TaskStatus.DONE, b=TaskStatus.READY))
    assert partial.groups[0].state is GroupState.WORKING
    assert partial.complete is False


def test_one_failure_fails_the_whole_group_and_names_it():
    plan = plan_of(task("a"), task("b"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.DONE, b=TaskStatus.FAILED))
    group = verdict.groups[0]
    assert group.state is GroupState.FAILED
    assert group.failed_task_ids == ("b",)
    assert verdict.failed_groups == (group,)


def test_groups_are_scored_independently():
    plan = plan_of(
        task("a", group="auth"),
        task("b", group="auth"),
        task("c", group="billing"),
    )
    verdict = evaluate_gate(
        plan, states(a=TaskStatus.DONE, b=TaskStatus.FAILED, c=TaskStatus.DONE)
    )
    by_group = {group.group: group.state for group in verdict.groups}
    assert by_group == {"auth": GroupState.FAILED, "billing": GroupState.PASSED}
    # The passing module is not rebuilt because a sibling failed.
    assert [group.group for group in verdict.passed_groups] == ["billing"]


def test_a_skipped_task_fails_its_group_but_is_never_escalated():
    """A task skipped because its dependency failed did not lose on merit.

    Escalating it would re-route a whole downstream subtree on one upstream
    failure, spending money on models that were never the problem.
    """
    plan = plan_of(task("a"), task("b"))
    seen = {
        "a": TaskState(task_id="a", status=TaskStatus.FAILED, attempts=2),
        "b": TaskState(task_id="b", status=TaskStatus.SKIPPED),
    }
    verdict = evaluate_gate(plan, seen)
    group = verdict.groups[0]
    assert group.state is GroupState.FAILED
    assert group.failed == 2  # both stop the group passing
    assert group.failed_task_ids == ("a",)  # only one is worth retrying
    assert [change.task_id for change in escalation_changes(plan, verdict, seen)] == ["a"]


def test_a_cancelled_task_is_not_escalated_either():
    # Cancellation is the operator or the budget stopping the run, not a model
    # failing at its job.
    plan = plan_of(task("a"))
    seen = {"a": TaskState(task_id="a", status=TaskStatus.CANCELLED, attempts=1)}
    verdict = evaluate_gate(plan, seen)
    assert verdict.groups[0].state is GroupState.FAILED
    assert escalation_changes(plan, verdict, seen) == []


def test_running_work_is_not_quiescent():
    plan = plan_of(task("a"))
    assert evaluate_gate(plan, states(a=TaskStatus.RUNNING)).quiescent is False
    assert evaluate_gate(plan, states(a=TaskStatus.READY)).quiescent is False
    assert evaluate_gate(plan, states(a=TaskStatus.DONE)).quiescent is True


def test_stale_and_superseded_are_work_not_outcomes():
    # These are revision queues. A group holding them has neither passed nor
    # failed, and the run is still active — waking the brain here would
    # interrupt work the executor already owes.
    plan = plan_of(task("a"), task("b"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.DONE, b=TaskStatus.STALE))
    assert verdict.groups[0].state is GroupState.WORKING
    assert verdict.groups[0].pending_revision == 1
    assert verdict.quiescent is False
    assert verdict.complete is False


def test_a_blocked_group_with_nothing_runnable_is_stuck_not_passed():
    plan = plan_of(task("a"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.BLOCKED))
    assert verdict.groups[0].state is GroupState.STUCK
    assert verdict.quiescent is True
    assert verdict.complete is False


def test_a_task_with_no_recorded_state_is_not_counted_as_done():
    # A revision can add a task that has never been dispatched. Treating an
    # absent record as success would let a gate pass work that never ran.
    plan = plan_of(task("a"), task("b"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.DONE))
    assert verdict.groups[0].done == 1
    assert verdict.complete is False


# --- when to wake the brain ---------------------------------------------


def test_the_brain_is_not_woken_while_workers_are_building():
    plan = plan_of(task("a"), task("b"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.DONE, b=TaskStatus.RUNNING))
    assert verdict.needs_brain is False


def test_the_brain_is_not_woken_to_confirm_success():
    # A reason-tier spawn to be told "it worked" is a spawn wasted.
    plan = plan_of(task("a"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.DONE))
    assert verdict.quiescent is True
    assert verdict.needs_brain is False


def test_the_brain_is_woken_when_work_stops_and_something_failed():
    plan = plan_of(task("a"))
    verdict = evaluate_gate(plan, states(a=TaskStatus.FAILED))
    assert verdict.needs_brain is True


# --- constant size -------------------------------------------------------


def test_verdict_size_does_not_grow_with_task_count():
    """The reason the gate exists. A verdict for 5 tasks and one for 500 must
    be the same size, or the run's cost becomes quadratic in the plan."""
    small = plan_of(*(task(f"t{index}") for index in range(5)))
    large = plan_of(*(task(f"t{index}") for index in range(500)))
    small_states = states(**{f"t{index}": TaskStatus.DONE for index in range(5)})
    large_states = states(**{f"t{index}": TaskStatus.DONE for index in range(500)})

    small_render = evaluate_gate(small, small_states).render()
    large_render = evaluate_gate(large, large_states).render()
    assert len(evaluate_gate(large, large_states).groups) == 1
    # Only the counts differ, so the rendering differs by a handful of digits.
    assert abs(len(large_render) - len(small_render)) < 10


def test_render_never_lists_more_than_three_failed_ids():
    plan = plan_of(*(task(f"t{index}") for index in range(20)))
    verdict = evaluate_gate(
        plan, states(**{f"t{index}": TaskStatus.FAILED for index in range(20)})
    )
    rendered = verdict.render()
    assert "t0" in rendered and "t19" not in rendered


# --- escalation ----------------------------------------------------------


def failed_after(task_id: str, attempts: int) -> dict[str, TaskState]:
    return {
        task_id: TaskState(task_id=task_id, status=TaskStatus.FAILED, attempts=attempts)
    }


def test_a_failed_module_is_retried_one_tier_stronger():
    plan = plan_of(task("a", tier=Tier.MECHANICAL))
    verdict = evaluate_gate(plan, failed_after("a", 2))
    changes = escalation_changes(plan, verdict, failed_after("a", 2))
    assert len(changes) == 1
    assert changes[0].op is RevisionOp.RETARGET_TASK
    assert changes[0].task.tier is Tier.EXTRACT


def test_escalation_also_grants_an_attempt_or_it_would_do_nothing():
    """A task is FAILED because attempts >= max_attempts. Raising only the
    tier produces a better-routed task the executor will never dispatch."""
    original = task("a", tier=Tier.CODE)
    assert original.retry.max_attempts == 2
    plan = plan_of(original)
    seen = failed_after("a", 2)
    replacement = escalation_changes(plan, evaluate_gate(plan, seen), seen)[0].task
    assert replacement.retry.max_attempts == 3  # exactly one more, not a reset


def test_escalation_changes_only_routing_fields():
    """Routing-only is what makes this safe to auto-apply and what stops it
    invalidating completed work — `spec_hash` excludes routing fields."""
    original = task("a", tier=Tier.CODE)
    plan = plan_of(original)
    seen = failed_after("a", 2)
    replacement = escalation_changes(plan, evaluate_gate(plan, seen), seen)[0].task
    assert replacement.spec_hash() == original.spec_hash()
    assert replacement.model_dump(exclude={"tier", "retry"}) == original.model_dump(
        exclude={"tier", "retry"}
    )


def test_escalation_stops_at_the_schema_attempt_ceiling():
    # Six attempts is the schema maximum. A task that burned them all has been
    # tried everywhere the ladder goes; the brain decides from here.
    plan = plan_of(task("a", tier=Tier.CODE))
    seen = failed_after("a", 6)
    assert escalation_changes(plan, evaluate_gate(plan, seen), seen) == []


def test_a_task_already_at_the_strongest_tier_is_not_re_escalated():
    plan = plan_of(task("a", tier=Tier.REASON))
    seen = failed_after("a", 2)
    assert escalation_changes(plan, evaluate_gate(plan, seen), seen) == []


def test_no_downshift_blocks_escalation_too():
    # The flag means "this tier was chosen deliberately"; moving it in either
    # direction overrides that choice.
    plan = plan_of(task("a", tier=Tier.CODE, no_downshift=True))
    seen = failed_after("a", 2)
    assert escalation_changes(plan, evaluate_gate(plan, seen), seen) == []


def test_passing_groups_are_never_escalated():
    plan = plan_of(task("a", group="ok"), task("b", group="bad"))
    seen = {
        "a": TaskState(task_id="a", status=TaskStatus.DONE),
        "b": TaskState(task_id="b", status=TaskStatus.FAILED, attempts=2),
    }
    changes = escalation_changes(plan, evaluate_gate(plan, seen), seen)
    assert [change.task_id for change in changes] == ["b"]


def test_the_ladder_terminates():
    """Escalation must not be able to loop forever. Repeatedly escalating one
    task walks it to the top tier and then stops."""
    current = task("a", tier=Tier.MECHANICAL)
    attempts = 2
    seen_tiers = []
    for _ in range(10):
        plan = plan_of(current)
        seen = failed_after("a", attempts)
        changes = escalation_changes(plan, evaluate_gate(plan, seen), seen)
        if not changes:
            break
        current = changes[0].task
        attempts = current.retry.max_attempts
        seen_tiers.append(current.tier)
    else:  # pragma: no cover - only reached if escalation never terminates
        pytest.fail("escalation did not terminate")
    assert seen_tiers == [Tier.EXTRACT, Tier.CODE, Tier.REASON]


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        (Tier.MECHANICAL, Tier.EXTRACT),
        (Tier.EXTRACT, Tier.CODE),
        (Tier.CODE, Tier.REASON),
        (Tier.REASON, None),
    ],
)
def test_the_escalation_ladder_is_the_downshift_ladder_read_upwards(start, expected):
    assert stronger_tier(task("a", tier=start)) is expected
