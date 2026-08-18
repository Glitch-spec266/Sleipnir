"""Configuration: backends and per-tier routing policy.

TOML via stdlib `tomllib` — no dependency. The whole point of this file is that
*model choice lives in configuration, not in code*. Sleipnir ships no model
names and no prices; it ships the policy language you express them in.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sleipnir.schema import Adapter, BillingMode, Tier

DEFAULT_CONFIG_NAMES = ("sleipnir.toml", ".sleipnir.toml")


class ConfigError(ValueError):
    """Configuration is unusable. Always raised before anything is dispatched."""


@dataclass(slots=True, frozen=True)
class ModelOption:
    """A model a backend can offer, with optional locally-known metadata.

    `context` and `price_per_mtok` are escape hatches for subscription models
    that do not appear in the OpenRouter catalogue. They are hints supplied by
    the operator about their own plan — not prices baked into Sleipnir.
    """

    id: str
    context: int | None = None
    price_per_mtok: float | None = None


@dataclass(slots=True, frozen=True)
class Backend:
    name: str
    adapter: Adapter
    billing: BillingMode
    #: Empty means "every model in the live catalogue is a candidate".
    models: tuple[ModelOption, ...] = ()
    #: Fixed token cost paid on every dispatch regardless of task size.
    #: Measured at ~30,000 for `claude -p` — see DESIGN.md. This is why a
    #: trivial task can cost more to delegate than to skip.
    dispatch_overhead_tokens: int = 0

    @property
    def uses_catalog(self) -> bool:
        return not self.models


@dataclass(slots=True, frozen=True)
class TierPolicy:
    """What a tier requires and which backends it prefers, in order."""

    prefer: tuple[str, ...] = ()
    min_context: int = 0
    max_price_per_mtok: float | None = None
    require_parameters: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()  # substring/prefix filters on model id
    deny: tuple[str, ...] = ()
    #: Share of tokens expected to be output, used to blend a comparable price.
    output_ratio: float = 0.25


@dataclass(slots=True)
class SleipnirConfig:
    backends: dict[str, Backend] = field(default_factory=dict)
    tiers: dict[Tier, TierPolicy] = field(default_factory=dict)
    concurrency: int = 3
    catalog_ttl_s: float = 6 * 60 * 60
    catalog_url: str | None = None
    catalog_cache_path: Path | None = None
    #: Fraction of the window the governor tries to leave unspent.
    reserve_fraction: float = 0.10
    window_tokens_limit: int | None = None
    metered_budget_usd: float | None = None

    def policy(self, tier: Tier) -> TierPolicy:
        if tier not in self.tiers:
            raise ConfigError(f"no policy configured for tier {tier.value!r}")
        return self.tiers[tier]

    @classmethod
    def load(cls, path: Path) -> SleipnirConfig:
        if not path.exists():
            raise ConfigError(f"config not found: {path}")
        try:
            raw = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{path}: {exc}") from exc
        return cls.from_dict(raw, source=str(path))

    @classmethod
    def from_dict(cls, raw: dict[str, Any], *, source: str = "<dict>") -> SleipnirConfig:
        backends = _parse_backends(raw.get("backends"), source)
        tiers = _parse_tiers(raw.get("tiers"), backends, source)

        missing = [tier.value for tier in Tier if tier not in tiers]
        if missing:
            # Fail at load, not at dispatch. A tier with no policy is a run that
            # dies partway through with half the plan already paid for.
            raise ConfigError(
                f"{source}: no [tiers.*] policy for: {', '.join(sorted(missing))}"
            )

        return cls(
            backends=backends,
            tiers=tiers,
            concurrency=int(raw.get("concurrency", 3)),
            catalog_ttl_s=float(raw.get("catalog_ttl_s", 6 * 60 * 60)),
            catalog_url=raw.get("catalog_url"),
            catalog_cache_path=(
                Path(raw["catalog_cache_path"]) if raw.get("catalog_cache_path") else None
            ),
            reserve_fraction=float(raw.get("reserve_fraction", 0.10)),
            window_tokens_limit=_opt_int(raw.get("window_tokens_limit")),
            metered_budget_usd=_opt_float(raw.get("metered_budget_usd")),
        )

    @staticmethod
    def discover(start: Path) -> Path | None:
        for name in DEFAULT_CONFIG_NAMES:
            candidate = start / name
            if candidate.exists():
                return candidate
        return None


def _parse_backends(raw: Any, source: str) -> dict[str, Backend]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{source}: at least one [[backends]] entry is required")

    backends: dict[str, Backend] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: each [[backends]] entry must be a table")
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"{source}: every backend needs a name")
        if name in backends:
            raise ConfigError(f"{source}: duplicate backend {name!r}")

        try:
            adapter = Adapter(entry.get("adapter"))
        except ValueError as exc:
            raise ConfigError(
                f"{source}: backend {name!r} has unknown adapter {entry.get('adapter')!r}; "
                f"expected one of {[a.value for a in Adapter]}"
            ) from exc
        try:
            billing = BillingMode(entry.get("billing", "metered"))
        except ValueError as exc:
            raise ConfigError(
                f"{source}: backend {name!r} has unknown billing {entry.get('billing')!r}"
            ) from exc

        backends[name] = Backend(
            name=name,
            adapter=adapter,
            billing=billing,
            models=_parse_models(entry.get("models"), name, source),
            dispatch_overhead_tokens=int(entry.get("dispatch_overhead_tokens", 0)),
        )
    return backends


def _parse_models(raw: Any, backend: str, source: str) -> tuple[ModelOption, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"{source}: backend {backend!r} models must be a list")
    options: list[ModelOption] = []
    for item in raw:
        if isinstance(item, str):
            options.append(ModelOption(id=item))
        elif isinstance(item, dict) and isinstance(item.get("id"), str):
            options.append(
                ModelOption(
                    id=item["id"],
                    context=_opt_int(item.get("context")),
                    price_per_mtok=_opt_float(item.get("price_per_mtok")),
                )
            )
        else:
            raise ConfigError(
                f"{source}: backend {backend!r} has a model entry that is neither a "
                f"string nor a table with an id: {item!r}"
            )
    return tuple(options)


def _parse_tiers(
    raw: Any, backends: dict[str, Backend], source: str
) -> dict[Tier, TierPolicy]:
    if not isinstance(raw, dict):
        raise ConfigError(f"{source}: a [tiers] table is required")

    tiers: dict[Tier, TierPolicy] = {}
    for key, entry in raw.items():
        try:
            tier = Tier(key)
        except ValueError as exc:
            raise ConfigError(
                f"{source}: unknown tier {key!r}; the five tiers are "
                f"{[t.value for t in Tier]} and adding one is an architecture decision"
            ) from exc
        if not isinstance(entry, dict):
            raise ConfigError(f"{source}: [tiers.{key}] must be a table")

        prefer = tuple(entry.get("prefer", ()) or ())
        unknown = [name for name in prefer if name not in backends]
        if unknown:
            raise ConfigError(
                f"{source}: [tiers.{key}] prefers unknown backend(s) {unknown}; "
                f"known backends are {sorted(backends)}"
            )
        if not prefer:
            raise ConfigError(f"{source}: [tiers.{key}] must name at least one backend")

        tiers[tier] = TierPolicy(
            prefer=prefer,
            min_context=int(entry.get("min_context", 0)),
            max_price_per_mtok=_opt_float(entry.get("max_price_per_mtok")),
            require_parameters=tuple(entry.get("require_parameters", ()) or ()),
            allow=tuple(entry.get("allow", ()) or ()),
            deny=tuple(entry.get("deny", ()) or ()),
            output_ratio=float(entry.get("output_ratio", 0.25)),
        )
    return tiers


def _opt_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


__all__ = [
    "DEFAULT_CONFIG_NAMES",
    "Backend",
    "ConfigError",
    "ModelOption",
    "SleipnirConfig",
    "TierPolicy",
]
