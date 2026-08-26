"""Acceptance checks.

Checks run *after* the adapter returns and decide whether work that exists is
work that counts. A task whose outputs all landed but whose checks fail is a
`FAILED` attempt with `ACCEPTANCE_FAILED`, which the default retry policy
escalates a tier rather than retrying identically — retrying the same model on
work it already got wrong is how you spend twice for one failure.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sleipnir.artifacts import AttemptWorkspace
from sleipnir.process import ProcessRunner
from sleipnir.schema import (
    AcceptanceCheck,
    CheckResult,
    CommandCheck,
    ExpectedOutput,
    FileExistsCheck,
    JsonSchemaCheck,
    LlmJudgeCheck,
    Task,
)


class UnsupportedCheckError(RuntimeError):
    """Raised at startup, not per task.

    A plan that cannot be fully checked must fail loudly before anything is
    dispatched. Discovering mid-run that a check silently passed because it was
    unimplemented is strictly worse than refusing the plan.
    """


#: `sh` runs these itself, so PATH says nothing about whether they work.
_SHELL_BUILTINS = frozenset(
    """: . [ break cd continue echo eval exec exit export false hash pwd read
    return set shift test times trap true type ulimit umask unset wait""".split()
)

#: Any of these means the command is a shell program rather than one
#: invocation, and its program cannot be resolved without running it.
_SHELL_SYNTAX = frozenset("|&;<>()$`\n*?[]{}~!#'\\\"")


def _static_program(command: str) -> str | None:
    """The one program this command will run, when that is knowable statically.

    Returns None whenever the answer needs a shell to decide. Guessing there
    would refuse working plans, which is a worse failure than the one this
    guards against.
    """
    if any(character in _SHELL_SYNTAX for character in command):
        return None
    parts = command.split()
    if not parts:
        return None
    program = parts[0]
    if "=" in program or "/" in program:
        return None  # an env assignment, or a path the operator spelled out
    return None if program in _SHELL_BUILTINS else program


def assert_checks_supported(
    tasks: list[Task], *, env: Mapping[str, str] | None = None
) -> None:
    unsupported = sorted(
        {
            f"{task.id}:{check.type}"
            for task in tasks
            for check in task.acceptance
            if isinstance(check, LlmJudgeCheck)
        }
    )
    if unsupported:
        raise UnsupportedCheckError(
            "llm_judge checks need a router to resolve a judge model and are not "
            f"available until Phase 3; offending tasks: {', '.join(unsupported)}"
        )

    # A command check whose program is not installed can never pass, so every
    # attempt at that task is spend with no possible outcome. Refuse the plan
    # while refusing is still free.
    search_path = (env or os.environ).get("PATH")
    missing = sorted(
        {
            f"{task.id}: {program}"
            for task in tasks
            for check in task.acceptance
            if isinstance(check, CommandCheck)
            for program in [_static_program(check.command)]
            if program is not None and shutil.which(program, path=search_path) is None
        }
    )
    if missing:
        raise UnsupportedCheckError(
            "these acceptance checks name a program that is not on PATH, so no "
            f"attempt at those tasks could ever pass: {'; '.join(missing)}"
        )


async def run_checks(
    task: Task,
    workspace: AttemptWorkspace,
    *,
    runner: ProcessRunner | None = None,
    env: Mapping[str, str] | None = None,
    timeout_scale: float = 1.0,
) -> list[CheckResult]:
    runner = runner or ProcessRunner()
    outputs = {out.name: out for out in task.outputs.outputs}
    results: list[CheckResult] = []
    for check in task.acceptance:
        results.append(await _run_one(check, workspace, outputs, runner, env, timeout_scale))
    return results


async def _run_one(
    check: AcceptanceCheck,
    workspace: AttemptWorkspace,
    outputs: Mapping[str, ExpectedOutput],
    runner: ProcessRunner,
    env: Mapping[str, str] | None,
    timeout_scale: float,
) -> CheckResult:
    started = time.monotonic()
    try:
        passed, detail = await _dispatch_check(
            check, workspace, outputs, runner, env, timeout_scale
        )
    except Exception as exc:  # a broken check is a failed check, never a crash
        passed, detail = False, f"{type(exc).__name__}: {exc}"
    return CheckResult(
        check_type=check.type,
        passed=passed,
        detail=detail[:1_000],
        duration_s=round(time.monotonic() - started, 3),
    )


async def _dispatch_check(
    check: AcceptanceCheck,
    workspace: AttemptWorkspace,
    outputs: Mapping[str, ExpectedOutput],
    runner: ProcessRunner,
    env: Mapping[str, str] | None,
    timeout_scale: float,
) -> tuple[bool, str]:
    match check:
        case CommandCheck():
            return await _check_command(check, workspace, runner, env, timeout_scale)
        case FileExistsCheck():
            return _check_files(check, workspace, outputs)
        case JsonSchemaCheck():
            return _check_json_schema(check, workspace, outputs)
    return False, f"unsupported check type {check.type!r}"


async def _check_command(
    check: CommandCheck,
    workspace: AttemptWorkspace,
    runner: ProcessRunner,
    env: Mapping[str, str] | None,
    timeout_scale: float,
) -> tuple[bool, str]:
    cwd = workspace.dir / check.cwd if check.cwd else workspace.dir
    logs = workspace.dir / ".checks"
    logs.mkdir(parents=True, exist_ok=True)
    stem = f"command-{abs(hash(check.command)) % 10_000:04d}"
    result = await runner.run(
        ["/bin/sh", "-c", check.command],
        stdout_path=logs / f"{stem}.out",
        stderr_path=logs / f"{stem}.err",
        cwd=cwd,
        env=env,
        timeout_s=check.timeout_s * timeout_scale,
    )
    if result.timed_out:
        return False, f"command timed out after {check.timeout_s}s"
    if result.exit_code == 0:
        return True, "exit 0"
    return False, f"exit {result.exit_code}: {result.stderr_tail[-400:]}"


def _check_files(
    check: FileExistsCheck,
    workspace: AttemptWorkspace,
    outputs: Mapping[str, ExpectedOutput],
) -> tuple[bool, str]:
    problems: list[str] = []
    for name in check.outputs:
        expected = outputs.get(name)
        if expected is None:
            problems.append(f"{name}: not a declared output")
            continue
        path = workspace.dir / expected.path
        if not path.is_file():
            problems.append(f"{name}: missing ({expected.path})")
        elif path.stat().st_size < check.min_bytes:
            problems.append(f"{name}: {path.stat().st_size}B < {check.min_bytes}B")
    return (not problems), "; ".join(problems) or f"{len(check.outputs)} output(s) present"


def _check_json_schema(
    check: JsonSchemaCheck,
    workspace: AttemptWorkspace,
    outputs: Mapping[str, ExpectedOutput],
) -> tuple[bool, str]:
    expected = outputs.get(check.output)
    if expected is None:
        return False, f"{check.output}: not a declared output"
    path = workspace.dir / expected.path
    if not path.is_file():
        return False, f"{check.output}: missing ({expected.path})"
    try:
        instance = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"{check.output}: invalid JSON: {exc}"
    problems = _validate(instance, check.json_schema, "$")
    return (not problems), "; ".join(problems[:10]) or "schema satisfied"


_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _validate(instance: Any, schema: Mapping[str, Any], path: str) -> list[str]:
    """A deliberate *subset* of JSON Schema: type, required, properties, items,
    enum, and the numeric/length bounds.

    Full JSON Schema means the `jsonschema` dependency, which is not on the
    sanctioned list. This covers the shape-checking a task output realistically
    needs; anything richer should use a CommandCheck that runs a real validator,
    which keeps the dependency in the plan rather than in Sleipnir.
    """
    problems: list[str] = []

    declared = schema.get("type")
    if isinstance(declared, str) and declared in _TYPES:
        expected = _TYPES[declared]
        # bool is a subclass of int in Python; JSON Schema treats them apart.
        if isinstance(instance, bool) and declared in ("integer", "number"):
            problems.append(f"{path}: expected {declared}, got boolean")
        elif not isinstance(instance, expected):
            problems.append(f"{path}: expected {declared}, got {type(instance).__name__}")
            return problems

    if "enum" in schema and instance not in schema["enum"]:
        problems.append(f"{path}: {instance!r} not in enum")

    if isinstance(instance, dict):
        for key in schema.get("required") or []:
            if key not in instance:
                problems.append(f"{path}: missing required property {key!r}")
        for key, subschema in (schema.get("properties") or {}).items():
            if key in instance and isinstance(subschema, dict):
                problems += _validate(instance[key], subschema, f"{path}.{key}")

    if isinstance(instance, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for index, item in enumerate(instance):
                problems += _validate(item, items, f"{path}[{index}]")
        if "minItems" in schema and len(instance) < schema["minItems"]:
            problems.append(f"{path}: {len(instance)} items < minItems {schema['minItems']}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            problems.append(f"{path}: shorter than minLength {schema['minLength']}")

    if isinstance(instance, int | float) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            problems.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            problems.append(f"{path}: {instance} > maximum {schema['maximum']}")

    return problems


__all__ = ["UnsupportedCheckError", "assert_checks_supported", "run_checks"]
