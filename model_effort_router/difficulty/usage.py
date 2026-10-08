"""Token-usage summing shared by the Router (route events) and evaluation tooling."""

USAGE_KEYS = ("input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")


def sum_usage(usages):
    """Sum codex-style usage dicts over USAGE_KEYS (ignores unknown keys and non-int values)."""
    return {
        k: sum(u[k] for u in usages if isinstance(u.get(k), int) and not isinstance(u.get(k), bool)) for k in USAGE_KEYS
    }
