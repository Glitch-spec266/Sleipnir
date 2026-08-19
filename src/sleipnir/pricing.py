"""Live model catalogue from OpenRouter, cached with a TTL.

Nothing in this module hardcodes a model name, a context window, or a price.
Every one of those is fetched at runtime and cached, because a price baked into
source is wrong the moment a provider changes it and wrong *silently*.

The response shape and pricing sentinels were verified against the live
OpenRouter catalogue on 2026-08-18. Parsing remains defensive: it tolerates
optional metadata, reports what it could not understand, and never silently
substitutes a missing price with zero. A zeroed missing price would tell the
budget governor that every model is free.
"""

from __future__ import annotations

import math

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_MODELS_URL = "https://openrouter.ai/api/v1/models"
DEFAULT_TTL_S = 6 * 60 * 60
DEFAULT_CACHE_PATH = Path.home() / ".cache" / "sleipnir" / "openrouter-models.json"

#: OpenRouter documents `pricing.*` as USD **per token**, so a per-million rate
#: is that number times 1e6. If the API ever switched to per-million, every
#: price would come out 1,000,000x too high — this ceiling catches that rather
#: than letting the governor act on a nonsense number.
IMPLAUSIBLE_PRICE_PER_MTOK = 10_000.0

ClientFactory = Callable[[], httpx.AsyncClient]


class CatalogUnavailableError(RuntimeError):
    """No live data and no cache. The router must not guess prices."""


@dataclass(slots=True, frozen=True)
class ModelInfo:
    id: str
    context_length: int | None
    input_per_mtok: float
    output_per_mtok: float
    cache_read_per_mtok: float | None = None
    cache_write_per_mtok: float | None = None
    request_cost_usd: float = 0.0
    max_output_tokens: int | None = None
    supported_parameters: tuple[str, ...] = ()
    modality: str = ""

    def blended_per_mtok(self, output_ratio: float = 0.25) -> float:
        """One comparable number for ranking.

        Tasks are input-heavy, so a plain average over-weights output price and
        would rank a cheap-input/expensive-output model worse than it deserves.
        """
        return (
            self.input_per_mtok * (1.0 - output_ratio)
            + self.output_per_mtok * output_ratio
        )


@dataclass(slots=True)
class CatalogSnapshot:
    models: dict[str, ModelInfo]
    fetched_at: datetime
    source: str
    stale: bool = False
    warnings: list[str] = field(default_factory=list)

    def get(self, model_id: str) -> ModelInfo | None:
        return self.models.get(model_id)

    def __len__(self) -> int:
        return len(self.models)


class ModelCatalog:
    """Fetches and caches the OpenRouter model list."""

    def __init__(
        self,
        *,
        url: str = DEFAULT_MODELS_URL,
        cache_path: Path = DEFAULT_CACHE_PATH,
        ttl_s: float = DEFAULT_TTL_S,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.url = url
        self.cache_path = cache_path
        self.ttl_s = ttl_s
        self._client_factory = client_factory

    async def load(self, *, force: bool = False) -> CatalogSnapshot:
        """Fresh cache, else network, else stale cache, else raise.

        Falling back to a stale cache is deliberate: an expired price is a
        far better basis for a budget decision than no price, and the snapshot
        says `stale=True` so the caller can surface it.
        """
        cached = self._read_cache()
        if not force and cached is not None and self._age(cached) < self.ttl_s:
            return self._snapshot(cached, source=f"cache:{self.cache_path}")

        try:
            payload = await self._fetch()
        except Exception as exc:
            if cached is None:
                raise CatalogUnavailableError(
                    f"could not fetch {self.url} ({type(exc).__name__}: {exc}) and no "
                    f"cache exists at {self.cache_path}; refusing to guess prices"
                ) from exc
            snapshot = self._snapshot(cached, source=f"stale-cache:{self.cache_path}")
            snapshot.stale = True
            snapshot.warnings.append(
                f"live fetch failed ({type(exc).__name__}: {exc}); using cache from "
                f"{snapshot.fetched_at.isoformat()}"
            )
            return snapshot

        self._write_cache(payload)
        return self._snapshot(payload, source=self.url)

    async def _fetch(self) -> dict[str, Any]:
        client = self._client_factory() if self._client_factory else httpx.AsyncClient(
            timeout=httpx.Timeout(30.0)
        )
        try:
            response = await client.get(self.url)
            response.raise_for_status()
            payload = response.json()
        finally:
            await client.aclose()
        payload["_fetched_at"] = datetime.now(UTC).isoformat()
        return payload

    # -- cache ---------------------------------------------------------------

    def _read_cache(self) -> dict[str, Any] | None:
        if not self.cache_path.exists():
            return None
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _write_cache(self, payload: dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(self.cache_path)  # atomic: never leave a half-written cache

    @staticmethod
    def _age(payload: dict[str, Any]) -> float:
        stamp = payload.get("_fetched_at")
        if not stamp:
            return float("inf")
        try:
            return time.time() - datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            return float("inf")

    # -- parsing -------------------------------------------------------------

    def _snapshot(self, payload: dict[str, Any], *, source: str) -> CatalogSnapshot:
        models, warnings = parse_models(payload)
        stamp = payload.get("_fetched_at")
        try:
            fetched_at = datetime.fromisoformat(stamp) if stamp else datetime.now(UTC)
        except ValueError:
            fetched_at = datetime.now(UTC)
        return CatalogSnapshot(
            models=models, fetched_at=fetched_at, source=source, warnings=warnings
        )


def parse_models(payload: dict[str, Any]) -> tuple[dict[str, ModelInfo], list[str]]:
    """Parse the models response, reporting every entry it could not use.

    Entries missing a usable price are DROPPED, not defaulted to zero: a model
    the router cannot price is a model the router must not choose.
    """
    models: dict[str, ModelInfo] = {}
    warnings: list[str] = []

    entries = payload.get("data")
    if not isinstance(entries, list):
        return {}, [f"unrecognised payload: expected a 'data' list, got {type(payload.get('data')).__name__}"]

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue

        pricing = entry.get("pricing")
        if not isinstance(pricing, dict):
            warnings.append(f"{model_id}: no pricing block; dropped")
            continue

        prompt = _per_mtok(pricing.get("prompt"))
        completion = _per_mtok(pricing.get("completion"))
        if prompt is None or completion is None:
            warnings.append(f"{model_id}: unparseable prompt/completion price; dropped")
            continue
        if prompt < 0 or completion < 0:
            # OpenRouter marks its meta-models (openrouter/auto, fusion,
            # pareto-code, bodybuilder, auto-beta — five of them live on
            # 2026-08-18) with -1, meaning "cost depends which model this
            # routes to". Unguarded that is -$1,000,000/Mtok, which makes them
            # the cheapest entries in the catalogue and wins every routing
            # decision forever. The implausible-price guard below is a `>`
            # test and does not catch it.
            warnings.append(
                f"{model_id}: negative price ({min(prompt, completion):.0f}/Mtok) is a "
                "sentinel for 'cost depends which model is picked'; dropped"
            )
            continue
        if prompt > IMPLAUSIBLE_PRICE_PER_MTOK or completion > IMPLAUSIBLE_PRICE_PER_MTOK:
            warnings.append(
                f"{model_id}: price of ${max(prompt, completion):.0f}/Mtok is implausible — "
                "the API's pricing units may have changed from per-token; dropped"
            )
            continue

        top = entry.get("top_provider") if isinstance(entry.get("top_provider"), dict) else {}
        context = _first_int(entry, ("context_length",)) or _first_int(top, ("context_length",))
        if not context:
            # Unknown is not the same as too small. Retain a priced model and
            # let explainability surface the uncertainty; excluding it here
            # quietly turns optional catalogue metadata into a hard policy.
            warnings.append(f"{model_id}: no context_length; retained with unknown context")

        architecture = entry.get("architecture") if isinstance(entry.get("architecture"), dict) else {}
        params = entry.get("supported_parameters")

        models[model_id] = ModelInfo(
            id=model_id,
            context_length=context,
            input_per_mtok=prompt,
            output_per_mtok=completion,
            cache_read_per_mtok=_per_mtok(pricing.get("input_cache_read")),
            cache_write_per_mtok=_per_mtok(pricing.get("input_cache_write")),
            request_cost_usd=_float(pricing.get("request")) or 0.0,
            max_output_tokens=_first_int(top, ("max_completion_tokens",)),
            supported_parameters=tuple(params) if isinstance(params, list) else (),
            modality=str(architecture.get("modality") or ""),
        )

    if not models and entries:
        warnings.append(f"all {len(entries)} catalogue entries were unusable")
    return models, warnings


def _float(value: Any) -> float | None:
    """Prices arrive as strings in the documented shape; accept numbers too."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        # "Infinity", "1e400" and "NaN" all survive float() and none is a price.
        # NaN is the dangerous one: every comparison against it is False, so it
        # slips past both the negative and the implausible-price guards below
        # and then silently destroys any ordering built on it.
        return parsed if math.isfinite(parsed) else None
    return None


def _per_mtok(value: Any) -> float | None:
    raw = _float(value)
    return None if raw is None else raw * 1_000_000


def _first_int(node: Any, keys: tuple[str, ...]) -> int | None:
    if not isinstance(node, dict):
        return None
    for key in keys:
        value = node.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            return int(value)
    return None


__all__ = [
    "DEFAULT_CACHE_PATH",
    "DEFAULT_MODELS_URL",
    "DEFAULT_TTL_S",
    "IMPLAUSIBLE_PRICE_PER_MTOK",
    "CatalogSnapshot",
    "CatalogUnavailableError",
    "ModelCatalog",
    "ModelInfo",
    "parse_models",
]
