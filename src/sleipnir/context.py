"""Resolve a task's InputContract into the exact prompt a subagent receives.

This module is the runtime enforcement point for the contract the schema only
*declares*. A task gets its declared summaries, its declared artifacts (clipped
to their declared byte caps), and its declared files. Nothing else. If a task
wants more context, that is a plan revision, not a runtime accident.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from sleipnir.artifacts import contained_regular_file
from sleipnir.schema import Task

#: Resolves a dependency id to the artifact directory of its latest successful
#: attempt. Supplied by the executor, which is the only component that knows
#: which attempt won.
ArtifactDirResolver = Callable[[str], Path | None]

_CLIP_NOTE = "\n\n[... clipped: {dropped} of {total} bytes not shown ...]"


@dataclass(slots=True)
class IncludedInput:
    kind: str  # "summary" | "artifact" | "file" | "instructions"
    source: str
    bytes: int
    clipped: bool = False


@dataclass(slots=True)
class ResolvedInput:
    prompt: str
    included: list[IncludedInput] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.included)

    def manifest(self) -> dict[str, object]:
        return {
            "total_bytes": self.total_bytes,
            "prompt_bytes": len(self.prompt.encode()),
            "missing": self.missing,
            "included": [
                {
                    "kind": item.kind,
                    "source": item.source,
                    "bytes": item.bytes,
                    "clipped": item.clipped,
                }
                for item in self.included
            ],
        }


def _read_clipped(path: Path, max_bytes: int) -> tuple[str, int, bool]:
    raw = path.read_bytes()
    if len(raw) <= max_bytes:
        return raw.decode("utf-8", errors="replace"), len(raw), False
    text = raw[:max_bytes].decode("utf-8", errors="replace")
    text += _CLIP_NOTE.format(dropped=len(raw) - max_bytes, total=len(raw))
    return text, max_bytes, True


def resolve_inputs(
    task: Task,
    *,
    goal: str,
    run_root: Path,
    summaries: Mapping[str, str],
    artifact_dir_for: ArtifactDirResolver,
) -> ResolvedInput:
    """Build the prompt for ``task``. Pure apart from reading declared files."""
    resolved = ResolvedInput(prompt="")
    sections: list[str] = [
        "# Project goal",
        goal.strip(),
        "",
        "# Your task",
        f"id: {task.id}",
        task.description.strip(),
    ]

    if task.inputs.instructions:
        sections += ["", "# Additional instructions", task.inputs.instructions.strip()]
        resolved.included.append(
            IncludedInput("instructions", task.id, len(task.inputs.instructions.encode()))
        )

    sections += _summary_section(task, summaries, resolved)
    sections += _artifact_section(task, artifact_dir_for, resolved)
    sections += _file_section(task, run_root, resolved)
    sections += _output_section(task)

    resolved.prompt = "\n".join(sections).strip() + "\n"
    return resolved


def _summary_section(
    task: Task, summaries: Mapping[str, str], resolved: ResolvedInput
) -> list[str]:
    if not task.inputs.summaries:
        return []
    lines = ["", "# Results of prior tasks you depend on"]
    for dep in task.inputs.summaries:
        text = summaries.get(dep)
        if text is None:
            resolved.missing.append(f"summary:{dep}")
            continue
        lines += [f"## {dep}", text.strip()]
        resolved.included.append(IncludedInput("summary", dep, len(text.encode())))
    return lines


def _artifact_section(
    task: Task, artifact_dir_for: ArtifactDirResolver, resolved: ResolvedInput
) -> list[str]:
    if not task.inputs.artifacts:
        return []
    lines = ["", "# Full outputs of prior tasks"]
    for ref in task.inputs.artifacts:
        base = artifact_dir_for(ref.task_id)
        if base is None:
            resolved.missing.append(f"artifact:{ref.task_id}/{ref.path}")
            continue
        matches = sorted(base.glob(ref.path)) if ref.is_glob else [base / ref.path]
        found = False
        for match in matches:
            if not contained_regular_file(match, base):
                continue
            found = True
            text, size, clipped = _read_clipped(match, ref.max_bytes)
            rel = match.relative_to(base)
            lines += [f"## {ref.task_id}/{rel}", "```", text, "```"]
            resolved.included.append(
                IncludedInput("artifact", f"{ref.task_id}/{rel}", size, clipped)
            )
        if not found:
            resolved.missing.append(f"artifact:{ref.task_id}/{ref.path}")
    return lines


def _file_section(task: Task, run_root: Path, resolved: ResolvedInput) -> list[str]:
    if not task.inputs.files:
        return []
    lines = ["", "# Repository files"]
    budget = task.inputs.max_input_bytes - resolved.total_bytes
    for pattern in task.inputs.files:
        matches = sorted(run_root.glob(pattern)) if any(c in pattern for c in "*?[") else [run_root / pattern]
        for match in matches:
            if not contained_regular_file(match, run_root):
                resolved.missing.append(f"file:{pattern}")
                continue
            if budget <= 0:
                resolved.missing.append(f"file:{match} (input budget exhausted)")
                continue
            text, size, clipped = _read_clipped(match, budget)
            budget -= size
            rel = match.relative_to(run_root) if match.is_relative_to(run_root) else match
            lines += [f"## {rel}", "```", text, "```"]
            resolved.included.append(IncludedInput("file", str(rel), size, clipped))
    return lines


def _output_section(task: Task) -> list[str]:
    """Tell the subagent exactly what to write and where.

    The paths here are the same ones ``AttemptWorkspace.collect_outputs``
    checks, so 'the model did the work but named the file differently' shows up
    as a *partial* result with the stray file recorded, not as a mystery.
    """
    lines = [
        "",
        "# Required outputs",
        "Write each of these files, relative to your working directory:",
    ]
    for expected in task.outputs.outputs:
        flag = "required" if expected.required else "optional"
        lines.append(f"- `{expected.path}` ({expected.kind}, {flag}) — {expected.description}")

    if task.acceptance:
        lines += ["", "# Acceptance criteria", "Your work is checked by:"]
        for check in task.acceptance:
            lines.append(f"- {_describe_check(check)}")

    lines += [
        "",
        "# Summary (required)",
        "Finally, write `summary.md` containing at most 200 tokens describing what "
        "you produced and anything the orchestrator must know. This summary is the "
        "ONLY part of your output that the orchestrator will read — everything else "
        "is reachable only by file path. Do not restate the task; report the outcome, "
        "including anything you could not finish.",
    ]
    return lines


def _describe_check(check: object) -> str:
    kind = getattr(check, "type", "unknown")
    match kind:
        case "command":
            return f"running `{getattr(check, 'command', '')}` and requiring exit code 0"
        case "file_exists":
            return f"checking these outputs exist and are non-empty: {getattr(check, 'outputs', [])}"
        case "json_schema":
            return f"validating `{getattr(check, 'output', '')}` against a JSON schema"
        case "llm_judge":
            return f"a reviewer grading against: {getattr(check, 'rubric', '')}"
    return str(kind)


__all__ = ["IncludedInput", "ResolvedInput", "resolve_inputs"]
