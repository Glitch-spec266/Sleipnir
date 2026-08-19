"""Model catalogue: parsing, caching, and the refusal to guess."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from sleipnir.pricing import (
    IMPLAUSIBLE_PRICE_PER_MTOK,
    CatalogUnavailableError,
    ModelCatalog,
    parse_models,
)


def run(coro):
    return asyncio.run(coro)


def entry(model_id="vendor/m", prompt="0.000003", completion="0.000015", context=200000, **extra):
    payload = {
        "id": model_id,
        "context_length": context,
        "pricing": {"prompt": prompt, "completion": completion, "request": "0"},
        "architecture": {"modality": "text->text"},
        "top_provider": {"context_length": context, "max_completion_tokens": 32000},
        "supported_parameters": ["tools", "reasoning"],
    }
    payload.update(extra)
    return payload


def catalog_for(tmp_path: Path, payload, **kwargs) -> ModelCatalog:
    return ModelCatalog(
        cache_path=tmp_path / "models.json",
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
        ),
        **kwargs,
    )


# -- parsing ---------------------------------------------------------------


def test_prices_are_converted_from_per_token_to_per_mtok():
    """The documented units are USD per token. Getting this wrong is a
    1,000,000x error in either direction."""
    models, warnings = parse_models({"data": [entry()]})
    info = models["vendor/m"]
    assert info.input_per_mtok == pytest.approx(3.0)
    assert info.output_per_mtok == pytest.approx(15.0)
    assert warnings == []


def test_blended_price_weights_input_more_than_output():
    models, _ = parse_models({"data": [entry()]})
    info = models["vendor/m"]
    assert info.blended_per_mtok(output_ratio=0.25) == pytest.approx(3.0 * 0.75 + 15.0 * 0.25)


def test_models_without_a_usable_price_are_dropped_not_zeroed():
    """A model priced at zero is a model the router would always choose."""
    payload = {"data": [entry(model_id="a", prompt="not-a-number"), entry(model_id="b")]}
    models, warnings = parse_models(payload)
    assert set(models) == {"b"}
    assert any("unparseable" in w for w in warnings)


def test_models_with_no_pricing_block_are_dropped():
    bad = {"id": "x", "context_length": 1000}
    models, warnings = parse_models({"data": [bad]})
    assert models == {}
    assert any("no pricing block" in w for w in warnings)


def test_models_without_context_length_are_retained_as_unknown():
    broken = entry(model_id="c", context=0)
    broken["top_provider"] = {}
    models, warnings = parse_models({"data": [broken]})
    assert models["c"].context_length is None
    assert any("no context_length" in w for w in warnings)


def test_implausible_prices_are_rejected_as_a_unit_change():
    """If the API ever switched to per-million, every price would come out
    1e6x too high. Better to drop the model than to act on the number."""
    payload = {"data": [entry(model_id="huge", prompt=str(IMPLAUSIBLE_PRICE_PER_MTOK))]}
    models, warnings = parse_models(payload)
    assert models == {}
    assert any("implausible" in w for w in warnings)


def test_numeric_prices_are_accepted_as_well_as_strings():
    models, _ = parse_models({"data": [entry(prompt=0.000001, completion=0.000002)]})
    assert models["vendor/m"].input_per_mtok == pytest.approx(1.0)


def test_web_search_request_price_is_retained_without_unit_conversion():
    priced = entry()
    priced["pricing"]["web_search"] = "0.014"
    models, _ = parse_models({"data": [priced]})
    assert models["vendor/m"].web_search_cost_usd == pytest.approx(0.014)


def test_unrecognised_payload_is_reported():
    models, warnings = parse_models({"models": []})
    assert models == {}
    assert any("expected a 'data' list" in w for w in warnings)


# -- caching ---------------------------------------------------------------


def test_fetch_populates_the_cache(tmp_path: Path):
    catalog = catalog_for(tmp_path, {"data": [entry()]})
    snapshot = run(catalog.load())
    assert len(snapshot) == 1
    assert (tmp_path / "models.json").exists()


def test_fresh_cache_is_used_without_a_request(tmp_path: Path):
    calls: list = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [entry()]})

    catalog = ModelCatalog(
        cache_path=tmp_path / "models.json",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    run(catalog.load())
    run(catalog.load())
    assert len(calls) == 1, "a fresh cache must not re-fetch"


def test_expired_cache_triggers_a_refetch(tmp_path: Path):
    calls: list = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [entry()]})

    catalog = ModelCatalog(
        cache_path=tmp_path / "models.json",
        ttl_s=0.0,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    run(catalog.load())
    run(catalog.load())
    assert len(calls) == 2


def test_stale_cache_is_used_when_the_network_fails(tmp_path: Path):
    """An expired price beats no price — but the caller must be told."""
    cache = tmp_path / "models.json"
    cache.write_text(json.dumps({
        "data": [entry()],
        "_fetched_at": (datetime.now(UTC) - timedelta(days=3)).isoformat(),
    }))

    def boom(request):
        raise httpx.ConnectError("policy denied CONNECT")

    catalog = ModelCatalog(
        cache_path=cache,
        ttl_s=1.0,
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)),
    )
    snapshot = run(catalog.load())
    assert snapshot.stale is True
    assert len(snapshot) == 1
    assert any("live fetch failed" in w for w in snapshot.warnings)


def test_no_cache_and_no_network_refuses_to_guess(tmp_path: Path):
    def boom(request):
        raise httpx.ConnectError("nope")

    catalog = ModelCatalog(
        cache_path=tmp_path / "missing.json",
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)),
    )
    with pytest.raises(CatalogUnavailableError, match="refusing to guess"):
        run(catalog.load())


def test_corrupt_cache_is_treated_as_absent(tmp_path: Path):
    cache = tmp_path / "models.json"
    cache.write_text("{not json")
    catalog = catalog_for(tmp_path, {"data": [entry()]})
    catalog.cache_path = cache
    assert len(run(catalog.load())) == 1


def test_http_error_falls_back_rather_than_crashing(tmp_path: Path):
    cache = tmp_path / "models.json"
    cache.write_text(json.dumps({"data": [entry()], "_fetched_at": "2020-01-01T00:00:00+00:00"}))
    catalog = ModelCatalog(
        cache_path=cache,
        ttl_s=1.0,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503, text="down"))
        ),
    )
    assert run(catalog.load()).stale is True


# ---------------------------------------------------------------------------
# Adversarial catalogue input (ported from the parallel build's live findings)
# ---------------------------------------------------------------------------


def _entry(model_id: str, prompt: str, completion: str = "0.000001") -> dict:
    return {
        "id": model_id,
        "context_length": 200_000,
        "pricing": {"prompt": prompt, "completion": completion},
    }


def _parse(*entries: dict):
    from sleipnir.pricing import parse_models

    models, warnings = parse_models({"data": list(entries)})
    return models, warnings


def test_the_negative_price_sentinel_is_dropped():
    """Five live models return -1: 'cost depends which model is picked'.

    Unguarded that is -$1,000,000/Mtok, so they become the cheapest entries in
    the catalogue and win every routing decision forever. The implausible-price
    guard is a `>` test and does not catch it.
    """
    models, warnings = _parse(
        _entry("real/model", "0.000003"), _entry("openrouter/auto", "-1")
    )
    assert "real/model" in models
    assert "openrouter/auto" not in models
    assert any("openrouter/auto" in w for w in warnings)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_non_finite_prices_are_dropped(value):
    """float() parses all of these. NaN passes every comparison guard silently."""
    models, _ = _parse(_entry("real/model", "0.000003"), _entry("evil/model", value))
    assert "real/model" in models
    assert "evil/model" not in models


def test_the_implausible_price_guard_still_works():
    """Kept from the original: catches the API switching units to per-Mtok."""
    models, warnings = _parse(_entry("units/changed", "50000"))
    assert "units/changed" not in models
    assert any("implausible" in w for w in warnings)
