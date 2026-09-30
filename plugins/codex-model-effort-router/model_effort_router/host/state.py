"""Per-session RoutePlan state (JSON, atomic writes) and stage execution state (spec 19)."""
import contextlib
import hashlib
import json
import os
import re
import tempfile
import time

try:
    import fcntl
except ImportError:  # ponytail: no locking on platforms without fcntl (Windows); hooks are sequential per session anyway
    fcntl = None

from ..adapters.codex import CodexConfig, resolve
from ..profiles.profiles import Profile

MAX_FIX = 2
STATE_ENV = "MER_STATE_DIR"
STALE_RUNNING_S = 30 * 60  # a stage "running" longer than this is presumed dead
PLAN_TTL_S = 2 * 60 * 60  # an unfinished plan older than this is dropped on the next no_route prompt
MAX_IDLE_PROMPTS = 3  # consecutive no_route prompts after which the plan is dropped


def state_dir(env):
    if env.get(STATE_ENV):
        return env[STATE_ENV]
    base = env.get("XDG_STATE_HOME") or os.path.join(env.get("HOME") or os.path.expanduser("~"), ".local", "state")
    return os.path.join(base, "model-effort-router")


def _safe(session_id):
    """Readable prefix + hash of the raw id: `a/b` and `a_b` never share a file, `../x` stays inside the dir."""
    raw = str(session_id)
    prefix = re.sub(r"[^A-Za-z0-9._-]", "_", raw)[:64] or "_unknown"
    return f"{prefix}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"


@contextlib.contextmanager
def locked(sdir, session_id):
    """Best-effort exclusive per-session lock around load-check-save; proceeds unlocked if it cannot be taken."""
    handle = None
    try:
        os.makedirs(sdir, exist_ok=True)
        handle = open(os.path.join(sdir, _safe(session_id) + ".lock"), "a")
        if fcntl:
            fcntl.flock(handle, fcntl.LOCK_EX)
    except OSError:
        pass
    try:
        yield
    finally:
        if handle:
            handle.close()  # closing releases the flock


def plan_path(sdir, session_id):
    return os.path.join(sdir, _safe(session_id) + ".plan.json")


def log_path(sdir, session_id):
    return os.path.join(sdir, _safe(session_id) + ".log.jsonl")


def save(sdir, session_id, state):
    os.makedirs(sdir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=sdir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, plan_path(sdir, session_id))
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load(sdir, session_id):
    """None when the session has no plan; raises on a corrupt file (callers fail open and log)."""
    try:
        with open(plan_path(sdir, session_id), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def delete(sdir, session_id):
    try:
        os.unlink(plan_path(sdir, session_id))
    except FileNotFoundError:
        pass


def build_state(plan, *, session_id, gate_cmd, now=None, config=CodexConfig()):
    """Resolve each stage's abstract profile to the host's model + applied effort (spec 12)."""
    stages, order = {}, []
    for s in plan.policy.stages:
        order.append(s.stage)
        if s.stage == "test_gate":
            continue
        r = resolve(Profile(s.tier, s.effort), config)
        stages[s.stage] = {"tier": r.tier, "model": r.model, "requested_effort": r.requested_effort,
                           "effort": r.applied_effort, "status": "pending", "spawns": 0, "started_at": None}
    return {"version": 1, "session_id": session_id, "target": plan.target,
            "level": plan.policy.level, "order": order, "stages": stages, "fix_count": 0,
            "max_fix": MAX_FIX, "gate_cmd": gate_cmd,
            "created": time.time() if now is None else now, "idle_prompts": 0}


def after_no_route(state, now):
    """('drop', None) or ('keep', new_state) for a prompt that did not route (keeps "yes go ahead" working)."""
    finished = all(s["status"] == "done" for s in state["stages"].values())
    idle = state.get("idle_prompts", 0) + 1
    if finished or now - state["created"] > PLAN_TTL_S or idle >= MAX_IDLE_PROMPTS:
        return "drop", None
    return "keep", {**state, "idle_prompts": idle}


def _required(stage, st):
    return (f'spawn_agent(task_name="mer_{stage}", fork_turns="none", '
            f'model="{st["model"]}", reasoning_effort="{st["effort"]}")')


def check_spawn(state, tool_input, now=None):
    """Pure guard. Returns (decision, reason, stage, new_state); decision is 'allow' or 'deny'.

    Non-Router spawns are allowed untouched (stage None). A name is a Router stage spawn when, lowercased with
    `-` read as `_`, it starts with `mer_`; one that is not a planned stage is denied.
    Any implement spawn after the first is a fix round, however the previous one ended.
    Known limit (kept on purpose): a spawn the host itself rejects still counts, so its retry is a fix round;
    a quick-retry exemption would let `--mark failed` bypass the fix budget.
    """
    now = time.time() if now is None else now
    name = tool_input.get("task_name") if isinstance(tool_input, dict) else None
    norm = name.lower().replace("-", "_") if isinstance(name, str) else ""
    if not norm.startswith("mer_"):
        return "allow", None, None, state
    stage = norm[4:]
    st = state["stages"].get(stage)
    if st is None:
        valid = ", ".join(f"mer_{s}" for s in state["stages"])
        return "deny", f"{name!r} is not a planned Router stage. Valid stage task_names: {valid}.", stage or "?", state

    problems = []
    if tool_input.get("fork_turns") != "none":
        problems.append(f'fork_turns must be "none" (got {tool_input.get("fork_turns")!r})')
    if tool_input.get("model") != st["model"]:
        problems.append(f'model must be "{st["model"]}" (got {tool_input.get("model")!r})')
    if tool_input.get("reasoning_effort") != st["effort"]:
        problems.append(f'reasoning_effort must be "{st["effort"]}" (got {tool_input.get("reasoning_effort")!r})')
    if problems:
        return "deny", f"Router plan mismatch for stage {stage}: " + "; ".join(problems) + \
            f". Required call: {_required(stage, st)}", stage, state

    new = json.loads(json.dumps(state))  # never mutate the loaded state
    nst = new["stages"][stage]
    gate = state["gate_cmd"]
    if nst["status"] == "running" and now - (nst["started_at"] or now) > STALE_RUNNING_S:
        nst["status"] = "failed"  # presumed dead; respawn allowed (and counted, for implement)
    if nst["status"] == "running":
        return "deny", (f"Stage {stage} is already running; wait for its result instead of spawning it again. "
                        f"If it actually failed or was cancelled, run: python3 {gate} --session "
                        f"{state['session_id']} --mark {stage} failed"), stage, state
    if nst["status"] == "done" and stage != "implement":
        return "deny", f"Stage {stage} is already done; reuse its result.", stage, state
    if stage == "implement" and nst["spawns"] >= 1:
        if new["fix_count"] >= new["max_fix"]:
            return "deny", (f"Fix limit reached ({new['max_fix']} fix rounds). Stop, report the remaining "
                            "failures to the user and ask how to proceed."), stage, state
        new["fix_count"] += 1
        if "review" in new["stages"]:
            new["stages"]["review"]["status"] = "pending"  # review must re-run after a fix (spec 19)
    nst["status"] = "running"
    nst["spawns"] += 1
    nst["started_at"] = now
    earlier = [s for s in new["order"] if s in new["stages"]]
    for prev in earlier[: earlier.index(stage)]:  # the agent moved on, so earlier stages finished
        if new["stages"][prev]["status"] == "running":
            new["stages"][prev]["status"] = "done"
    return "allow", None, stage, new
