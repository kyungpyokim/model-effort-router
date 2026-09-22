#!/usr/bin/env python3
"""Jev classifier provider: an optional primary preflight classifier.

Implements the contract specified in docs/2026-09-21-jev-classifier-provider-plan.md:
- Reuses the existing 17-fact classifier schema and validation.
- Short timeout (10s default), no retries.
- Unknown facts are preserved as unresolved without lookup (prompting the user).
- Deterministic fallback on timeout, process/network errors, or schema validation failure.
- Kill switch immediately disables Jev and blocks Jev-originated session records.
- Shadow mode runs non-blocking comparisons without logging task text.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import random
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from classifier import Classification

from route_reuse import is_jev_kill_switch_active, state_dir
from rules import (
    BLAST_RADIUS_CRITERIA, FACTS, FACT_QUESTIONS, FILES_TOUCHED_CRITERIA, FILES_TOUCHED_INSTRUCTIONS, NOUL_CRITERIA,
    READ_ONLY_TASK_TYPES, SECURITY_DOMAIN_CRITERIA, TASK_TYPE_CRITERIA, evaluate_rules,
    extract_json_payload, fact_decision_point, resolve_uncertain_fact, unknown_facts
)

_default_validator: Callable[..., object] | None = None


def set_default_validator(fn: Callable[..., object]) -> None:
    """Register the classifier schema validator without a circular runtime import."""
    global _default_validator
    _default_validator = fn

JEV_STAGE_ENV = "MODEL_EFFORT_ROUTER_JEV_STAGE"
JEV_API_KEY_ENV = "MODEL_EFFORT_ROUTER_JEV_API_KEY"
JEV_KILL_SWITCH_ENV = "MODEL_EFFORT_ROUTER_JEV_KILL_SWITCH"
JEV_ENDPOINT_ENV = "MODEL_EFFORT_ROUTER_JEV_ENDPOINT"
JEV_TIMEOUT_ENV = "MODEL_EFFORT_ROUTER_JEV_TIMEOUT"
JEV_SHADOW_LOG_ENV = "MODEL_EFFORT_ROUTER_JEV_SHADOW_LOG"
JEV_SAMPLE_RATE_ENV = "MODEL_EFFORT_ROUTER_JEV_SAMPLE_RATE"
JEV_MODEL_ENV = "MODEL_EFFORT_ROUTER_JEV_MODEL"

DEFAULT_JEV_MODEL = "jev-latest"
DEFAULT_JEV_TIMEOUT = 10.0
DEFAULT_SHADOW_SAMPLE_RATE = 0.1
MAX_RESPONSE_BYTES = 65536


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Never follow HTTP redirects; prevent leaking Authorization credentials."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"Redirect to {newurl} disallowed", headers, fp)


_NO_REDIRECT_OPENER = urllib.request.build_opener(NoRedirectHandler)


def jev_stage() -> str:
    """Return the configured rollout stage ('off', 'shadow', 'primary').

    If the kill switch is active, immediately returns 'off'.
    """
    if is_jev_kill_switch_active():
        return "off"
    stage = os.environ.get(JEV_STAGE_ENV, "off").strip().lower()
    return stage if stage in ("shadow", "primary") else "off"


def jev_api_key() -> str | None:
    """Read API key from environment only."""
    key = os.environ.get(JEV_API_KEY_ENV) or os.environ.get("JEV_API_KEY")
    return key.strip() if key and key.strip() else None


def jev_timeout() -> float:
    """Return the timeout in seconds for Jev preflight calls."""
    raw = os.environ.get(JEV_TIMEOUT_ENV)
    if raw:
        try:
            val = float(raw)
            if val > 0:
                return val
        except ValueError:
            pass
    return DEFAULT_JEV_TIMEOUT


def _fetch_jev_http(req: urllib.request.Request, timeout: float) -> object:
    with _NO_REDIRECT_OPENER.open(req, timeout=timeout) as resp:
        raw_bytes = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError(f"response exceeded maximum size ({MAX_RESPONSE_BYTES} bytes)")
        return json.loads(raw_bytes.decode("utf-8"))


def _run_with_daemon_thread_deadline(fn: Callable[..., object], timeout: float, *args, **kwargs) -> object:
    """Run fn in a daemon thread and enforce wall-clock deadline without blocking in join/shutdown."""
    q: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def worker():
        try:
            res = fn(*args, **kwargs)
            q.put((True, res))
        except BaseException as exc:
            q.put((False, exc))

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    try:
        success, val = q.get(timeout=timeout)
    except queue.Empty:
        raise TimeoutError(f"Jev request deadline exceeded ({timeout:g}s)") from None

    if success:
        return val
    raise val


def build_systemone_request(task: str, model: str | None = None) -> dict[str, object]:
    """Build the SystemOne POST /v1/systemone request body with 17 fact questions."""
    chosen_model = model or os.environ.get(JEV_MODEL_ENV, DEFAULT_JEV_MODEL)
    questions: dict[str, dict[str, object]] = {}
    for fact in FACTS:
        if fact == "files_touched":
            questions[fact] = {
                "type": "choice",
                "instructions": FILES_TOUCHED_INSTRUCTIONS,
                "criteria": FILES_TOUCHED_CRITERIA,
            }
        elif fact == "security_domain":
            questions[fact] = {
                "type": "choice",
                "instructions": FACT_QUESTIONS.get(fact, "Which security-sensitive area does the work touch?"),
                "criteria": SECURITY_DOMAIN_CRITERIA,
            }
        elif fact == "blast_radius":
            questions[fact] = {
                "type": "choice",
                "instructions": FACT_QUESTIONS.get(fact, "What is the blast radius?"),
                "criteria": BLAST_RADIUS_CRITERIA,
            }
        else:
            questions[fact] = {
                "type": "noul",
                "instructions": FACT_QUESTIONS.get(fact, f"Is {fact} true?"),
            }
            if fact in NOUL_CRITERIA:
                questions[fact]["criteria"] = NOUL_CRITERIA[fact]
    questions["task_type"] = {
        "type": "choice",
        "instructions": "Which single kind of work does this task ask for? Classify only what is asked: "
                        "a request to look at, check or explain something is never widened into a fix.",
        "criteria": TASK_TYPE_CRITERIA,
    }
    return {
        "model": chosen_model,
        "state": task,
        "questions": questions,
    }


def read_task_type(answers: dict, facts: dict[str, str]) -> str:
    """Take task_type from Jev's own choice answer, reconciled with files_touched.

    An unreadable answer falls back to implementation: guessing a read-only type for work that
    may change files would route an editing task to a read-only worker."""
    answer = answers.get("task_type")
    choice = answer.get("choice") if isinstance(answer, dict) else None
    task_type = choice if isinstance(choice, str) and choice in TASK_TYPE_CRITERIA else "implementation"
    if task_type in READ_ONLY_TASK_TYPES:
        # Read-only work changes no file by definition, whatever scope the model read into the
        # implementation the task would eventually need. The validator enforces the same pairing.
        facts["files_touched"] = "0"
    elif facts["files_touched"] == "0":
        # The two answers disagree about whether anything is edited; keep the code-change type
        # and drop the scope claim, since "0" files is only valid for read-only work.
        facts["files_touched"] = "unknown"
    return task_type


def infer_delegability(facts: dict[str, str]) -> int:
    """Deterministically derive delegability (0, 1, or 2) from evaluated facts."""
    if (
        facts.get("changes_security_or_payment_logic") == "yes"
        or facts.get("reviews_security_sensitive_code") == "yes"
        or facts.get("irreversible_or_ledger_or_crypto") == "yes"
        or facts.get("changes_persisted_data") == "yes"
        or facts.get("intermittent_or_concurrency") == "yes"
    ):
        return 0
    if facts.get("mechanical_only") == "yes" and facts.get("files_touched") in ("0", "1"):
        return 2
    return 1


def parse_systemone_response(response: dict[str, object], task: str) -> dict[str, object]:
    """Parse a SystemOne response, apply thresholds, and build a 5-field Classification payload."""
    if not isinstance(response, dict):
        raise ValueError("response must be a dictionary")
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("response missing answers dictionary")

    facts: dict[str, str] = {}
    for fact in FACTS:
        if fact not in answers:
            raise ValueError(f"missing answer for fact: {fact}")
        ans = answers[fact]
        if not isinstance(ans, dict) or "type" not in ans:
            raise ValueError(f"invalid answer format for fact: {fact}")

        ans_type = ans["type"]
        allowed = FACTS[fact]
        if ans_type == "choice":
            choice_val = ans.get("choice")
            if isinstance(choice_val, str) and choice_val in allowed:
                facts[fact] = choice_val
            else:
                facts[fact] = resolve_uncertain_fact(fact)
        elif ans_type == "noul":
            noul_val = ans.get("noul")
            if not isinstance(noul_val, (int, float)):
                raise ValueError(f"invalid noul value for fact: {fact}")
            facts[fact] = "yes" if float(noul_val) >= fact_decision_point(fact) else "no"
        else:
            raise ValueError(f"unexpected answer type {ans_type} for fact {fact}")

    task_type = read_task_type(answers, facts)
    delegability = infer_delegability(facts)
    level, risk_tier, matched, _ = evaluate_rules(facts)
    if matched:
        reason = f"Jev SystemOne facts evaluated: {', '.join(matched)}"
    else:
        reason = f"Jev SystemOne classified {task_type} at {level} ({risk_tier})"

    evidence = [f"{k}={v}" for k, v in facts.items() if v in ("yes", "broad", "6+", "2-5")][:5]
    if not evidence:
        evidence = [f"task: {task[:60].strip()}"]

    return {
        "task_type": task_type,
        "facts": facts,
        "delegability": delegability,
        "reason": reason,
        "evidence": evidence,
    }


def _default_http_client(task: str, timeout: float, api_key: str, endpoint: str) -> object:
    """Call external Jev endpoint via standard HTTP POST with wall-clock deadline."""
    parsed = urllib.parse.urlparse(endpoint)
    is_https = parsed.scheme == "https"
    hostname = (parsed.hostname or "").lower()
    is_local_http = parsed.scheme == "http" and hostname in ("localhost", "127.0.0.1", "::1")
    if not (is_https or is_local_http):
        raise ValueError(f"Jev endpoint must use HTTPS or localhost: {endpoint}")

    req_payload = build_systemone_request(task)
    req_body = json.dumps(req_payload).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=req_body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    return _run_with_daemon_thread_deadline(_fetch_jev_http, timeout, req, timeout)


def classify_task_jev_with_status(
    task: str,
    timeout: float | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    client: Callable[..., object] | None = None,
    validate_fn: Callable[..., object] | None = None,
) -> tuple[Classification | None, str | None]:
    """Invoke Jev to classify a task and return (classification, failure_kind)."""
    if is_jev_kill_switch_active():
        return None, "kill_switch_active"

    key = api_key or jev_api_key()
    if not key:
        return None, "missing_api_key"

    to = timeout if timeout is not None else jev_timeout()
    ep = endpoint or os.environ.get(JEV_ENDPOINT_ENV)

    if client is None:
        if not ep:
            return None, "missing_endpoint"
        client_fn = _default_http_client
    else:
        client_fn = client

    try:
        raw_output = client_fn(task, to, key, ep)
    except (TimeoutError, socket.timeout):
        return None, "timeout"
    except urllib.error.HTTPError as exc:
        return None, f"http_{exc.code}"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)) or "timed out" in str(exc.reason).lower():
            return None, "timeout"
        return None, "network_error"
    except ValueError as exc:
        if "maximum size" in str(exc) or "too large" in str(exc):
            return None, "response_too_large"
        return None, f"error:{type(exc).__name__}"
    except Exception as exc:
        return None, f"error:{type(exc).__name__}"

    try:
        if isinstance(raw_output, str):
            if len(raw_output) > MAX_RESPONSE_BYTES:
                return None, "response_too_large"
            raw_output = extract_json_payload(raw_output)

        if isinstance(raw_output, dict):
            if "answers" in raw_output:
                payload = parse_systemone_response(raw_output, task)
            elif "facts" in raw_output and "task_type" in raw_output:
                payload = raw_output
            else:
                return None, "invalid_json"
        else:
            return None, "invalid_payload_type"
    except Exception:
        return None, "invalid_json"

    validator = validate_fn or _default_validator
    if validator is None:
        return None, "validator_not_configured"
    try:
        result = validator(payload, source="jev")
        return result, None
    except Exception:
        return None, "validation_error"


def classify_task_jev(
    task: str,
    timeout: float | None = None,
    api_key: str | None = None,
    endpoint: str | None = None,
    client: Callable[..., object] | None = None,
    validate_fn: Callable[..., object] | None = None,
) -> Classification | None:
    """Invoke Jev to classify a task.

    Returns Classification with source="jev" on success, or None on failure.
    """
    result, _ = classify_task_jev_with_status(
        task, timeout=timeout, api_key=api_key, endpoint=endpoint, client=client, validate_fn=validate_fn
    )
    return result


def _run_shadow_inline(
    task: str,
    primary_result: Classification,
    client: Callable[..., object] | None = None,
) -> None:
    """Execute the shadow comparison and write to log file."""
    start_time = time.perf_counter()
    jev_result, failure_kind = classify_task_jev_with_status(task, client=client)
    elapsed = round(time.perf_counter() - start_time, 4)

    log_path_str = os.environ.get(JEV_SHADOW_LOG_ENV)
    log_path = Path(log_path_str) if log_path_str else (state_dir() / "jev-shadow.jsonl")

    try:
        if not log_path.parent.exists():
            log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if jev_result is not None:
            fact_diffs = {
                k: {"primary": primary_result.facts.get(k), "jev": jev_result.facts.get(k)}
                for k in set(primary_result.facts) | set(jev_result.facts)
                if primary_result.facts.get(k) != jev_result.facts.get(k)
            }
            entry = {
                "timestamp": time.time(),
                "source": "jev",
                "primary_source": primary_result.source,
                "seconds": elapsed,
                "success": True,
                "failure_kind": None,
                "diff": {
                    "task_type": {"primary": primary_result.task_type, "jev": jev_result.task_type},
                    "level": {"primary": primary_result.level, "jev": jev_result.level},
                    "risk_tier": {"primary": primary_result.risk_tier, "jev": jev_result.risk_tier},
                    "facts": fact_diffs,
                },
                "primary_unknowns": list(unknown_facts(primary_result.facts)),
                "jev_unknowns": list(unknown_facts(jev_result.facts)),
            }
        else:
            entry = {
                "timestamp": time.time(),
                "source": "jev",
                "primary_source": primary_result.source,
                "seconds": elapsed,
                "success": False,
                "failure_kind": failure_kind or "jev_call_failed",
            }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def run_shadow_if_enabled(
    task: str,
    primary_result: Classification,
    client: Callable[..., object] | None = None,
    blocking: bool = False,
) -> None:
    """Run Jev in shadow mode and log differences without delaying or blocking.

    Does not log the raw task text (privacy requirement §5.2).
    Defaults to non-blocking execution via os.fork (POSIX) or daemon thread.
    """
    if is_jev_kill_switch_active() or jev_stage() != "shadow":
        return

    try:
        sample_rate = float(os.environ.get(JEV_SAMPLE_RATE_ENV, DEFAULT_SHADOW_SAMPLE_RATE))
    except ValueError:
        sample_rate = DEFAULT_SHADOW_SAMPLE_RATE

    if sample_rate <= 0.0 or random.random() > sample_rate:
        return

    if blocking:
        _run_shadow_inline(task, primary_result, client=client)
        return

    if hasattr(os, "fork"):
        try:
            pid = os.fork()
            if pid > 0:
                return  # Parent process returns immediately without delay
            try:
                os.setsid()
                devnull = os.open(os.devnull, os.O_RDWR)
                for fd in (0, 1, 2):
                    with contextlib.suppress(OSError):
                        os.dup2(devnull, fd)
                os.close(devnull)
                _run_shadow_inline(task, primary_result, client=client)
            except Exception:
                pass
            finally:
                os._exit(0)
        except OSError:
            t = threading.Thread(
                target=_run_shadow_inline,
                args=(task, primary_result),
                kwargs={"client": client},
                daemon=True,
            )
            t.start()
    else:
        t = threading.Thread(
            target=_run_shadow_inline,
            args=(task, primary_result),
            kwargs={"client": client},
            daemon=True,
        )
        t.start()
