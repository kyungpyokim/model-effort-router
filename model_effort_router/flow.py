"""Execute exactly one already-routed worker request."""


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

    def __init__(self, message, *, model=None, fallback_reason=None):
        super().__init__(message)
        self.model = model
        self.fallback_reason = fallback_reason


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
