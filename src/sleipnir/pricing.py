"""Model prices, fetched live and cached to disk.

Prices are never populated from training data. The only inputs are the
OpenRouter models endpoint and a snapshot this module wrote earlier. If neither
is available the run fails rather than guessing, because a confident wrong price
produces a confident wrong budget, and the governor has no way to notice.

The endpoint is public: it takes no API key, and this module deliberately sends
none. Attaching a bearer token would leak it for no benefit.

Two conversions are load-bearing:

* OpenRouter quotes **per token** as decimal strings; ``PriceSnapshot`` stores
  **per million tokens** as floats. The 1e6 factor is applied here exactly once.
* A cache price that is *absent* becomes ``None``, never ``0.0``. ``None`` makes
  ``PriceSnapshot.cost_usd`` fall back to the input price, which over-estimates
  reads — the safe direction. ``0.0`` would assert that cache reads are free,
  silently under-counting the channel measured at 94% of window consumption.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import httpx

from sleipnir.schema import PriceSnapshot

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

#: Source label stamped onto every snapshot fetched from the live catalogue.
SOURCE_LIVE = "openrouter/models"

#: Prices move slowly; a run should not re-fetch on every dispatch.
DEFAULT_TTL = timedelta(hours=6)

DEFAULT_TIMEOUT_S = 30.0

#: Per-token -> per-million-token.
_PER_MTOK = 1_000_000

#: Catalogue pricing key -> PriceSnapshot field.
_PRICE_FIELDS: tuple[tuple[str, str], ...] = (
    ("prompt", "input_per_mtok"),
    ("completion", "output_per_mtok"),
    ("input_cache_read", "cache_read_per_mtok"),
    ("input_cache_write", "cache_write_5m_per_mtok"),
    ("input_cache_write_1h", "cache_write_1h_per_mtok"),
)

#: Bad rows reported individually, then capped. A catalogue that is wholly
#: malformed should not produce hundreds of near-identical warnings.
MAX_WARNINGS = 20


class PriceFetchError(RuntimeError):
    """No trustworthy prices are available. Never raised to mean 'use zero'."""


def _as_price(raw: Any) -> float | None:
    """Parse one per-token price string into per-million-token float.

    Returns ``None`` for absent values so the caller can distinguish "not
    priced" from "priced at zero". Raises ``ValueError`` for junk.
    """
    if raw is None or raw == "":
        return None
    value = float(raw)  # raises ValueError on junk, which the caller catches
    if not math.isfinite(value):
        # "Infinity", "1e400" and "NaN" all survive float(). None of them is a
        # price. NaN is the dangerous one: every comparison against it is False,
        # so it neither sorts nor fails a >= 0 guard, and a NaN cost silently
        # makes the router's ordering meaningless.
        raise ValueError(f"non-finite price {raw!r}")
    if value < 0:
        # OpenRouter uses -1 as a sentinel on its meta-models (openrouter/auto
        # and friends) to mean "cost depends which model is picked". Left
        # unguarded, -1 per token is -$1,000,000 per Mtok, and those models
        # would score as infinitely cheap and win every route forever.
        raise ValueError(f"negative price {value!r}")
    return value * _PER_MTOK


@dataclass(slots=True)
class PriceBook:
    """Every model price known at ``fetched_at``.

    ``stale`` is True only when this book was served from disk after a failed
    fetch. A book inside its TTL is not stale; it is simply cached.
    """

    fetched_at: datetime
    source: str
    snapshots: Mapping[str, PriceSnapshot]
    warnings: list[str] = field(default_factory=list)
    stale: bool = False

    def get(self, model: str) -> PriceSnapshot:
        """Price for ``model``.

        Raises ``KeyError`` for an unknown model. There is deliberately no
        default and no nearest-match: pricing a model we have no data for is
        the exact failure this module exists to prevent.
        """
        try:
            return self.snapshots[model]
        except KeyError:
            raise KeyError(
                f"no price for model {model!r} in {self.source} "
                f"(fetched {self.fetched_at.isoformat()}); refusing to guess"
            ) from None

    def has(self, model: str) -> bool:
        return model in self.snapshots

    def models(self) -> Iterable[str]:
        return self.snapshots.keys()

    def age_at(self, now: datetime) -> timedelta:
        return now - self.fetched_at

    def is_stale(self, now: datetime, *, ttl: timedelta = DEFAULT_TTL) -> bool:
        return self.age_at(now) > ttl

    def to_dict(self) -> dict[str, Any]:
        return {
            "fetched_at": self.fetched_at.isoformat(),
            "source": self.source,
            "warnings": list(self.warnings),
            "models": {
                model: snap.model_dump(mode="json")
                for model, snap in self.snapshots.items()
            },
        }


def build_price_book(
    catalogue: Mapping[str, Any],
    fetched_at: datetime,
    *,
    source: str = SOURCE_LIVE,
) -> PriceBook:
    """Parse an OpenRouter ``/models`` payload into a price book.

    The payload is untrusted network input, so a malformed row is skipped with a
    warning rather than aborting the run — one bad entry among four hundred must
    not stop a build. An *entirely* unusable payload does raise, because a book
    with no models would price everything at nothing.
    """
    rows = catalogue.get("data") if isinstance(catalogue, Mapping) else None
    if not isinstance(rows, list):
        raise PriceFetchError(
            f"price catalogue from {source} has no 'data' list; refusing to guess"
        )

    snapshots: dict[str, PriceSnapshot] = {}
    warnings: list[str] = []

    def warn(message: str) -> None:
        if len(warnings) < MAX_WARNINGS:
            warnings.append(message)

    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            warn(f"row {index}: not an object, skipped")
            continue

        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            warn(f"row {index}: missing 'id', skipped")
            continue

        pricing = row.get("pricing")
        if not isinstance(pricing, Mapping):
            warn(f"{model_id}: missing 'pricing', skipped")
            continue

        try:
            values = {
                field_name: _as_price(pricing.get(key))
                for key, field_name in _PRICE_FIELDS
            }
        except (TypeError, ValueError) as exc:
            warn(f"{model_id}: unparseable price ({exc}), skipped")
            continue

        # The two mandatory channels. A model without them cannot be costed.
        if values["input_per_mtok"] is None or values["output_per_mtok"] is None:
            warn(f"{model_id}: missing prompt/completion price, skipped")
            continue

        # context_window is gt=0 in the schema, so 0 and absent both mean
        # "unknown" rather than "a zero-token window".
        raw_context = row.get("context_length")
        context = (
            int(raw_context)
            if isinstance(raw_context, (int, float)) and raw_context > 0
            else None
        )

        try:
            snapshots[model_id] = PriceSnapshot(
                source=source,
                fetched_at=fetched_at,
                model=model_id,
                context_window=context,
                **values,
            )
        except ValueError as exc:  # pydantic validation, e.g. a negative slipped
            warn(f"{model_id}: rejected by schema ({exc}), skipped")

    if not snapshots:
        raise PriceFetchError(
            f"price catalogue from {source} yielded no usable models "
            f"({len(rows)} rows, {len(warnings)} rejected); refusing to guess"
        )

    return PriceBook(
        fetched_at=fetched_at,
        source=source,
        snapshots=snapshots,
        warnings=warnings,
    )


def save_price_book(book: PriceBook, path: Path) -> None:
    """Write the snapshot, creating the cache directory if needed."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(book.to_dict(), indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic, so a crash never leaves a half-written price file


def load_price_book(path: Path) -> PriceBook:
    """Read a snapshot written by :func:`save_price_book`.

    A corrupt file raises rather than degrading to an empty book, for the same
    reason an empty catalogue does.
    """
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshots = {
            model: PriceSnapshot.model_validate(data)
            for model, data in payload["models"].items()
        }
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise PriceFetchError(f"unusable price snapshot at {path}: {exc}") from exc

    if not snapshots:
        raise PriceFetchError(f"price snapshot at {path} contains no models")

    return PriceBook(
        fetched_at=fetched_at,
        source=payload.get("source", SOURCE_LIVE),
        snapshots=snapshots,
        warnings=list(payload.get("warnings", [])),
    )


ClientFactory = Callable[[], httpx.AsyncClient]


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_S)


async def fetch_price_book(
    *,
    url: str = OPENROUTER_MODELS_URL,
    now: datetime | None = None,
    client_factory: ClientFactory | None = None,
) -> PriceBook:
    """Fetch the live catalogue. No API key is sent — the endpoint is public."""
    factory = client_factory or _default_client_factory
    fetched_at = now or datetime.now(UTC)

    try:
        async with factory() as client:
            response = await client.get(url)
            if response.status_code != 200:
                raise PriceFetchError(
                    f"price fetch from {url} returned HTTP {response.status_code}"
                )
            payload = response.json()
    except PriceFetchError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        raise PriceFetchError(f"price fetch from {url} failed: {exc}") from exc

    return build_price_book(payload, fetched_at)


async def load_or_fetch_price_book(
    *,
    cache_path: Path,
    now: datetime | None = None,
    ttl: timedelta = DEFAULT_TTL,
    url: str = OPENROUTER_MODELS_URL,
    client_factory: ClientFactory | None = None,
) -> PriceBook:
    """Return prices, preferring a fresh snapshot and falling back to the network.

    Order of preference:

    1. A cached snapshot inside ``ttl`` — no network at all.
    2. A live fetch, which overwrites the snapshot.
    3. The cached snapshot even though it is stale, flagged and warned about.
    4. Failure. There is no fourth option that involves inventing a number.
    """
    cache_path = Path(cache_path)
    observed_at = now or datetime.now(UTC)

    cached: PriceBook | None = None
    if cache_path.exists():
        try:
            cached = load_price_book(cache_path)
        except PriceFetchError:
            # A corrupt cache is not fatal here — we can still fetch. It becomes
            # fatal only if the fetch also fails, which the fallback below hits.
            cached = None
        else:
            if not cached.is_stale(observed_at, ttl=ttl):
                return cached

    try:
        book = await fetch_price_book(
            url=url, now=observed_at, client_factory=client_factory
        )
    except PriceFetchError as exc:
        if cached is None:
            raise PriceFetchError(
                f"{exc}; and no usable snapshot at {cache_path}. "
                "Refusing to run with invented prices."
            ) from exc
        age = cached.age_at(observed_at)
        cached.stale = True
        cached.warnings = [
            *cached.warnings,
            f"price fetch failed ({exc}); using stale snapshot "
            f"from {cached.fetched_at.isoformat()} ({age} old)",
        ]
        return cached

    save_price_book(book, cache_path)
    return book
