"""Phase 3 pricing tests.

The price book is the one place in Sleipnir where a number crosses a trust
boundary from the network. Every test here exists because a wrong number would
not raise — it would quietly produce a confident, incorrect budget, which is the
failure mode DESIGN.md's usage-record findings warn about most.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from sleipnir.pricing import (
    OPENROUTER_MODELS_URL,
    PriceBook,
    PriceFetchError,
    build_price_book,
    load_price_book,
    load_or_fetch_price_book,
    save_price_book,
)
from sleipnir.schema import TokenUsage

T0 = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


def catalogue(*entries: dict) -> dict:
    return {"data": list(entries)}


def entry(
    model_id: str,
    *,
    prompt: str = "0.000003",
    completion: str = "0.000015",
    cache_read: str | None = "0.0000003",
    cache_write: str | None = "0.00000375",
    cache_write_1h: str | None = "0.000006",
    context_length: int | None = 200_000,
    **extra,
) -> dict:
    pricing: dict[str, str] = {"prompt": prompt, "completion": completion}
    if cache_read is not None:
        pricing["input_cache_read"] = cache_read
    if cache_write is not None:
        pricing["input_cache_write"] = cache_write
    if cache_write_1h is not None:
        pricing["input_cache_write_1h"] = cache_write_1h
    out = {"id": model_id, "pricing": pricing, "context_length": context_length}
    out.update(extra)
    return out


# ---------------------------------------------------------------------------
# Parsing the catalogue
# ---------------------------------------------------------------------------


def test_per_token_prices_are_converted_to_per_million():
    """OpenRouter quotes per token; PriceSnapshot stores per million.

    Missing this factor under-reports every cost by 1e6 and would not raise.
    """
    book = build_price_book(catalogue(entry("vendor/model-a")), fetched_at=T0)
    snap = book.get("vendor/model-a")

    assert snap.input_per_mtok == pytest.approx(3.0)
    assert snap.output_per_mtok == pytest.approx(15.0)
    assert snap.cache_read_per_mtok == pytest.approx(0.3)
    assert snap.cache_write_5m_per_mtok == pytest.approx(3.75)
    assert snap.cache_write_1h_per_mtok == pytest.approx(6.0)


def test_absent_cache_prices_are_none_not_zero():
    """None means 'fall back to input price' (over-estimates, safe).

    Zero would mean 'cache reads are free', silently under-counting the channel
    that is 94% of measured window consumption.
    """
    book = build_price_book(
        catalogue(
            entry(
                "vendor/no-cache",
                cache_read=None,
                cache_write=None,
                cache_write_1h=None,
            )
        ),
        fetched_at=T0,
    )
    snap = book.get("vendor/no-cache")

    assert snap.cache_read_per_mtok is None
    assert snap.cache_write_5m_per_mtok is None
    assert snap.cache_write_1h_per_mtok is None

    # And the fallback must over-estimate rather than under-estimate reads.
    usage = TokenUsage(input_tokens=0, output_tokens=0, cache_read_tokens=1_000_000)
    assert snap.cost_usd(usage) == pytest.approx(3.0)


def test_free_models_price_at_zero_and_are_kept():
    book = build_price_book(
        catalogue(
            entry(
                "vendor/model:free",
                prompt="0",
                completion="0",
                cache_read="0",
                cache_write=None,
                cache_write_1h=None,
            )
        ),
        fetched_at=T0,
    )
    snap = book.get("vendor/model:free")
    assert snap.input_per_mtok == 0.0
    assert snap.output_per_mtok == 0.0
    assert snap.cost_usd(TokenUsage(input_tokens=5_000, output_tokens=5_000)) == 0.0


def test_malformed_entries_are_skipped_and_warned_not_fatal():
    """The catalogue is untrusted network input; one bad row must not kill a run."""
    book = build_price_book(
        catalogue(
            entry("vendor/good"),
            {"id": "vendor/no-pricing"},
            {"pricing": {"prompt": "1", "completion": "1"}},  # no id
            entry("vendor/bad-number", prompt="not-a-number"),
            {"id": "vendor/negative", "pricing": {"prompt": "-1", "completion": "1"}},
            "not-even-a-dict",
        ),
        fetched_at=T0,
    )

    assert book.get("vendor/good") is not None
    assert set(book.models()) == {"vendor/good"}
    assert len(book.warnings) == 5
    assert any("vendor/bad-number" in w for w in book.warnings)


def test_unknown_model_raises_rather_than_guessing():
    book = build_price_book(catalogue(entry("vendor/known")), fetched_at=T0)
    with pytest.raises(KeyError):
        book.get("vendor/unknown")


def test_empty_catalogue_is_an_error_not_an_empty_book():
    """An empty book would price every model at nothing. Fail loudly instead."""
    with pytest.raises(PriceFetchError):
        build_price_book(catalogue(), fetched_at=T0)


def test_context_length_is_carried_for_fit_decisions():
    book = build_price_book(
        catalogue(entry("vendor/small", context_length=8_000)), fetched_at=T0
    )
    assert book.get("vendor/small").context_window == 8_000


def test_zero_or_missing_context_length_becomes_none():
    """context_window is gt=0 in the schema; 0 must not be coerced through."""
    book = build_price_book(
        catalogue(
            entry("vendor/zero", context_length=0),
            entry("vendor/absent", context_length=None),
        ),
        fetched_at=T0,
    )
    assert book.get("vendor/zero").context_window is None
    assert book.get("vendor/absent").context_window is None


# ---------------------------------------------------------------------------
# Snapshot round-trip and staleness
# ---------------------------------------------------------------------------


def test_snapshot_round_trips_through_disk(tmp_path):
    book = build_price_book(
        catalogue(entry("vendor/a"), entry("vendor/b")), fetched_at=T0
    )
    path = tmp_path / "prices.json"
    save_price_book(book, path)
    reloaded = load_price_book(path)

    assert set(reloaded.models()) == {"vendor/a", "vendor/b"}
    assert reloaded.fetched_at == T0
    assert reloaded.get("vendor/a").input_per_mtok == pytest.approx(3.0)


def test_corrupt_snapshot_raises_rather_than_returning_empty(tmp_path):
    path = tmp_path / "prices.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(PriceFetchError):
        load_price_book(path)


def test_age_is_measured_from_fetched_at():
    book = build_price_book(catalogue(entry("vendor/a")), fetched_at=T0)
    assert book.age_at(T0 + timedelta(hours=2)) == timedelta(hours=2)
    assert book.is_stale(T0 + timedelta(hours=2), ttl=timedelta(hours=1))
    assert not book.is_stale(T0 + timedelta(minutes=30), ttl=timedelta(hours=1))


# ---------------------------------------------------------------------------
# Fetch, with the network mocked at the transport
# ---------------------------------------------------------------------------


def _factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def load_or_fetch(**kwargs) -> PriceBook:
    """Sync wrapper, matching the asyncio.run idiom used by the other suites.

    Keeps pytest-asyncio out of the dependency list.
    """
    return asyncio.run(load_or_fetch_price_book(**kwargs))


def test_fetch_hits_the_public_endpoint_without_auth(tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=catalogue(entry("vendor/a")))

    book = load_or_fetch(
        cache_path=tmp_path / "prices.json",
        now=T0,
        client_factory=_factory(handler),
    )

    assert seen["url"] == OPENROUTER_MODELS_URL
    # The endpoint is public. Sending a key would leak it for no benefit.
    assert seen["auth"] is None
    assert book.get("vendor/a").input_per_mtok == pytest.approx(3.0)
    assert (tmp_path / "prices.json").exists()


def test_fresh_cache_is_used_without_touching_the_network(tmp_path):
    path = tmp_path / "prices.json"
    save_price_book(build_price_book(catalogue(entry("vendor/cached")), T0), path)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("network must not be touched when the cache is fresh")

    book = load_or_fetch(
        cache_path=path,
        now=T0 + timedelta(minutes=5),
        ttl=timedelta(hours=6),
        client_factory=_factory(handler),
    )
    assert set(book.models()) == {"vendor/cached"}


def test_network_failure_falls_back_to_stale_snapshot_with_a_warning(tmp_path):
    path = tmp_path / "prices.json"
    save_price_book(build_price_book(catalogue(entry("vendor/cached")), T0), path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    book = load_or_fetch(
        cache_path=path,
        now=T0 + timedelta(days=30),
        ttl=timedelta(hours=6),
        client_factory=_factory(handler),
    )

    assert set(book.models()) == {"vendor/cached"}
    assert book.stale is True
    assert any("stale" in w.lower() for w in book.warnings)


def test_network_failure_with_no_snapshot_raises(tmp_path):
    """Never invent prices. No data and no cache means no run."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network")

    with pytest.raises(PriceFetchError):
        load_or_fetch(
            cache_path=tmp_path / "missing.json",
            now=T0,
            client_factory=_factory(handler),
        )


def test_http_error_status_is_a_fetch_error(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    with pytest.raises(PriceFetchError):
        load_or_fetch(
            cache_path=tmp_path / "missing.json",
            now=T0,
            client_factory=_factory(handler),
        )


def test_a_successful_fetch_overwrites_the_snapshot(tmp_path):
    path = tmp_path / "prices.json"
    save_price_book(build_price_book(catalogue(entry("vendor/old")), T0), path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=catalogue(entry("vendor/new")))

    later = T0 + timedelta(days=1)
    book = load_or_fetch(
        cache_path=path,
        now=later,
        ttl=timedelta(hours=6),
        client_factory=_factory(handler),
    )

    assert set(book.models()) == {"vendor/new"}
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["fetched_at"].startswith("2026-08-19")


def test_price_book_is_not_populated_from_training_data():
    """The only constructors take explicit data. There is no default catalogue."""
    assert not hasattr(PriceBook, "default")
    assert not hasattr(PriceBook, "builtin")


# ---------------------------------------------------------------------------
# Adversarial input — the catalogue is untrusted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["Infinity", "-Infinity", "NaN", "1e400", "-1e400"])
def test_non_finite_prices_are_rejected(value):
    """float() happily parses these; none of them is a price.

    NaN is the dangerous one: every comparison against it is False, so it passes
    a `>= 0` guard and then makes any cost ordering built on it meaningless.
    """
    with pytest.raises(PriceFetchError):
        build_price_book(
            catalogue(entry("vendor/evil", prompt=value)),
            fetched_at=T0,
        )


def test_the_openrouter_negative_sentinel_is_rejected():
    """openrouter/auto prices at -1: 'depends which model runs'.

    Unguarded, -1 per token is -$1,000,000 per Mtok, so these would score as
    infinitely cheap and win every routing decision forever.
    """
    book = build_price_book(
        catalogue(entry("vendor/real"), entry("openrouter/auto", prompt="-1")),
        fetched_at=T0,
    )
    assert set(book.models()) == {"vendor/real"}
    assert any("openrouter/auto" in w for w in book.warnings)
