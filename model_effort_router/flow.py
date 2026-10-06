"""Execute routed workers and an optional verification-driven effort loop."""
import json
import time
from dataclasses import replace

from .difficulty.decision import EFFORTS, EXECUTION_ROLES


class ModelUnavailableBeforeExecution(RuntimeError):
    """Runner-confirmed model rejection before the worker started; the only safe retry signal."""


class WorkerFallbackError(RuntimeError):
    """The configured fallback worker failed after a confirmed primary model rejection."""

    def __init__(self, model, fallback_reason, cause):
        super().__init__(f"fallback model {model} failed: {type(cause).__name__}: {cause}")
        self.model = model
        self.fallback_reason = fallback_reason


class WorkerInterrupted(BaseException):
    """Cancellation that must bypass fallback/retry, with execution metadata when available."""

    def __init__(self, message, *, model=None, fallback_reason=None, result=None):
        super().__init__(message)
        self.model = model
        self.fallback_reason = fallback_reason
        self.result = result


def run_worker(task, plan, *, cwd, runner, env, host, timeout_s, context_packet=None):
    if host.name == "antigravity":
        raise ValueError("Antigravity worker execution is unsupported: Subagent execution isolation is unverified")
    if host.name not in ("codex", "claude"):
        raise ValueError(f"worker execution is unsupported for host {host.name!r}")
    from .adapters.common import ResolvedProfile

    profile = ResolvedProfile(plan.agent, plan.model, plan.requested_effort, plan.applied_effort)
    readonly = plan.decision.role in ("plan", "design", "review", "analysis")
    prompt = context_packet or task
    sandbox = "read-only" if readonly else "workspace-write"
    actual_model = plan.model
    fallback_reason = None
    argv = host.exec.session_argv(profile, prompt, sandbox, host.config)
    try:
        result = runner(argv, cwd=cwd, env=host.exec.session_env(env), timeout_s=timeout_s)
    except ModelUnavailableBeforeExecution as exc:
        if not plan.fallback_model:
            raise
        fallback_reason = type(exc).__name__
        fallback = ResolvedProfile(plan.agent, plan.fallback_model, plan.requested_effort, plan.applied_effort)
        argv = host.exec.session_argv(fallback, prompt, sandbox, host.config)
        try:
            result = runner(argv, cwd=cwd, env=host.exec.session_env(env), timeout_s=timeout_s)
            stream = host.exec.parse_stream(result)
            if not stream.text:
                raise RuntimeError("worker completed without a result message")
        except WorkerInterrupted as exc:
            raise WorkerInterrupted(str(exc), model=plan.fallback_model,
                                    fallback_reason=fallback_reason) from exc
        except Exception as fallback_exc:
            raise WorkerFallbackError(plan.fallback_model, fallback_reason, fallback_exc) from fallback_exc
        actual_model = plan.fallback_model
    else:
        stream = host.exec.parse_stream(result)
        if not stream.text:
            raise RuntimeError("worker completed without a result message")
    return {"role": plan.decision.role, "agent": plan.agent, "model": actual_model,
            "fallback_reason": fallback_reason,
            "requested_effort": plan.requested_effort, "applied_effort": plan.applied_effort,
            "risk_flags": list(plan.risk_flags), "thread_id": stream.thread_id,
            "usage": stream.usage, "message": stream.text}


def _loop_result(attempts, status, error=None):
    keys = ("input", "cached_input", "output", "reasoning_output")
    reported = [a["usage"] for a in attempts if isinstance(a.get("usage"), dict)]
    missing = sum(not isinstance(a.get("usage"), dict) or any(
        not isinstance(a["usage"].get(k), int) or isinstance(a["usage"].get(k), bool)
        or a["usage"][k] < 0 for k in keys) for a in attempts)
    usage = {k: sum(u[k] for u in reported if isinstance(u.get(k), int)
                    and not isinstance(u.get(k), bool) and u[k] >= 0) for k in keys} if reported else None
    increases = sum(EFFORTS.index(b["applied_effort"]) > EFFORTS.index(a["applied_effort"])
                    for a, b in zip(attempts, attempts[1:]))
    first_check = attempts[0].get("verification") if attempts else None
    return {**(attempts[-1] if attempts else {}), "status": status, "attempts": attempts,
            "first_pass": first_check.get("status") == "passed" if first_check else None,
            "escalation_count": increases, "usage": usage, "usage_missing": missing,
            "usage_scope": "worker attempts; excludes models invoked inside the verification command",
            **({"error": error[:300]} if error else {})}


def run_low_first(task, plan, *, cwd, runner, env, host, timeout_s, verify,
                  context_packet=None, verify_timeout_s=300, retry_low=False, approve_xhigh=False,
                  start_effort="low"):
    """Fresh worker sessions keep workspace edits; only a normal failed check promotes effort.

    The caller fixes the verification command before dispatch and validates model support.
    """
    if plan.decision.role not in EXECUTION_ROLES:
        raise ValueError("low-first requires an execution role")
    if start_effort not in ("low", "xhigh") or start_effort == "xhigh" and not approve_xhigh:
        raise ValueError("start_effort must be low or user-approved xhigh")
    attempts, packet = [], context_packet or task
    steps = ("xhigh",) if start_effort == "xhigh" else (("low", "low", *EFFORTS[1:]) if retry_low else EFFORTS)
    current = plan
    for effort in steps:
        if effort == "xhigh" and not approve_xhigh:
            return {**_loop_result(attempts, "approval_required", "User approval is required before xhigh."),
                    "next_effort": "xhigh", "approval_required": True, "continuation_context": packet}
        current = replace(current, requested_effort=effort, applied_effort=effort)
        started = time.monotonic()
        try:
            result = run_worker(task, current, cwd=cwd, runner=runner, env=env, host=host,
                                timeout_s=timeout_s, context_packet=packet)
        except (WorkerInterrupted, KeyboardInterrupt) as exc:
            failed = {"applied_effort": effort, "requested_effort": effort,
                      "model": getattr(exc, "model", None) or current.model,
                      "fallback_reason": getattr(exc, "fallback_reason", None), "usage": None}
            message = str(exc) or "worker interrupted"
            raise WorkerInterrupted(message, model=failed["model"], fallback_reason=failed["fallback_reason"],
                                    result=_loop_result([*attempts, failed], "error", message)) from exc
        except Exception as exc:
            failed = {"applied_effort": effort, "requested_effort": effort,
                      "model": getattr(exc, "model", current.model), "usage": None}
            return _loop_result([*attempts, failed], "error", f"{type(exc).__name__}: {exc}")
        result = {**result, "worker_wall_s": round(time.monotonic() - started, 3)}
        try:
            check = verify(cwd, verify_timeout_s)
            if not isinstance(check, dict) or check.get("status") not in ("passed", "failed"):
                raise ValueError("verification did not return passed or failed")
            code = check.get("exit_code")
            if check["status"] == "passed" and (not isinstance(code, int) or isinstance(code, bool)
                                                 or code != 0 or check.get("reason")):
                raise ValueError("verification passed without a zero exit code")
        except Exception as exc:
            error = f"verification: {type(exc).__name__}: {exc}"
            return _loop_result([*attempts, {**result, "verification": {"status": "error", "reason": error[:300]}}],
                                "error", error)
        except (WorkerInterrupted, KeyboardInterrupt) as exc:
            message = str(exc) or "verification interrupted"
            interrupted = {**result, "verification": {"status": "error", "reason": message[:300]}}
            raise WorkerInterrupted(message, model=result["model"],
                                    fallback_reason=result.get("fallback_reason"),
                                    result=_loop_result([*attempts, interrupted], "error", message)) from exc
        attempts = [*attempts, {**result, "verification": check}]
        if check["status"] == "passed":
            return _loop_result(attempts, "complete")
        if check.get("reason") or not isinstance(code, int) or isinstance(code, bool) or code <= 0:
            return _loop_result(attempts, "error", check.get("reason") or "verification could not finish normally")
        # Fresh sessions avoid host-specific resume/usage semantics; the same cwd retains edits.
        packet = json.dumps({"original_context": context_packet or task,
                             "instruction": "Keep existing changes. Fix the failed verification and report the result.",
                             "previous_effort": effort, "verification": check}, ensure_ascii=False)
        current = replace(current, model=result["model"], fallback_model=None)
    return _loop_result(attempts, "verification_failed", "verification failed at maximum effort")
