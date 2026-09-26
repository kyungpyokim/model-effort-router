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
without them is unpriced however small the record. ``cached_input_per_million``,
``cache_write_per_million`` and ``reasoning_per_million`` may be null only while the buckets they
price hold no tokens; the moment a record reports cached input, cache writes, or separately billed
reasoning, the missing rate is a ``missing_rate`` failure rather than a silent reinterpretation.
``reasoning_billing`` states the provider's rule: ``included_in_output`` (already inside
``output_tokens``), ``not_billed`` (excluded from billable output), or ``separate`` (billed at
``reasoning_per_million`` on top of the non-reasoning output).

Canonical bucket relation, enforced instead of repaired: ``cached_input_tokens +
cache_write_tokens <= input_tokens`` and ``reasoning_tokens <= output_tokens``. Every token falls in
exactly one bucket — ordinary, cached, or cache-write — so the adapter subtracts both cached and
cache-write tokens from total input, and a record that violates the relation is a measurement fault
that fails closed rather than an input to clamp into a cheaper number.

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

RATE_KEYS = ("input_per_million", "cached_input_per_million", "cache_write_per_million", "output_per_million", "reasoning_per_million")
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
    reasoning_per_million: Decimal | None
    reasoning_billing: str


@dataclass(frozen=True)
class PricingSnapshot:
    #: ISO date the rates were taken from the provider, or None while the snapshot is unpopulated.
    snapshot_date: str | None
    currency: str
    sources: Mapping[str, str]
    #: The conditions the rates apply to (for example ``service_tier`` and ``context_band``), so a
    #: run can be re-priced against the band it actually used.
    conditions: Mapping[str, str]
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
    conditions = raw.get("conditions", {})
    if not isinstance(conditions, dict) or not all(isinstance(key, str) and isinstance(value, str) and value.strip() for key, value in conditions.items()):
        raise PricingError("schema", "pricing snapshot conditions must map names to values")

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
                reasoning_per_million=_rate(entry.get("reasoning_per_million"), f"{where}.reasoning_per_million"),
                reasoning_billing=billing,
            )
    return PricingSnapshot(snapshot_date=date, currency=currency, sources=dict(sources), conditions=dict(conditions), providers=loaded)


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

    # Canonical bucket relation: the record's input splits into ordinary, cached, and cache-write
    # tokens, each billed at its own rate. A record that breaks the relation is a measurement fault,
    # so it fails closed instead of being clamped into a cheaper, believable-looking number.
    if usage.cached_input_tokens + usage.cache_write_tokens > usage.input_tokens:
        raise PricingError("invalid_usage", "cached plus cache-write input exceeds total input")
    if usage.reasoning_tokens > usage.output_tokens:
        raise PricingError("invalid_usage", "reasoning tokens exceed output tokens")
    if usage.cached_input_tokens and entry.cached_input_per_million is None:
        raise PricingError("missing_rate", f"{provider}/{model} bills cached input but has no cached rate")
    if usage.cache_write_tokens and entry.cache_write_per_million is None:
        raise PricingError("missing_rate", f"{provider}/{model} bills cache writes but has no cache-write rate")

    ordinary_input = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_tokens
    cached_cost = _component(usage.cached_input_tokens, entry.cached_input_per_million) if usage.cached_input_tokens else Decimal(0)
    write_cost = _component(usage.cache_write_tokens, entry.cache_write_per_million) if usage.cache_write_tokens else Decimal(0)

    # canonical: output_tokens is the whole output and reasoning_tokens is a subset of it, so only a
    # rule that bills reasoning at its own rate may charge for it beyond the output rate.
    billable_output = usage.output_tokens
    reasoning_cost = Decimal(0)
    if entry.reasoning_billing == "not_billed":
        billable_output -= usage.reasoning_tokens
    elif entry.reasoning_billing == "separate":
        if usage.reasoning_tokens and entry.reasoning_per_million is None:
            raise PricingError("missing_rate", f"{provider}/{model} bills reasoning separately but has no reasoning rate")
        billable_output -= usage.reasoning_tokens
        reasoning_cost = _component(usage.reasoning_tokens, entry.reasoning_per_million) if usage.reasoning_tokens else Decimal(0)

    total = (
        _component(ordinary_input, essential["input_per_million"])
        + cached_cost
        + write_cost
        + _component(billable_output, essential["output_per_million"])
        + reasoning_cost
    )
    return total.quantize(_MICRO_USD, rounding=ROUND_HALF_UP)
