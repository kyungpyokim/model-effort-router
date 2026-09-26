"""Provider-neutral usage telemetry primitives for the E2E token-savings benchmark.

Consumes validated provider argv, captured provider stdout, stage metadata, exit code and
wall time; produces normalized usage records for the run's usage JSONL sink. Provider
event-shape logic stays inside the provider parser (Codex only in Phase 1); the argv
adapter and the recorder stay provider-neutral behind an explicit provider registry so
Phase 2 can add a Claude parser without touching aggregation.

Environment contract (read by the pipeline hook, never converted into model argv here):
the enable variable is boolean only and the sink path is only an output destination, so
neither value can inject flags — telemetry flags are code constants inserted here.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

INSTRUMENT_USAGE_ENV = "MODEL_EFFORT_ROUTER_INSTRUMENT_USAGE"
USAGE_JSONL_ENV = "MODEL_EFFORT_ROUTER_USAGE_JSONL"
#: Harness-owned run identifiers for the usage recorder (spec 3.6): recorder metadata only,
#: never converted into model argv. Single source shared by both instrumentation seams — it
#: lives here because pipeline.py and classifier.py both import this module cycle-free.
RUN_CONTEXT_ENV = "MODEL_EFFORT_ROUTER_RUN_CONTEXT"

UsageStatus = Literal["complete", "partial", "missing"]

#: Codex's structured JSONL event-output flag, inserted only at the ``codex exec`` position.
CODEX_JSON_FLAG = "--json"

_SUPPORTED_PROVIDERS = ("codex",)

_USAGE_TOKEN_KEYS = (
    "input_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "output_tokens",
    "reasoning_tokens",
)


@dataclass(frozen=True)
class UsageContext:
    run_id: str
    case_id: str
    mode: str
    stage: str
    attempt: int
    provider: str
    model: str
    effort: str | None


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    usage_status: UsageStatus


@dataclass(frozen=True)
class ParsedProviderOutput:
    logical_output: str
    usage: NormalizedUsage
    raw_events: tuple[dict, ...]
    exit_code: int
    wall_time_ms: int


def instrument_execution_argv(provider: str, validated_argv: Sequence[str]) -> list[str]:
    """Return the execution argv: validated argv plus provider-owned telemetry flags.

    Call only after ``validate_argv()`` succeeded. Flags are trusted constants defined
    here, never derived from env values or route contents; every provider/argv shape
    whose exact flag position this module does not define is refused rather than
    guessed, so ``strip_instrumentation`` can always restore the validated argv."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"no usage instrumentation adapter for provider {provider!r}")
    argv = list(validated_argv)
    if len(argv) < 3 or argv[0] != "codex" or argv[1] != "exec":
        raise ValueError("codex usage instrumentation requires a non-interactive 'codex exec' argv")
    if argv[2] == CODEX_JSON_FLAG:
        raise ValueError("codex argv is already instrumented")
    # Fail-closed precondition, not a grammar: every router-generated ``codex exec`` argv carries
    # a sandbox mode and a model binding, so refusing their absence keeps this helper from
    # instrumenting something the router would never have validated (for example
    # ``codex exec --help``). The binding is ``-m`` for pipeline stages and ``--model`` for the
    # classifier seam, so both spellings count.
    if "--sandbox" not in argv or not ({"-m", "--model"} & set(argv)):
        raise ValueError("codex argv is missing the sandbox or model option the router always emits")
    return [argv[0], argv[1], CODEX_JSON_FLAG, *argv[2:]]


def strip_instrumentation(provider: str, execution_argv: Sequence[str]) -> list[str]:
    """Remove exactly the flag ``instrument_execution_argv`` inserted; identity otherwise."""
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(f"no usage instrumentation adapter for provider {provider!r}")
    argv = list(execution_argv)
    if len(argv) >= 3 and argv[:3] == ["codex", "exec", CODEX_JSON_FLAG]:
        del argv[2]
    return argv


def _token_value(value: object) -> int | None:
    """Accept a non-negative JSON integer; reject bools, floats and anything else."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def parse_codex_jsonl(
    stdout: str, context: UsageContext, *, exit_code: int, wall_time_ms: int
) -> ParsedProviderOutput:
    """Parse Codex ``exec --json`` JSONL stdout into logical output and normalized usage.

    Provider-specific: understands only Codex event shapes — usage on turn events and the
    final assistant text on ``item.completed`` agent messages. Malformed or unrelated
    lines are skipped, and usage already present in the stream is recovered even when the
    process exits non-zero. ``context`` is accepted for the provider-neutral interface;
    stage metadata is joined by ``append_usage_jsonl``, not by the parser.

    ``total_tokens`` is computed as input + output only: cached input, cache writes and
    reasoning tokens are provider subfields and are never added again. Absence of usage is
    reported as ``missing`` with zeroed fields — never inferred as measured zero.

    Usage belongs to the invocation, not to a single turn: each usage-bearing event is a
    separately billed turn, so the invocation's fields are summed over the turns that reported
    them, and a field is never taken from a turn that did not report it. The invocation counts as
    ``complete`` only when **every** usage-bearing turn carried both input and output, so a
    partial turn can never be promoted to complete by an earlier complete one.
    """
    del context  # stage metadata rides the recorder, not the parsed provider output
    events: list[dict] = []
    logical_output = ""
    turns: list[dict[str, int]] = []

    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        events.append(event)

        if event.get("type") == "item.completed":
            item = event.get("item")
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str):
                    logical_output = text

        usage = event.get("usage")
        if isinstance(usage, dict):
            reported = {key: value for key in _USAGE_TOKEN_KEYS if (value := _token_value(usage.get(key))) is not None}
            # An event that reports no usable token value changes nothing (it is not a measured zero).
            if reported:
                turns.append(reported)

    if turns:
        input_tokens = sum(turn.get("input_tokens", 0) for turn in turns)
        output_tokens = sum(turn.get("output_tokens", 0) for turn in turns)
        usage = NormalizedUsage(
            input_tokens=input_tokens,
            cached_input_tokens=sum(turn.get("cached_input_tokens", 0) for turn in turns),
            cache_write_tokens=sum(turn.get("cache_write_tokens", 0) for turn in turns),
            output_tokens=output_tokens,
            reasoning_tokens=sum(turn.get("reasoning_tokens", 0) for turn in turns),
            total_tokens=input_tokens + output_tokens,
            usage_status="complete" if all({"input_tokens", "output_tokens"} <= set(turn) for turn in turns) else "partial",
        )
    else:
        usage = NormalizedUsage(0, 0, 0, 0, 0, 0, "missing")

    return ParsedProviderOutput(
        logical_output=logical_output,
        usage=usage,
        raw_events=tuple(events),
        exit_code=exit_code,
        wall_time_ms=wall_time_ms,
    )


def append_usage_jsonl(path: Path, context: UsageContext, parsed: ParsedProviderOutput) -> None:
    """Append one normalized invocation record to the usage sink.

    Writes exactly one line per model call, carrying ``usage_status`` verbatim so a
    missing or partial usage is never rewritten as a measured zero."""
    usage = parsed.usage
    record = {
        "run_id": context.run_id,
        "case_id": context.case_id,
        "mode": context.mode,
        "stage": context.stage,
        "attempt": context.attempt,
        "provider": context.provider,
        "model": context.model,
        "effort": context.effort,
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
        "usage_status": usage.usage_status,
        "exit_code": parsed.exit_code,
        "wall_time_ms": parsed.wall_time_ms,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
