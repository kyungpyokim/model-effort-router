"""Versioned API-equivalent pricing for the E2E benchmark (spec sections 5.1-5.3).

The adapter turns a normalized usage record into an API-equivalent cost from a committed,
version-controlled pricing snapshot; there is no live price lookup, and no rate is hardcoded here.

Two rules this module exists to keep apart.

* **Pricing validity is not usage completeness.** A record whose usage is still ``partial`` can be
  priced when the rates and buckets it needs are present, and a ``complete`` record whose model is
  not in the snapshot cannot. The adapter therefore decides only from the snapshot and the
  arithmetic; ``usage_status`` is a fact about measurement, and the harness (Task 8/9) decides a
  run's validity from it separately.
* **A record that cannot be priced fails, it is never reported as free.** Every failure raises
  ``PricingError`` with a stable ``kind`` (``schema``, ``unknown_provider``, ``unknown_model``,
  ``missing_rate``, ``invalid_usage``, ``missing_usage``) so the harness can mark the run
  ``pricing_invalid`` instead of silently adding ``$0`` to a total.

Null rate semantics: ``input_per_million`` and ``output_per_million`` are essential — a model
without them is unpriced however small the record. ``cached_input_per_million`` may be null only if
the record reports no cached input. ``cache_write_per_million`` may be null because a provider that
does not bill cache writes separately keeps those tokens inside uncached input (no separate charge),
which is how the Codex records are shaped. ``reasoning_billing`` states the provider's rule:
``included_in_output`` (already inside ``output_tokens``), ``not_billed`` (excluded from billable
output), or ``separate`` (billed at the output rate on top of ``output_tokens``).

Not bundle-shared on purpose: nothing a plugin ships imports it, so it stays out of
``sync_bundle.SHARED`` while ``e2e_usage`` (imported by the pipeline and classifier) is in it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Mapping

from e2e_usage import NormalizedUsage

RATE_KEYS = ("input_per_million", "cached_input_per_million", "cache_write_per_million", "output_per_million")
ENTRY_KEYS = (*RATE_KEYS, "reasoning_billing")
ESSENTIAL_RATE_KEYS = ("input_per_million", "output_per_million")
REASONING_BILLING = ("included_in_output", "not_billed", "separate")
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MILLION = Decimal(1_000_000)
_MICRO_USD = Decimal("0.000001")


class PricingError(Exception):
    """A record that cannot be priced, with a stable ``kind`` for the caller's run validity."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class ModelPricing:
    input_per_million: Decimal | None
    cached_input_per_million: Decimal | None
    cache_write_per_million: Decimal | None
    output_per_million: Decimal | None
    reasoning_billing: str


@dataclass(frozen=True)
class PricingSnapshot:
    #: ISO date the rates were taken from the provider, or None while the snapshot is unpopulated.
    snapshot_date: str | None
    currency: str
    sources: Mapping[str, str]
    providers: Mapping[str, Mapping[str, ModelPricing]]


def _rate(value: object, where: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PricingError("schema", f"{where} must be a JSON number or null")
    try:
        rate = Decimal(str(value))
    except InvalidOperation as exc:
        raise PricingError("schema", f"{where} is not a usable number") from exc
    if not rate.is_finite() or rate < 0:
        raise PricingError("schema", f"{where} must be finite and non-negative")
    return rate


def load_pricing(path: Path) -> PricingSnapshot:
    """Read and validate a pricing snapshot, refusing anything the adapter cannot trust.

    ``snapshot_date`` must be present and either an ISO date or null: an unpopulated snapshot says
    so explicitly, while a document that forgot its provenance is refused. Every provider in
    ``providers`` needs a source, and every model entry is checked against the schema, so a typo
    cannot quietly become "this rate is missing"."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PricingError("schema", f"pricing snapshot is unreadable ({exc})") from exc
    if not isinstance(raw, dict):
        raise PricingError("schema", "pricing snapshot must be a JSON object")
    if "snapshot_date" not in raw:
        raise PricingError("schema", "pricing snapshot must declare snapshot_date (or null)")
    date = raw["snapshot_date"]
    if date is not None and (not isinstance(date, str) or not _ISO_DATE.match(date)):
        raise PricingError("schema", "snapshot_date must be an ISO date or null")
    currency = raw.get("currency")
    if not isinstance(currency, str) or not currency.strip():
        raise PricingError("schema", "pricing snapshot must declare its currency")
    sources = raw.get("sources")
    if not isinstance(sources, dict) or not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in sources.items()):
        raise PricingError("schema", "pricing snapshot must map each provider to a source")
    providers = raw.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise PricingError("schema", "pricing snapshot must define providers")

    loaded: dict[str, dict[str, ModelPricing]] = {}
    for provider, models in providers.items():
        if provider not in sources:
            raise PricingError("schema", f"provider {provider!r} has no source")
        if not isinstance(models, dict) or not models:
            raise PricingError("schema", f"provider {provider!r} must define models")
        loaded[provider] = {}
        for model, entry in models.items():
            where = f"{provider}/{model}"
            if not isinstance(entry, dict) or not set(entry) <= set(ENTRY_KEYS):
                raise PricingError("schema", f"{where} has an unknown field")
            billing = entry.get("reasoning_billing", "included_in_output")
            if billing not in REASONING_BILLING:
                raise PricingError("schema", f"{where} has an unknown reasoning_billing rule")
            loaded[provider][model] = ModelPricing(
                input_per_million=_rate(entry.get("input_per_million"), f"{where}.input_per_million"),
                cached_input_per_million=_rate(entry.get("cached_input_per_million"), f"{where}.cached_input_per_million"),
                cache_write_per_million=_rate(entry.get("cache_write_per_million"), f"{where}.cache_write_per_million"),
                output_per_million=_rate(entry.get("output_per_million"), f"{where}.output_per_million"),
                reasoning_billing=billing,
            )
    return PricingSnapshot(snapshot_date=date, currency=currency, sources=dict(sources), providers=loaded)


def unpriced_models(pricing: PricingSnapshot) -> tuple[str, ...]:
    """``<provider>/<model>`` entries missing an essential rate, sorted.

    The Task 10 readiness gate requires this to be empty for the Phase 1 models before the
    benchmark is gated; it is also how a partially populated snapshot reports itself."""
    return tuple(sorted(
        f"{provider}/{model}"
        for provider, models in pricing.providers.items()
        for model, entry in models.items()
        if any(getattr(entry, key) is None for key in ESSENTIAL_RATE_KEYS)
    ))


def _component(tokens: int, rate: Decimal) -> Decimal:
    return (Decimal(tokens) / _MILLION) * rate


def estimate_api_equivalent_cost_usd(provider: str, model: str, usage: NormalizedUsage, pricing: PricingSnapshot) -> Decimal:
    """The API-equivalent cost of one measured invocation, or ``PricingError``.

    Billing quantities are computed here rather than taken from the usage record: cached input is
    subtracted from total input before the input rate applies, cache writes are moved to their own
    rate only when the snapshot defines one and never beyond the uncached input, and reasoning
    tokens follow the provider's ``reasoning_billing`` rule instead of being added to output cost
    twice."""
    if usage.usage_status == "missing":
        # Nothing was measured, so there is no free invocation to report: a zero here would make an
        # unmeasured run look like a measured $0 one.
        raise PricingError("missing_usage", "usage was not measured, so it cannot be priced")
    models = pricing.providers.get(provider)
    if models is None:
        raise PricingError("unknown_provider", f"pricing snapshot has no provider {provider!r}")
    entry = models.get(model)
    if entry is None:
        raise PricingError("unknown_model", f"pricing snapshot has no model {model!r} under {provider!r}")

    essential = {key: getattr(entry, key) for key in ESSENTIAL_RATE_KEYS}
    absent = [key for key, rate in essential.items() if rate is None]
    if absent:
        raise PricingError("missing_rate", f"{provider}/{model} has no {' or '.join(sorted(absent))}")

    uncached_input = usage.input_tokens - usage.cached_input_tokens
    if uncached_input < 0:
        raise PricingError("invalid_usage", "cached input exceeds total input")

    cached_cost = Decimal(0)
    if usage.cached_input_tokens:
        if entry.cached_input_per_million is None:
            raise PricingError("missing_rate", f"{provider}/{model} bills cached input but has no cached rate")
        cached_cost = _component(usage.cached_input_tokens, entry.cached_input_per_million)

    write_cost = Decimal(0)
    if usage.cache_write_tokens and entry.cache_write_per_million is not None:
        # A null write rate means the provider keeps cache writes inside uncached input, so only a
        # snapshot that defines one moves tokens out of it — and never more than it holds.
        billed_writes = min(usage.cache_write_tokens, uncached_input)
        uncached_input -= billed_writes
        write_cost = _component(billed_writes, entry.cache_write_per_million)

    billable_output = usage.output_tokens
    if entry.reasoning_billing == "not_billed":
        billable_output -= usage.reasoning_tokens
        if billable_output < 0:
            raise PricingError("invalid_usage", "reasoning tokens exceed output tokens")
    elif entry.reasoning_billing == "separate":
        # Reported separately and billed on top of output_tokens at the output rate.
        billable_output += usage.reasoning_tokens

    total = (
        _component(uncached_input, essential["input_per_million"])
        + cached_cost
        + write_cost
        + _component(billable_output, essential["output_per_million"])
    )
    return total.quantize(_MICRO_USD, rounding=ROUND_HALF_UP)
