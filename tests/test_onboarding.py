"""What a fresh install needs, and what the wizard is allowed to claim."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from sleipnir import onboarding
from sleipnir.onboarding import (
    Headroom,
    Requirement,
    alias_modelfile,
    model_options,
    root_batch,
)


def _requirement(identifier: str, *, fix: str, root: bool) -> Requirement:
    return Requirement(id=identifier, label=identifier, present=False, fix=fix, needs_root=root)


def test_every_privileged_fix_runs_behind_one_prompt() -> None:
    """``sudo -A`` spawns its askpass helper per prompt, so six installs would
    otherwise be six pinentry dialogs."""
    script = root_batch(
        [
            _requirement("a", fix="pacman -Syu --noconfirm grim", root=True),
            _requirement("b", fix="pacman -Syu --noconfirm ydotool", root=True),
            _requirement("c", fix="curl -o model", root=False),
            Requirement(id="d", label="d", present=True, fix="never run", needs_root=True),
        ]
    )

    assert script.startswith("set -e\n")
    assert "grim" in script and "ydotool" in script
    # An unprivileged download and an already-satisfied requirement are both
    # outside the batch: the first needs no password, the second needs nothing.
    assert "curl -o model" not in script
    assert "never run" not in script


def test_nothing_missing_means_no_password_prompt() -> None:
    assert root_batch([Requirement(id="a", label="a", present=True)]) == ""


def test_capacity_is_installed_memory_and_pressure_is_free_memory() -> None:
    """A machine already running the assistant must not be told it cannot."""
    space = Headroom(free_gib=3.1, total_gib=8.0, device="GPU", accelerated=True)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"layers": [{"size": 6_100_000_000}]})

    options = asyncio.run(model_options(space, transport=httpx.MockTransport(handler)))
    by_tier = {option.tier: option for option in options}

    # 8 GiB installed clears the 7.5 GiB floor even though 3.1 GiB is free now.
    assert by_tier["moderate"].fits
    assert "free right now" in by_tier["moderate"].note
    # The 32b floor is a genuine hardware verdict, not memory pressure.
    assert not by_tier["high"].fits
    assert "this machine has" in by_tier["high"].note


def test_an_unreachable_registry_reports_unknown_and_never_a_guess() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    space = Headroom(free_gib=64.0, total_gib=64.0, device="GPU", accelerated=True)
    options = asyncio.run(model_options(space, transport=httpx.MockTransport(handler)))

    assert {option.download for option in options} == {"unknown"}
    # The fit verdict is offline knowledge and must survive the outage.
    assert all(option.fits for option in options)


def test_the_alias_carries_the_context_the_tool_loop_needs() -> None:
    """MEASURED: 8K overran on a single vision/tool follow-up. Without this the
    operator has to know to hand-write a Modelfile, which is the step that made
    setup take an afternoon."""
    text = alias_modelfile("qwen3-vl:8b")

    assert text.startswith("FROM qwen3-vl:8b")
    assert f"num_ctx {onboarding.LOCAL_CONTEXT_TOKENS}" in text


def test_an_implausible_model_name_is_refused_before_it_reaches_a_shell() -> None:
    with pytest.raises(ValueError):
        asyncio.run(onboarding.pull_model("qwen3-vl:8b; rm -rf ~"))


def test_the_probe_reports_a_fix_for_everything_it_reports_as_missing() -> None:
    """A wizard that says "missing" with no command is the two-hour setup."""
    for item in onboarding.probe():
        if not item.present and not item.interactive:
            assert item.fix, f"{item.id} is missing with no fix"
