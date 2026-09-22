"""Golden benchmark corpus definitions for Model Effort Router."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts dir is in sys.path when imported as a script or module
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from benchmark_cases import BenchmarkCase, GOLDEN_BENCHMARK_CASES

__all__ = ["BenchmarkCase", "GOLDEN_BENCHMARK_CASES"]
