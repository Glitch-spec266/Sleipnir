"""Router: tier -> model, filters, preference order, and explainability."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from test_schema import make_task

from sleipnir.config import ConfigError, ModelOption, SleipnirConfig
from sleipnir.pricing import CatalogSnapshot, ModelInfo
from sleipnir.router import RoutingError, TierRouter, required_context_tokens
from sleipnir.schema import Adapter, ArtifactRef, InputContract, Tier

CONFIG_TOML = """
[[backends]]
name = "sub"
adapter = "claude"
billing = "subscription"
dispatch_overhead_tokens = 30000
models = [{ id = "big-sub", context = 200000 }, { id = "small-sub", context = 32000 }]

[[backends]]
name = "meter"
adapter = "openrouter"
billing = "metered"
models = ["cheap/x"]

[tiers.reason]
prefer = ["sub", "meter"]
min_context = 100000

[tiers.code]
prefer = ["sub", "meter"]
min_context = 16000

[tiers.mechanical]
prefer = ["meter", "sub"]
min_context = 8000
max_price_per_mtok = 1.0

[tiers.extract]
prefer = ["meter"]
min_context = 8000

[tiers.longctx]
prefer = ["meter"]
min_context = 400000
"""


def config(**overrides) -> SleipnirConfig:
    import tomllib
    raw = tomllib.loads(CONFIG_TOML)
    raw.update(overrides)
    return SleipnirConfig.from_dict(raw, source="<test>")


def model(model_id, *, price=1.0, out=2.0, context=128_000, params=("tools",)):
    return ModelInfo(
        id=model_id,
        context_length=context,
        input_per_mtok=price,
        output_per_mtok=out,
        supported_parameters=tuple(params),
    )


def catalog(*models, stale=False) -> CatalogSnapshot:
    return CatalogSnapshot(
        models={m.id: m for m in models},
        fetched_at=datetime(2026, 8, 17, tzinfo=UTC),
        source="test",
        stale=stale,
    )


def router(*models, cfg=None, **kwargs) -> TierRouter:
    cfg = cfg or config()
    if models:
        meter = cfg.backends["meter"]
        cfg.backends["meter"] = meter.__class__(
            name=meter.name,
            adapter=meter.adapter,
            billing=meter.billing,
            models=tuple(ModelOption(id=item.id) for item in models),
            dispatch_overhead_tokens=meter.dispatch_overhead_tokens,
        )
    return TierRouter(cfg, catalog(*models, **kwargs))


# -- preference order ------------------------------------------------------


def test_first_preferred_backend_with_a_candidate_wins():
    r = router(model("cheap/x", price=0.05))
    decision = r.resolve(make_task("t", tier=Tier.CODE), attempt=1, tier=Tier.CODE)
    assert decision.model == "big-sub"
    assert decision.adapter is Adapter.CLAUDE


def test_mechanical_prefers_metered_over_the_subscription_spawn_overhead():
    """The measured ~30k fixed cost of a `claude -p` spawn is why mechanical
    work should not default to the subscription backend."""
    r = router(model("cheap/x", price=0.05, context=64_000))
    decision = r.resolve(make_task("t", tier=Tier.MECHANICAL), attempt=1, tier=Tier.MECHANICAL)
    assert decision.adapter is Adapter.OPENROUTER
    assert decision.model == "cheap/x"


def test_falls_through_to_the_next_backend_when_the_first_cannot_serve():
    # longctx needs 400k; no subscription model declares that much.
    r = router(model("huge/x", context=1_000_000, price=0.5))
    decision = r.resolve(make_task("t", tier=Tier.LONGCTX), attempt=1, tier=Tier.LONGCTX)
    assert decision.model == "huge/x"


def test_explicit_model_list_rotates_in_config_order():
    r = router(
        model("dear/x", price=10.0, context=64_000),
        model("cheap/x", price=0.10, context=64_000),
        model("mid/x", price=0.50, context=64_000),
    )
    decision = r.resolve(make_task("t", tier=Tier.EXTRACT), attempt=1, tier=Tier.EXTRACT)
    assert decision.model == "dear/x"


def test_explicit_model_lists_keep_config_order():
    """The operator knows their own plan better than a price table does."""
    r = router()
    explanation = r.explain(make_task("t", tier=Tier.CODE), tier=Tier.CODE)
    assert explanation.decision.model == "big-sub"


# -- filters ---------------------------------------------------------------


def test_models_with_too_little_context_are_rejected():
    r = router(model("small/x", context=4_000, price=0.01))
    with pytest.raises(RoutingError, match="no model satisfies"):
        r.resolve(make_task("t", tier=Tier.LONGCTX), attempt=1, tier=Tier.LONGCTX)


def test_unknown_context_does_not_exclude_a_candidate():
    """Missing catalogue metadata is uncertainty, not evidence of insufficiency."""
    unknown = model("unknown/x", context=64_000, price=0.01)
    unknown = unknown.__class__(
        id=unknown.id,
        context_length=None,
        input_per_mtok=unknown.input_per_mtok,
        output_per_mtok=unknown.output_per_mtok,
    )
    decision = router(unknown).resolve(
        make_task("t", tier=Tier.LONGCTX), attempt=1, tier=Tier.LONGCTX
    )
    assert decision.model == "unknown/x"


def test_price_cap_is_enforced():
    r = router(model("dear/x", price=50.0, out=50.0, context=64_000))
    # mechanical caps at $1.00/Mtok, and no subscription model is cheap enough
    # to be priced at all, so nothing qualifies.
    explanation = r.explain(make_task("t", tier=Tier.MECHANICAL), tier=Tier.MECHANICAL)
    rejected = [c for c in explanation.candidates if not c.accepted]
    assert any("exceeds cap" in c.reason for c in rejected)


def test_required_parameters_are_enforced_when_the_catalogue_reports_them():
    cfg = config()
    cfg.tiers[Tier.EXTRACT] = cfg.tiers[Tier.EXTRACT].__class__(
        prefer=("meter",), min_context=8_000, require_parameters=("reasoning",)
    )
    r = router(model("plain/x", params=("tools",)), model("thinky/x", params=("tools", "reasoning")), cfg=cfg)
    decision = r.resolve(make_task("t", tier=Tier.EXTRACT), attempt=1, tier=Tier.EXTRACT)
    assert decision.model == "thinky/x"


def test_required_parameters_do_not_exclude_operator_declared_models():
    """A subscription model has no catalogue entry and therefore reports no
    capabilities. Rejecting it for that would silently exclude every
    subscription backend from any tier that requires a parameter."""
    cfg = config()
    policy = cfg.tiers[Tier.CODE]
    cfg.tiers[Tier.CODE] = policy.__class__(
        prefer=("sub",), min_context=16_000, require_parameters=("reasoning",)
    )
    decision = TierRouter(cfg, catalog()).resolve(
        make_task("t", tier=Tier.CODE), attempt=1, tier=Tier.CODE
    )
    assert decision.model == "big-sub"


def test_deny_and_allow_patterns():
    cfg = config()
    cfg.tiers[Tier.EXTRACT] = cfg.tiers[Tier.EXTRACT].__class__(
        prefer=("meter",), min_context=8_000, deny=("bad",)
    )
    r = router(model("bad/x", price=0.01), model("good/x", price=0.02), cfg=cfg)
    assert r.resolve(make_task("t", tier=Tier.EXTRACT), attempt=1, tier=Tier.EXTRACT).model == "good/x"


# -- context sizing --------------------------------------------------------


def test_required_context_follows_declared_inputs_not_the_global_cap():
    """Using max_input_bytes would demand a 70k window for a task that reads
    nothing."""
    plain = make_task("a")
    heavy = make_task(
        "b",
        deps=["a"],
        inputs=InputContract(
            artifacts=[
                ArtifactRef(
                    task_id="a",
                    path="out.py",
                    reason="needs the whole file to refactor faithfully",
                    max_bytes=400_000,
                )
            ],
            max_input_bytes=500_000,
        ),
    )
    policy = config().policy(Tier.CODE)
    assert required_context_tokens(plain, policy) < required_context_tokens(heavy, policy)
    assert required_context_tokens(heavy, policy) > 100_000


# -- explainability --------------------------------------------------------


def test_explain_lists_accepted_and_rejected_candidates_with_reasons():
    r = router(model("small/x", context=1_000, price=0.01), model("ok/x", context=64_000, price=0.02))
    explanation = r.explain(make_task("t", tier=Tier.EXTRACT), tier=Tier.EXTRACT)
    rendered = explanation.render()
    assert "small/x" in rendered and "context 1,000" in rendered
    assert "ok/x" in rendered
    assert "chosen" in rendered


def test_explain_flags_a_stale_catalogue():
    r = router(model("ok/x", context=64_000), stale=True)
    explanation = r.explain(make_task("t", tier=Tier.EXTRACT), tier=Tier.EXTRACT)
    assert any("stale" in note for note in explanation.notes)


def test_downshift_is_recorded_with_its_reason():
    r = router(model("cheap/x", price=0.05, context=64_000))
    decision = r.resolve(
        make_task("t", tier=Tier.REASON),
        attempt=1,
        tier=Tier.MECHANICAL,
        downshift_reason="window headroom exhausted",
    )
    assert decision.downshifted is True
    assert decision.downshift_reason == "window headroom exhausted"
    assert decision.escalated is False


def test_escalation_is_not_mistaken_for_a_downshift():
    r = router(model("cheap/x", price=0.05, context=200_000))
    decision = r.resolve(make_task("t", tier=Tier.MECHANICAL), attempt=2, tier=Tier.REASON)
    assert decision.escalated is True
    assert decision.downshifted is False


def test_longctx_movement_is_neither_downshift_nor_escalation():
    """longctx sits outside the ladder: moving off it is a correctness failure,
    not a saving."""
    r = router(model("huge/x", context=1_000_000, price=0.5))
    decision = r.resolve(make_task("t", tier=Tier.LONGCTX), attempt=1, tier=Tier.LONGCTX)
    assert not decision.downshifted and not decision.escalated


# -- config validation -----------------------------------------------------


def test_missing_tier_policy_fails_at_load_not_at_dispatch():
    import tomllib
    raw = tomllib.loads(CONFIG_TOML)
    del raw["tiers"]["longctx"]
    with pytest.raises(ConfigError, match="longctx"):
        SleipnirConfig.from_dict(raw, source="<test>")


def test_unknown_backend_reference_is_rejected():
    import tomllib
    raw = tomllib.loads(CONFIG_TOML)
    raw["tiers"]["code"]["prefer"] = ["nope"]
    with pytest.raises(ConfigError, match="unknown backend"):
        SleipnirConfig.from_dict(raw, source="<test>")


def test_unknown_tier_name_is_rejected():
    import tomllib
    raw = tomllib.loads(CONFIG_TOML)
    raw["tiers"]["turbo"] = {"prefer": ["meter"]}
    with pytest.raises(ConfigError, match="architecture decision"):
        SleipnirConfig.from_dict(raw, source="<test>")


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"concurrency": 0}, "concurrency"),
        ({"catalog_ttl_s": float("nan")}, "catalog_ttl_s"),
        ({"reserve_fraction": 1.0}, "reserve_fraction"),
        ({"window_tokens_limit": -1}, "window_tokens_limit"),
        ({"metered_budget_usd": float("inf")}, "metered_budget_usd"),
    ],
)
def test_dangerous_numeric_config_is_rejected(override, message):
    with pytest.raises(ConfigError, match=message):
        config(**override)


def test_non_finite_operator_model_price_is_rejected():
    import tomllib
    raw = tomllib.loads(CONFIG_TOML)
    raw["backends"][0]["models"][0]["price_per_mtok"] = float("nan")
    with pytest.raises(ConfigError, match="price must be finite"):
        SleipnirConfig.from_dict(raw, source="<test>")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("metered_budget_usd",), 1.0),
        (("backends", 0, "typo"), True),
        (("tiers", "code", "typo"), True),
    ],
)
def test_unknown_config_keys_are_rejected(path, value):
    import tomllib

    raw = tomllib.loads(CONFIG_TOML)
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    if path == ("metered_budget_usd",):
        target["metered_budegt_usd"] = target.pop("metered_budget_usd")
    with pytest.raises(ConfigError, match="unknown configuration key"):
        SleipnirConfig.from_dict(raw, source="<test>")


def test_empty_or_duplicate_model_lists_are_rejected():
    import tomllib

    raw = tomllib.loads(CONFIG_TOML)
    raw["backends"][1]["models"] = []
    with pytest.raises(ConfigError, match="at least one model"):
        SleipnirConfig.from_dict(raw, source="<test>")

    raw = tomllib.loads(CONFIG_TOML)
    raw["backends"][1]["models"] = ["same/x", "same/x"]
    with pytest.raises(ConfigError, match="more than once"):
        SleipnirConfig.from_dict(raw, source="<test>")


def test_shipped_example_config_is_valid():
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / "sleipnir.example.toml"
    cfg = SleipnirConfig.load(path)
    assert set(cfg.tiers) == set(Tier)


def test_successive_attempts_rotate_through_accepted_candidates():
    """A retry must not repeat an identical call.

    Free models rate-limit one at a time (observed live: one returned HTTP 429
    while its neighbour answered instantly), so re-issuing the same request
    fails the same way. Rotating also yields tier escalation for free, since the
    second-cheapest accepted model is usually the stronger one.
    """
    r = router(
        model("a/cheap", price=0.10, context=64_000),
        model("b/mid", price=0.20, context=64_000),
        model("c/dear", price=0.30, context=64_000),
    )
    task = make_task("t", tier=Tier.MECHANICAL)
    picks = [
        r.resolve(task, attempt=n, tier=Tier.MECHANICAL).model for n in (1, 2, 3, 4)
    ]
    assert picks == ["a/cheap", "b/mid", "c/dear", "a/cheap"]


def test_a_string_pattern_list_is_rejected_rather_than_split_into_letters():
    """`deny = "gpt-4"` must not become five one-character patterns.

    Router matching is substring-based, so a bare string silently degrades into
    a per-character pattern list. As a deny list that rejects every model; as an
    allow list it accepts almost every model, which is the dangerous direction —
    the allow list is what keeps a tier off models the operator excluded.
    """
    import tomllib

    for field in ("allow", "deny", "require_parameters", "prefer"):
        raw = tomllib.loads(CONFIG_TOML)
        raw["tiers"]["code"][field] = "meter"
        with pytest.raises(ConfigError, match="list of strings"):
            SleipnirConfig.from_dict(raw, source="<test>")


def test_pattern_lists_reject_non_string_and_empty_entries():
    import tomllib

    for value in ([""], ["ok", 3], [["nested"]]):
        raw = tomllib.loads(CONFIG_TOML)
        raw["tiers"]["code"]["deny"] = value
        with pytest.raises(ConfigError, match="list of strings"):
            SleipnirConfig.from_dict(raw, source="<test>")


def test_non_finite_numeric_config_is_a_config_error_not_a_crash():
    """TOML 1.0 can express `nan` and `inf`.

    `int(float("nan"))` raises ValueError and `int(float("inf"))` raises
    OverflowError; neither is a ConfigError, so an operator typo would surface
    as an unhandled traceback instead of a refusal naming the offending key.
    """
    import tomllib

    for literal in ("nan", "inf", "-inf"):
        raw = tomllib.loads(CONFIG_TOML)
        raw["backends"][1]["models"] = [{"id": "x/y", "context": float(literal)}]
        with pytest.raises(ConfigError, match="context"):
            SleipnirConfig.from_dict(raw, source="<test>")

    for literal in ("nan", "inf"):
        raw = tomllib.loads(CONFIG_TOML)
        raw["tiers"]["code"]["min_context"] = float(literal)
        with pytest.raises(ConfigError, match="min_context"):
            SleipnirConfig.from_dict(raw, source="<test>")
