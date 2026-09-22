"""Benchmark cases package re-exporting all golden test cases."""

from __future__ import annotations

from benchmark_cases.cases_l1_l2 import CASES_L1_L2
from benchmark_cases.cases_l3 import CASES_L3
from benchmark_cases.cases_l4_l5 import CASES_L4_L5
from benchmark_cases.models import BenchmarkCase

GOLDEN_BENCHMARK_CASES: list[BenchmarkCase] = CASES_L1_L2 + CASES_L3 + CASES_L4_L5

__all__ = ["BenchmarkCase", "GOLDEN_BENCHMARK_CASES"]
