"""Configuration: backends and per-tier routing policy.

TOML via stdlib `tomllib` — no dependency. The whole point of this file is that
*model choice lives in configuration, not in code*. Sleipnir ships no model
names and no prices; it ships the policy language you express them in.
"""

from __future__ import annotations

import json
import math
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sleipnir.schema import Adapter, BillingMode, Tier

DEFAULT_CONFIG_NAMES = ("sleipnir.toml", ".sleipnir.toml")


def _toml_scalar(value: str | int | float) -> str:
    return json.dumps(value, ensure_ascii=True) if isinstance(value, str) else repr(value)


def _toml_strings(values: tuple[str, ...]) -> str:
    return "[" + ", ".join(_toml_scalar(value) for value in values) + "]"


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
    models: tuple[ModelOption, ...] = ()
    #: Fixed token cost paid on every dispatch regardless of task size.
    #: Measured at ~30,000 for `claude -p` — see DESIGN.md. This is why a
    #: trivial task can cost more to delegate than to skip.
    dispatch_overhead_tokens: int = 0
    #: Adapter-specific, operator-supplied flags. Currently used by Claude
    #: Code for settings such as ``--effort medium``.
    cli_args: tuple[str, ...] = ()
    #: HTTP endpoint and the *name* of an environment variable containing its
    #: credential. Raw credentials are deliberately not part of the schema.
    base_url: str | None = None
    api_key_env: str | None = None

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

    def to_toml(self) -> str:
        """Render a normalized, secret-free config for a console child run."""
        lines = [
            f"concurrency = {self.concurrency}",
            f"catalog_ttl_s = {self.catalog_ttl_s!r}",
            f"reserve_fraction = {self.reserve_fraction!r}",
        ]
        for key, value in (
            ("catalog_url", self.catalog_url),
            ("catalog_cache_path", str(self.catalog_cache_path) if self.catalog_cache_path else None),
            ("window_tokens_limit", self.window_tokens_limit),
            ("metered_budget_usd", self.metered_budget_usd),
        ):
            if value is not None:
                lines.append(f"{key} = {_toml_scalar(value)}")

        for backend in self.backends.values():
            lines.extend([
                "",
                "[[backends]]",
                f"name = {_toml_scalar(backend.name)}",
                f"adapter = {_toml_scalar(backend.adapter.value)}",
                f"billing = {_toml_scalar(backend.billing.value)}",
                f"dispatch_overhead_tokens = {backend.dispatch_overhead_tokens}",
            ])
            if backend.base_url is not None:
                lines.append(f"base_url = {_toml_scalar(backend.base_url)}")
            if backend.api_key_env is not None:
                lines.append(f"api_key_env = {_toml_scalar(backend.api_key_env)}")
            if backend.cli_args:
                lines.append(f"cli_args = {_toml_strings(backend.cli_args)}")
            models = []
            for model in backend.models:
                fields = [f"id = {_toml_scalar(model.id)}"]
                if model.context is not None:
                    fields.append(f"context = {model.context}")
                if model.price_per_mtok is not None:
                    fields.append(f"price_per_mtok = {model.price_per_mtok!r}")
                models.append("{ " + ", ".join(fields) + " }")
            lines.append("models = [" + ", ".join(models) + "]")

        for tier, policy in self.tiers.items():
            lines.extend([
                "",
                f"[tiers.{tier.value}]",
                f"prefer = {_toml_strings(policy.prefer)}",
                f"min_context = {policy.min_context}",
                f"output_ratio = {policy.output_ratio!r}",
            ])
            if policy.max_price_per_mtok is not None:
                lines.append(f"max_price_per_mtok = {policy.max_price_per_mtok!r}")
            for key, values in (
                ("require_parameters", policy.require_parameters),
                ("allow", policy.allow),
                ("deny", policy.deny),
            ):
                if values:
                    lines.append(f"{key} = {_toml_strings(values)}")
        return "\n".join(lines) + "\n"

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
        if not isinstance(raw, dict):
            raise ConfigError(f"{source}: configuration root must be a table")
        _only_keys(
            raw,
            {
                "backends", "tiers", "concurrency", "catalog_ttl_s", "catalog_url",
                "catalog_cache_path", "reserve_fraction", "window_tokens_limit",
                "metered_budget_usd",
            },
            source,
        )
        backends = _parse_backends(raw.get("backends"), source)
        tiers = _parse_tiers(raw.get("tiers"), backends, source)

        missing = [tier.value for tier in Tier if tier not in tiers]
        if missing:
            # Fail at load, not at dispatch. A tier with no policy is a run that
            # dies partway through with half the plan already paid for.
            raise ConfigError(
                f"{source}: no [tiers.*] policy for: {', '.join(sorted(missing))}"
            )

        concurrency = _opt_int(raw.get("concurrency", 3))
        catalog_ttl_s = _opt_float(raw.get("catalog_ttl_s", 6 * 60 * 60))
        reserve_fraction = _opt_float(raw.get("reserve_fraction", 0.10))
        if concurrency is None or concurrency < 1:
            raise ConfigError(f"{source}: concurrency must be an integer of at least 1")
        if catalog_ttl_s is None or not math.isfinite(catalog_ttl_s) or catalog_ttl_s <= 0:
            raise ConfigError(f"{source}: catalog_ttl_s must be finite and greater than zero")
        if (
            reserve_fraction is None
            or not math.isfinite(reserve_fraction)
            or not 0 <= reserve_fraction < 1
        ):
            raise ConfigError(f"{source}: reserve_fraction must be between 0 (inclusive) and 1")
        window_limit = _opt_int(raw.get("window_tokens_limit"))
        metered_budget = _opt_float(raw.get("metered_budget_usd"))
        if raw.get("window_tokens_limit") is not None and window_limit is None:
            raise ConfigError(f"{source}: window_tokens_limit must be numeric")
        if raw.get("metered_budget_usd") is not None and metered_budget is None:
            raise ConfigError(f"{source}: metered_budget_usd must be numeric")
        if window_limit is not None and window_limit <= 0:
            raise ConfigError(f"{source}: window_tokens_limit must be greater than zero")
        if metered_budget is not None and (
            not math.isfinite(metered_budget) or metered_budget < 0
        ):
            raise ConfigError(f"{source}: metered_budget_usd must be finite and non-negative")

        catalog_url = raw.get("catalog_url")
        if catalog_url is not None and (not isinstance(catalog_url, str) or not catalog_url):
            raise ConfigError(f"{source}: catalog_url must be a non-empty string")
        cache_path = raw.get("catalog_cache_path")
        if cache_path is not None and (not isinstance(cache_path, str) or not cache_path):
            raise ConfigError(f"{source}: catalog_cache_path must be a non-empty string")

        return cls(
            backends=backends,
            tiers=tiers,
            concurrency=concurrency,
            catalog_ttl_s=catalog_ttl_s,
            catalog_url=catalog_url,
            catalog_cache_path=Path(cache_path) if cache_path else None,
            reserve_fraction=reserve_fraction,
            window_tokens_limit=window_limit,
            metered_budget_usd=metered_budget,
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
        _only_keys(
            entry,
            {
                "name", "adapter", "billing", "models",
                "dispatch_overhead_tokens", "cli_args", "base_url", "api_key_env",
            },
            f"{source}: backend",
        )
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

        overhead = _opt_int(entry.get("dispatch_overhead_tokens", 0))
        if overhead is None or overhead < 0:
            raise ConfigError(
                f"{source}: backend {name!r} dispatch overhead must be a non-negative whole number"
            )
        cli_args = _pattern_list(entry.get("cli_args"), f"{source}: backend {name!r}", "cli_args")
        if cli_args and adapter is not Adapter.CLAUDE:
            raise ConfigError(f"{source}: backend {name!r} cli_args are currently supported only for claude")
        base_url = entry.get("base_url")
        api_key_env = entry.get("api_key_env")
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise ConfigError(f"{source}: backend {name!r} base_url must be a non-empty string")
        if isinstance(base_url, str):
            parsed_url = urlsplit(base_url)
            if (
                parsed_url.scheme not in ("http", "https")
                or not parsed_url.netloc
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                raise ConfigError(
                    f"{source}: backend {name!r} base_url must be an HTTP(S) URL "
                    "without embedded credentials"
                )
        if api_key_env is not None and (
            not isinstance(api_key_env, str)
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", api_key_env) is None
        ):
            raise ConfigError(
                f"{source}: backend {name!r} api_key_env must be an environment variable name"
            )
        if adapter in (Adapter.OPENAI, Adapter.ANTHROPIC) and base_url is None:
            raise ConfigError(f"{source}: backend {name!r} requires base_url")
        if adapter in (Adapter.CLAUDE, Adapter.CODEX) and (
            base_url is not None or api_key_env is not None
        ):
            raise ConfigError(
                f"{source}: backend {name!r} cannot set HTTP endpoint fields for {adapter.value}"
            )
        backends[name] = Backend(
            name=name,
            adapter=adapter,
            billing=billing,
            models=_parse_models(entry.get("models"), name, source),
            dispatch_overhead_tokens=overhead,
            cli_args=cli_args,
            base_url=base_url.rstrip("/") if base_url else None,
            api_key_env=api_key_env,
        )
    return backends


def _parse_models(raw: Any, backend: str, source: str) -> tuple[ModelOption, ...]:
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"{source}: backend {backend!r} must name at least one model")
    options: list[ModelOption] = []
    for item in raw:
        if isinstance(item, str) and item:
            model_id = item
            options.append(ModelOption(id=model_id))
        elif isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]:
            _only_keys(item, {"id", "context", "price_per_mtok"}, f"{source}: backend {backend!r} model")
            model_id = item["id"]
            context = _opt_int(item.get("context"))
            price = _opt_float(item.get("price_per_mtok"))
            if item.get("context") is not None and (context is None or context <= 0):
                raise ConfigError(
                    f"{source}: backend {backend!r} model {item['id']!r} context must be "
                    f"a positive finite number"
                )
            if item.get("price_per_mtok") is not None and (
                price is None or not math.isfinite(price) or price < 0
            ):
                raise ConfigError(
                    f"{source}: backend {backend!r} model {item['id']!r} price must be finite and non-negative"
                )
            options.append(
                ModelOption(
                    id=item["id"],
                    context=context,
                    price_per_mtok=price,
                )
            )
        else:
            raise ConfigError(
                f"{source}: backend {backend!r} has a model entry that is neither a "
                f"string nor a table with an id: {item!r}"
            )
        if not model_id.strip() or any(ord(char) < 32 or ord(char) == 127 for char in model_id):
            raise ConfigError(f"{source}: backend {backend!r} model id must be printable and non-empty")
        if any(option.id == model_id for option in options[:-1]):
            raise ConfigError(f"{source}: backend {backend!r} names model {model_id!r} more than once")
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
        _only_keys(
            entry,
            {
                "prefer", "min_context", "max_price_per_mtok", "require_parameters",
                "allow", "deny", "output_ratio",
            },
            f"{source}: [tiers.{key}]",
        )

        prefer = _pattern_list(entry.get("prefer"), f"{source}: [tiers.{key}]", "prefer")
        unknown = [name for name in prefer if name not in backends]
        if unknown:
            raise ConfigError(
                f"{source}: [tiers.{key}] prefers unknown backend(s) {unknown}; "
                f"known backends are {sorted(backends)}"
            )
        if not prefer:
            raise ConfigError(f"{source}: [tiers.{key}] must name at least one backend")

        min_context = _opt_int(entry.get("min_context", 0))
        if min_context is None:
            raise ConfigError(
                f"{source}: [tiers.{key}] min_context must be a whole number"
            )
        output_ratio = _opt_float(entry.get("output_ratio", 0.25))
        if output_ratio is None:
            raise ConfigError(
                f"{source}: [tiers.{key}] output_ratio must be a finite number"
            )
        max_price = _opt_float(entry.get("max_price_per_mtok"))
        if min_context is None or min_context < 0:
            raise ConfigError(f"{source}: [tiers.{key}] min_context must be a non-negative integer")
        if output_ratio is None or not math.isfinite(output_ratio) or not 0 <= output_ratio <= 1:
            raise ConfigError(f"{source}: [tiers.{key}] output_ratio must be between 0 and 1")
        if entry.get("max_price_per_mtok") is not None and (
            max_price is None or not math.isfinite(max_price) or max_price < 0
        ):
            raise ConfigError(f"{source}: [tiers.{key}] max price must be finite and non-negative")
        tiers[tier] = TierPolicy(
            prefer=prefer,
            min_context=min_context,
            max_price_per_mtok=max_price,
            require_parameters=_pattern_list(
                entry.get("require_parameters"), f"{source}: [tiers.{key}]", "require_parameters"
            ),
            allow=_pattern_list(entry.get("allow"), f"{source}: [tiers.{key}]", "allow"),
            deny=_pattern_list(entry.get("deny"), f"{source}: [tiers.{key}]", "deny"),
            output_ratio=output_ratio,
        )
    return tiers


def _opt_int(value: Any) -> int | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    # TOML 1.0 spells `nan` and `inf`; int() answers those with ValueError and
    # OverflowError, neither of which the callers translate into a ConfigError.
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        return None
    return int(value)


def _opt_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _pattern_list(value: Any, where: str, field: str) -> tuple[str, ...]:
    """Read a list of match patterns, refusing a bare string.

    Router matching is substring-based, so `tuple("gpt-4")` would silently
    become five one-character patterns: as a deny list that rejects every
    model, and as an allow list it accepts nearly every model — which is the
    direction that matters, since the allow list is what holds a tier off the
    models the operator excluded.
    """
    if value is None:
        return ()
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ConfigError(
            f"{where}: {field} must be a list of strings, each non-empty; got {value!r}"
        )
    return tuple(value)


def _only_keys(raw: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ConfigError(f"{where}: unknown configuration key(s): {', '.join(unknown)}")


__all__ = [
    "DEFAULT_CONFIG_NAMES",
    "Backend",
    "ConfigError",
    "ModelOption",
    "SleipnirConfig",
    "TierPolicy",
]
