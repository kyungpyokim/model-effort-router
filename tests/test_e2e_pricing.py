"""The E2E pricing adapter: versioned snapshot loading and API-equivalent cost.

Two rules these tests exist to protect. First, pricing validity is not usage completeness: a
record can be priced while its usage is still `partial`, and an unpriced model is invalid however
complete its usage is. Second, a record that cannot be priced fails with a typed error — it is
never silently reported as `$0`, which would make an unpriced or unmeasured run look free.
"""
import json
import sys
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import e2e_pricing  # noqa: E402
from e2e_usage import NormalizedUsage  # noqa: E402

SNAPSHOT = ROOT / "tests" / "fixtures" / "e2e_pricing" / "snapshot.json"
PRODUCTION_SNAPSHOT = ROOT / "config" / "model-pricing.json"


def usage(input_tokens=0, cached_input_tokens=0, cache_write_tokens=0, output_tokens=0, reasoning_tokens=0, status="complete"):
    return NormalizedUsage(
        input_tokens=input_tokens, cached_input_tokens=cached_input_tokens,
        cache_write_tokens=cache_write_tokens, output_tokens=output_tokens,
        reasoning_tokens=reasoning_tokens, total_tokens=input_tokens + output_tokens,
        usage_status=status,
    )


class PricingSnapshotTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pricing = e2e_pricing.load_pricing(SNAPSHOT)

    def test_a_snapshot_carries_its_provenance_and_unit(self):
        self.assertEqual(self.pricing.snapshot_date, "2026-09-01")
        self.assertEqual(self.pricing.currency, "USD")
        self.assertIn("openai", self.pricing.sources)
        self.assertTrue(self.pricing.sources["openai"])

    def test_rates_are_exact_decimals_not_floats(self):
        rate = self.pricing.providers["openai"]["fixture-standard"].input_per_million

        self.assertEqual(rate, Decimal("1.25"))
        self.assertIsInstance(rate, Decimal)

    def test_an_unknown_snapshot_shape_is_refused(self):
        for broken in (
            {"currency": "USD", "sources": {}, "providers": {}},                       # no snapshot_date
            {"snapshot_date": "2026-09-01", "sources": {}, "providers": {}},            # no currency
            {"snapshot_date": "2026-09-01", "currency": "USD", "providers": {}},        # no sources
            {"snapshot_date": "2026-09-01", "currency": "USD", "sources": {}, "providers": "openai"},
        ):
            with self.subTest(broken=sorted(broken)):
                with self.assertRaises(e2e_pricing.PricingError):
                    e2e_pricing.load_pricing(self.write_snapshot(broken))

    def test_a_provider_without_a_source_is_refused(self):
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        snapshot["providers"]["other"] = {"fixture-basic": {"input_per_million": 1, "output_per_million": 2}}
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.load_pricing(self.write_snapshot(snapshot))
        self.assertEqual(caught.exception.kind, "schema")

    def test_an_unknown_rate_key_or_billing_rule_is_refused(self):
        for entry in (
            {"input_per_million": 1, "output_per_million": 2, "output_per_token": 3},
            {"input_per_million": 1, "output_per_million": 2, "reasoning_billing": "sometimes"},
        ):
            with self.subTest(entry=sorted(entry)):
                snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
                snapshot["providers"]["openai"]["fixture-standard"] = entry
                with self.assertRaises(e2e_pricing.PricingError):
                    e2e_pricing.load_pricing(self.write_snapshot(snapshot))

    def test_the_production_snapshot_is_populated_and_fully_priced(self):
        pricing = e2e_pricing.load_pricing(PRODUCTION_SNAPSHOT)

        self.assertEqual(pricing.currency, "USD")
        self.assertEqual(pricing.snapshot_date, "2026-09-27")
        self.assertEqual(pricing.conditions, {"service_tier": "standard", "context_band": "short"})
        self.assertEqual(e2e_pricing.unpriced_models(pricing), ())

    def test_the_production_rates_price_the_phase_1_models(self):
        pricing = e2e_pricing.load_pricing(PRODUCTION_SNAPSHOT)

        # gpt-6-luna: ordinary 0.1M*0.1 + cached 0.8M*0.01 + writes 0.1M*0.125 + output 0.2M*0.5
        luna = e2e_pricing.estimate_api_equivalent_cost_usd(
            "openai", "gpt-6-luna",
            usage(input_tokens=1_000_000, cached_input_tokens=800_000, cache_write_tokens=100_000, output_tokens=200_000),
            pricing,
        )
        self.assertEqual(luna, Decimal("0.130500"))
        # gpt-6-sol: 1M input + 1M output
        sol = e2e_pricing.estimate_api_equivalent_cost_usd(
            "openai", "gpt-6-sol", usage(input_tokens=1_000_000, output_tokens=1_000_000), pricing,
        )
        self.assertEqual(sol, Decimal("12.000000"))

    def write_snapshot(self, data):
        path = Path(self._tmp.name) / "snapshot.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path


class CostArithmeticTests(unittest.TestCase):
    def setUp(self):
        self.pricing = e2e_pricing.load_pricing(SNAPSHOT)

    def cost(self, model="fixture-standard", **kwargs):
        return e2e_pricing.estimate_api_equivalent_cost_usd("openai", model, usage(**kwargs), self.pricing)

    def test_uncached_input_is_billed_at_the_input_rate(self):
        # fixture-standard: input 1.25/M, cached 0.25/M, output 5/M
        self.assertEqual(self.cost(input_tokens=1_000_000), Decimal("1.250000"))

    def test_cached_input_is_discounted_and_not_billed_twice(self):
        # 1M input of which 0.8M cached: 0.2M * 1.25 + 0.8M * 0.25
        self.assertEqual(self.cost(input_tokens=1_000_000, cached_input_tokens=800_000), Decimal("0.450000"))

    def test_cache_writes_are_billed_at_their_own_rate(self):
        # fixture-cache-write: input 1/M, cached 0.5/M, write 2/M, output 4/M
        # ordinary 0.6M*1 + cached 0.2M*0.5 + writes 0.2M*2 = 1.1
        cost = e2e_pricing.estimate_api_equivalent_cost_usd(
            "openai", "fixture-cache-write",
            usage(input_tokens=1_000_000, cached_input_tokens=200_000, cache_write_tokens=200_000), self.pricing,
        )
        self.assertEqual(cost, Decimal("1.100000"))

    def test_cached_plus_cache_write_exceeding_input_is_invalid_usage(self):
        # The buckets partition the input, so this record is a measurement fault. It must fail
        # closed rather than be clamped into a cheaper, believable-looking number.
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd(
                "openai", "fixture-cache-write",
                usage(input_tokens=1_000_000, cached_input_tokens=900_000, cache_write_tokens=500_000), self.pricing,
            )
        self.assertEqual(caught.exception.kind, "invalid_usage")

    def test_cache_writes_without_a_write_rate_are_missing_rate(self):
        # A null write rate is only allowed while the record reports no cache writes; the adapter
        # never reinterprets those tokens as ordinary input.
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd(
                "openai", "fixture-standard",
                usage(input_tokens=1000, cache_write_tokens=100), self.pricing,
            )
        self.assertEqual(caught.exception.kind, "missing_rate")

    def test_reasoning_included_in_output_is_not_charged_twice(self):
        with_reasoning = self.cost(output_tokens=1_000_000, reasoning_tokens=600_000)

        self.assertEqual(with_reasoning, Decimal("5.000000"))
        self.assertEqual(with_reasoning, self.cost(output_tokens=1_000_000))

    def test_reasoning_not_billed_is_excluded_from_billable_output(self):
        # fixture-no-reasoning-billing: output 10/M, reasoning excluded
        cost = e2e_pricing.estimate_api_equivalent_cost_usd(
            "openai", "fixture-no-reasoning-billing",
            usage(output_tokens=1_000_000, reasoning_tokens=600_000), self.pricing,
        )
        self.assertEqual(cost, Decimal("4.000000"))

    def test_separately_billed_reasoning_uses_its_own_rate_never_the_output_rate_twice(self):
        # canonical: reasoning is a subset of output. fixture-separate-reasoning: output 2/M,
        # reasoning 3/M, so (1M - 0.2M)*2 + 0.2M*3 = 2.2, not (1M + 0.2M)*2.
        cost = e2e_pricing.estimate_api_equivalent_cost_usd(
            "openai", "fixture-separate-reasoning",
            usage(output_tokens=1_000_000, reasoning_tokens=200_000), self.pricing,
        )
        self.assertEqual(cost, Decimal("2.200000"))

    def test_separately_billed_reasoning_without_its_rate_is_missing_rate(self):
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd(
                "openai", "fixture-separate-reasoning-without-a-rate",
                usage(output_tokens=1_000_000, reasoning_tokens=200_000), self.pricing,
            )
        self.assertEqual(caught.exception.kind, "missing_rate")

    def test_zero_measured_tokens_are_a_real_zero(self):
        self.assertEqual(self.cost(), Decimal("0.000000"))

    def test_a_negative_derived_uncached_input_is_invalid_usage(self):
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            self.cost(input_tokens=100, cached_input_tokens=150)
        self.assertEqual(caught.exception.kind, "invalid_usage")

    def test_reasoning_exceeding_output_is_invalid_for_every_rule(self):
        # Canonical invariant: reasoning_tokens is a subset of output_tokens, whatever the billing
        # rule, so a record that breaks it is a measurement fault.
        for model in ("fixture-standard", "fixture-no-reasoning-billing", "fixture-separate-reasoning"):
            with self.subTest(model=model):
                with self.assertRaises(e2e_pricing.PricingError) as caught:
                    e2e_pricing.estimate_api_equivalent_cost_usd(
                        "openai", model, usage(output_tokens=100, reasoning_tokens=150), self.pricing,
                    )
                self.assertEqual(caught.exception.kind, "invalid_usage")


class PricingValidityTests(unittest.TestCase):
    """Pricing validity is decided by the pricing side, never by usage completeness."""

    def setUp(self):
        self.pricing = e2e_pricing.load_pricing(SNAPSHOT)

    def test_partial_usage_with_the_needed_buckets_is_priced(self):
        # `partial` stays a usage-completeness fact; the adapter prices what was measured and the
        # harness decides the run's validity separately.
        cost = e2e_pricing.estimate_api_equivalent_cost_usd(
            "openai", "fixture-standard",
            usage(input_tokens=1_000_000, status="partial"), self.pricing,
        )
        self.assertEqual(cost, Decimal("1.250000"))

    def test_complete_usage_with_an_unpriced_model_is_invalid(self):
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd("openai", "not-in-table", usage(10, output_tokens=1), self.pricing)
        self.assertEqual(caught.exception.kind, "unknown_model")

    def test_an_unknown_provider_is_invalid(self):
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd("anthropic", "claude", usage(10, output_tokens=1), self.pricing)
        self.assertEqual(caught.exception.kind, "unknown_provider")

    def test_a_missing_rate_is_invalid_rather_than_free(self):
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd(
                "openai", "fixture-partial-rate", usage(input_tokens=1000, output_tokens=10), self.pricing,
            )
        self.assertEqual(caught.exception.kind, "missing_rate")

    def test_unmeasured_usage_is_never_priced_as_zero(self):
        with self.assertRaises(e2e_pricing.PricingError) as caught:
            e2e_pricing.estimate_api_equivalent_cost_usd(
                "openai", "fixture-standard", usage(status="missing"), self.pricing,
            )
        self.assertEqual(caught.exception.kind, "missing_usage")

    def test_no_failure_is_reported_as_a_zero_cost(self):
        for provider, model, record in (
            ("anthropic", "claude", usage(10, output_tokens=1)),
            ("openai", "not-in-table", usage(10, output_tokens=1)),
            ("openai", "fixture-partial-rate", usage(10, output_tokens=1)),
            ("openai", "fixture-standard", usage(status="missing")),
        ):
            with self.subTest(provider=provider, model=model):
                with self.assertRaises(e2e_pricing.PricingError):
                    e2e_pricing.estimate_api_equivalent_cost_usd(provider, model, record, self.pricing)


class PricingBundleTests(unittest.TestCase):
    def test_the_pricing_module_is_not_bundle_shared(self):
        # Nothing in a bundled plugin imports it, so it must stay out of sync_bundle.SHARED
        # (the bundle parity test derives its list from there).
        sys.path.insert(0, str(ROOT / "scripts"))
        import sync_bundle

        self.assertNotIn("scripts/e2e_pricing.py", sync_bundle.SHARED)
        self.assertIn("scripts/e2e_usage.py", sync_bundle.SHARED)


if __name__ == "__main__":
    unittest.main()
