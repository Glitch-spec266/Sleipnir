"""The voice dispatcher: a local model hands hard work to a tier, never a model.

Stage 5 of the Phase 22 voice rebuild. The operator's constraint is zero
incremental dollars, so the only models this lane may reach are free-priced
ones -- and the local model is told about tiers rather than model names, which
keeps the standing "no model name in source" rule satisfied for free and costs
about sixty prompt tokens instead of four hundred.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sleipnir.config import SleipnirConfig
from sleipnir.pricing import CatalogSnapshot, ModelInfo
from sleipnir.schema import Tier

CONFIG = {
    "backends": [
        {
            "name": "alpha",
            "adapter": "openai",
            "billing": "metered",
            "base_url": "https://example.invalid/v1",
            "api_key_env": "ALPHA_KEY",
            "models": [{"id": "vendor/gratis-big", "context": 128000}],
        },
        {
            "name": "beta",
            "adapter": "openai",
            "billing": "metered",
            "base_url": "https://example.invalid/v1",
            "api_key_env": "BETA_KEY",
            "models": [{"id": "vendor/costly-big", "context": 128000}],
        },
    ],
    # All five tiers must carry a policy: the config refuses to load otherwise,
    # deliberately, so that a run cannot die partway through on a missing one.
    "tiers": {
        "reason": {
            "prefer": ["beta", "alpha"],
            "description": "hard problems, long answers, careful judgement",
        },
        "code": {"prefer": ["alpha"], "description": "writing and changing code"},
        "mechanical": {"prefer": ["alpha"], "description": "short factual lookups"},
        "extract": {"prefer": ["alpha"]},
        "longctx": {"prefer": ["alpha"]},
    },
}


TOML = """
[[backends]]
name = "alpha"
adapter = "openai"
billing = "metered"
base_url = "https://example.invalid/v1"
api_key_env = "ALPHA_KEY"
models = [{ id = "vendor/gratis-big", context = 128000 }]

[tiers.reason]
prefer = ["alpha"]
description = "hard problems, long answers, careful judgement"

[tiers.code]
prefer = ["alpha"]

[tiers.mechanical]
prefer = ["alpha"]

[tiers.extract]
prefer = ["alpha"]

[tiers.longctx]
prefer = ["alpha"]
"""


def _catalog() -> CatalogSnapshot:
    return CatalogSnapshot(
        models={
            "vendor/gratis-big": ModelInfo("vendor/gratis-big", 128000, 0.0, 0.0),
            # Cheapest by a wide margin, and still forbidden: the operator's
            # constraint is zero dollars, not few dollars.
            "vendor/costly-big": ModelInfo("vendor/costly-big", 128000, 0.01, 0.02),
        },
        fetched_at=datetime.now(UTC),
        source="<test>",
    )


def test_the_delegation_menu_names_tiers_and_never_models():
    from sleipnir.voice.dispatch import delegation_menu

    config = SleipnirConfig.from_dict(CONFIG, source="<test>")
    menu = delegation_menu(config)

    assert "reason" in menu
    assert "hard problems, long answers, careful judgement" in menu
    assert "mechanical" in menu
    for forbidden in ("vendor/gratis-big", "vendor/costly-big", "free", "paid"):
        assert forbidden not in menu.replace("free-form", "")
    # The whole menu is interpolated into a 16K local context every turn.
    assert len(menu) < 600


def test_the_dispatcher_only_routes_to_a_free_model():
    """A cheaper paid model must lose to a free one, and win nothing on its own."""
    from sleipnir.voice.dispatch import DispatchRefused, pick_model

    config = SleipnirConfig.from_dict(CONFIG, source="<test>")
    catalog = _catalog()

    choice = pick_model(config, catalog, tier=Tier.REASON)
    assert choice.model == "vendor/gratis-big"
    assert choice.backend == "alpha"
    assert choice.tier is Tier.REASON
    # The endpoint travels with the choice; the credential never does.
    assert choice.base_url == "https://example.invalid/v1"
    assert choice.api_key_env == "ALPHA_KEY"

    # With no free candidate at all the lane refuses rather than spending.
    paid_only = {
        **CONFIG,
        "tiers": {**CONFIG["tiers"], "reason": {"prefer": ["beta"]}},
    }
    with pytest.raises(DispatchRefused, match="free"):
        pick_model(
            SleipnirConfig.from_dict(paid_only, source="<test>"), catalog, tier=Tier.REASON
        )


def test_an_unknown_tier_is_refused_rather_than_defaulted():
    """Same rule as the router's unknown effort level and the tier deny list.

    A model-supplied tier name is untrusted text. Silently falling back to a
    default tier would let a hallucinated word choose where the operator's
    work -- and their quota -- goes.
    """
    from sleipnir.voice.dispatch import DispatchRefused, pick_model

    config = SleipnirConfig.from_dict(CONFIG, source="<test>")
    with pytest.raises(DispatchRefused, match="tier"):
        pick_model(config, _catalog(), tier="whatever-the-model-said")


def test_a_delegated_answer_returns_only_its_spoken_line():
    """The worker's full answer must not flow back into the local context.

    Delegation exists because the local model is not good enough; handing it
    the whole reply to summarise spends its context on work it already lost.
    The worker states one spoken sentence first and that is all that returns.
    """
    from sleipnir.voice.dispatch import spoken_line

    long_answer = "SPOKEN: The bridge needs 32 tonnes of steel.\n\n" + "detail " * 400
    assert spoken_line(long_answer) == "The bridge needs 32 tonnes of steel."

    # A worker that ignores the contract still must not flood the context.
    flood = "no marker here. " * 400
    assert len(spoken_line(flood)) <= 300
    assert spoken_line(flood).startswith("no marker here.")


def test_delegating_writes_an_audit_record_for_every_outcome(tmp_path, monkeypatch):
    """`delegate_work` wrote nothing at all, not even for its own refusal.

    Delegation spends the operator's quota on another provider and is exactly
    the kind of privileged call the audit log exists for. Three shapes have to
    land: the request, the routing decision, and the outcome -- and a refusal
    is an outcome.
    """
    import asyncio
    import json

    from sleipnir.capabilities import audit
    from sleipnir.voice.local_agent import LocalToolbox

    log = tmp_path / "capability-audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_LOG", log)

    toolbox = LocalToolbox(
        workspace=tmp_path,
        permission_mode="ask",
        original_prompt="summarise this for me",
        task_grant=False,
    )
    result = asyncio.run(toolbox.execute("delegate_work", {"provider": "claude", "instruction": "do it"}))

    assert json.loads(result)["status"] == "approval_required"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [record["action"] for record in records] == ["local.delegate_work"]
    assert records[0]["detail"]["outcome"] == "refused"
    # The instruction is the operator's words and the worker's prompt; only its
    # size belongs in an audit log, the same rule as typed text.
    assert "do it" not in json.dumps(records[0])


def test_a_tier_delegation_records_its_route_and_returns_only_the_spoken_line(
    tmp_path, monkeypatch
):
    """The whole api lane, from a tier name to one sentence and three records."""
    import asyncio
    import json

    from sleipnir.capabilities import audit
    from sleipnir.voice.local_agent import LocalToolbox
    from sleipnir.voice.relay import AmbientReply

    log = tmp_path / "capability-audit.jsonl"
    monkeypatch.setattr(audit, "DEFAULT_LOG", log)
    monkeypatch.setenv("ALPHA_KEY", "not-a-real-key")

    asked: dict = {}

    class Relay:
        async def respond(self, prompt, **kwargs):
            asked.update(kwargs, prompt=prompt)
            return AmbientReply(
                "SPOKEN: It needs 32 tonnes of steel.\n\n" + "working " * 500,
                "openai",
                kwargs["model"],
            )

    toolbox = LocalToolbox(
        workspace=tmp_path,
        permission_mode="always",
        original_prompt="how much steel does the bridge need",
    )
    toolbox.relay = Relay()
    toolbox._routing = (SleipnirConfig.from_dict(CONFIG, source="<test>"), _catalog())

    result = asyncio.run(
        toolbox.execute(
            "delegate_work",
            {"provider": "api", "tier": "reason", "instruction": "how much steel?"},
        )
    )

    assert result == "It needs 32 tonnes of steel."
    assert asked["model"] == "vendor/gratis-big"
    assert asked["base_url"] == "https://example.invalid/v1"
    assert asked["api_key"] == "not-a-real-key"

    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [record["detail"]["outcome"] for record in records] == ["routed", "answered"]
    assert records[0]["detail"]["tier"] == "reason"
    # The key must not reach the log by any route, including a redacted one.
    assert "not-a-real-key" not in log.read_text(encoding="utf-8")


def test_a_reasoning_timeout_becomes_a_delegation_not_an_error(tmp_path):
    """The 25 s deadline exists to hand off fast, so it must actually hand off.

    Until the dispatcher existed, exhausting the local reasoning budget raised
    LocalCapabilityExceeded out of the turn and the operator heard a failure
    for a question another model could answer in a second.
    """
    import asyncio

    import httpx

    from sleipnir.voice.local_agent import LocalCapabilityExceeded, LocalDesktopAgent

    delegated: list[dict] = []

    async def run_tool(name: str, arguments: dict) -> str:
        delegated.append({"name": name, **arguments})
        return "About 32 tonnes."

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        tool_runner=run_tool,
    )

    async def exhausted(*args, **kwargs):
        raise LocalCapabilityExceeded("deliberated past the deadline")

    agent._reason = exhausted  # type: ignore[method-assign]
    reply = asyncio.run(
        agent.respond(
            "calculate the steel mass for a 40 metre span",
            workspace=tmp_path,
            model="jarvis",
            permission_mode="ask",
        )
    )

    assert reply.text == "About 32 tonnes."
    assert delegated == [
        {
            "name": "delegate_work",
            "provider": "api",
            "tier": "reason",
            "instruction": "calculate the steel mass for a 40 metre span",
        }
    ]


def test_a_delegation_that_cannot_route_is_spoken_not_printed_as_json(tmp_path):
    """An unavailable lane must still leave the operator with a sentence."""
    import asyncio

    import httpx

    from sleipnir.voice.local_agent import LocalCapabilityExceeded, LocalDesktopAgent

    async def run_tool(name: str, arguments: dict) -> str:
        return '{"status": "unavailable", "reason": "live prices are unavailable"}'

    agent = LocalDesktopAgent(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
        tool_runner=run_tool,
    )

    async def exhausted(*args, **kwargs):
        raise LocalCapabilityExceeded("deliberated past the deadline")

    agent._reason = exhausted  # type: ignore[method-assign]
    reply = asyncio.run(
        agent.respond(
            "calculate the steel mass for a 40 metre span",
            workspace=tmp_path,
            model="jarvis",
            permission_mode="ask",
        )
    )

    assert "{" not in reply.text
    assert "couldn't" in reply.text.casefold() or "could not" in reply.text.casefold()


def test_the_system_prompt_offers_the_menu_and_still_names_no_model(tmp_path):
    """A tool the model is never told how to use is a tool it will never use."""
    from sleipnir.voice.dispatch import menu_for

    (tmp_path / "sleipnir.toml").write_text(TOML, encoding="utf-8")
    menu = menu_for(tmp_path)

    assert "reason: hard problems" in menu
    assert "vendor/" not in menu

    # No config at all is the ordinary case for a fresh machine: the menu is
    # simply absent, and the local model keeps every other tool.
    assert menu_for(tmp_path / "elsewhere") == ""


def test_a_deck_is_written_as_a_real_pptx_inside_the_output_folder(tmp_path, monkeypatch):
    """A presentation the operator can open in PowerPoint, not an HTML page.

    python-pptx is an optional extra: the core keeps its three runtime
    dependencies, and a machine without it gets a refusal that names the extra
    rather than a traceback.
    """
    import asyncio
    import json

    pytest.importorskip("pptx")

    from sleipnir.capabilities import audit
    from sleipnir.voice.local_agent import LocalToolbox

    monkeypatch.setattr(audit, "DEFAULT_LOG", tmp_path / "audit.jsonl")
    toolbox = LocalToolbox(
        workspace=tmp_path,
        permission_mode="ask",
        original_prompt="make me a deck",
        output_root=tmp_path / "out",
    )
    result = json.loads(
        asyncio.run(
            toolbox.execute(
                "build_deck",
                {
                    "path": "photosynthesis.pptx",
                    "title": "Photosynthesis",
                    "slides": [
                        {"title": "The reaction", "bullets": ["Light", "Water", "CO2"]},
                        {"title": "Why it matters", "bullets": ["Oxygen", "Food"]},
                    ],
                },
            )
        )
    )

    written = tmp_path / "out" / "photosynthesis.pptx"
    assert result["status"] == "written"
    assert written.is_file()
    # A .pptx is a zip; anything else means we wrote a text file with the
    # wrong extension, which is the failure this whole stage exists to end.
    assert written.read_bytes()[:2] == b"PK"

    from pptx import Presentation

    deck = Presentation(str(written))
    assert len(deck.slides) == 3  # title slide plus the two content slides


def test_a_deck_may_not_escape_the_output_folder(tmp_path, monkeypatch):
    """Same containment check as write_file: the name is untrusted model output."""
    import asyncio

    from sleipnir.capabilities import audit
    from sleipnir.voice.local_agent import LocalToolbox

    monkeypatch.setattr(audit, "DEFAULT_LOG", tmp_path / "audit.jsonl")
    toolbox = LocalToolbox(
        workspace=tmp_path,
        permission_mode="always",
        original_prompt="make me a deck",
        output_root=tmp_path / "out",
    )
    with pytest.raises(ValueError, match="Sleipnir output folder"):
        asyncio.run(
            toolbox.execute(
                "build_deck",
                {"path": "../../escape.pptx", "title": "x", "slides": [{"title": "y"}]},
            )
        )
