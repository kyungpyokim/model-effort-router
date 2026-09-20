#!/usr/bin/env python3
"""Run a routed plan -> implement -> test -> review pipeline from a route JSON file.

The route says who does each role (route JSON); this runner owns where the run is
(state.json in its work directory). Deterministic tests run here, without any model,
and only a failure sends a truncated log to the cheap implementer. A single merged
Sol/Opus review follows a green test run; a review FAIL is fixed by the implementer
first and re-planned by the planning model after that.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import route_reuse  # noqa: E402
import router  # noqa: E402

# Pipeline-owned outcomes sit above the usual 0-9 range so a stage's own exit code is not mistaken for them.
EXIT_GAVE_UP = 10
EXIT_NO_VERDICT = 11
EXIT_SPAWN_FAILED = 12
EXIT_NO_PLAN = 13
STAGE_TIMEOUT_SECONDS = 3600.0
TEST_TIMEOUT_SECONDS = 1800.0
MAX_LOG_LINES = 80
MAX_LOG_CHARS = 6000
MAX_DIFF_CHARS = 60000
MAX_PLAN_CHARS = 20000
TEST_COMMAND_ENV = "MODEL_EFFORT_ROUTER_TEST_CMD"
VERBOSE_ENV = "MODEL_EFFORT_ROUTER_VERBOSE"
VERBOSE_PROMPT_CHARS = 120

VERDICT_RE = re.compile(r"^VERDICT: (PASS|FAIL)$")
ESCALATE_RE = re.compile(r"^ESCALATE: (.+)$")

REVIEW_INSTRUCTIONS = """You are the single merged verification and code review stage of a plan-implement-test-review pipeline.
Judge whether the change satisfies the original request and the plan, and review the diff for correctness, security, regressions, and missing tests. The deterministic tests already ran; their result is given.
Do not modify any file and do not fix anything yourself; report problems for the implementer.
Do not invoke the model-effort router recursively.
Finish with a findings list (empty on PASS), then a last line that is exactly VERDICT: followed by one space and PASS or FAIL."""

FIX_INSTRUCTIONS = """You are the fix stage of a plan-implement-test-review pipeline.
Fix only the reported failure with the smallest correct change; do not redesign, widen scope, or add scaffolding.
If the failure needs an architecture, public API, data migration, or security-boundary change, or the plan no longer matches the code, change nothing and end with a line that starts with ESCALATE and a colon, then the evidence. Difficulty alone is not evidence.
Do not invoke the model-effort router recursively."""


def log(message: str) -> None:
    print(f"[model-effort-router] {message}", file=sys.stderr, flush=True)


def tail(text: str) -> str:
    lines = text.splitlines()[-MAX_LOG_LINES:]
    return "\n".join(lines)[-MAX_LOG_CHARS:]


def last_line(output: str) -> str:
    """A verdict or escalation only counts as the run's final line, never as an echoed prompt line."""
    lines = [line.rstrip() for line in output.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def run_capture(argv: list[str], cwd: str) -> tuple[int, str]:
    """Run a stage, streaming its stdout and keeping a copy for verdict/escalation parsing."""
    try:
        proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, text=True, errors="replace")
    except OSError as exc:
        log(f"cannot start {argv[0]}: {exc}")
        return EXIT_SPAWN_FAILED, ""
    assert proc.stdout is not None
    timer = threading.Timer(STAGE_TIMEOUT_SECONDS, proc.kill)
    timer.start()
    try:
        lines = []
        for line in proc.stdout:
            sys.stdout.write(line)
            lines.append(line)
        return proc.wait(), "".join(lines)
    finally:
        timer.cancel()
        proc.stdout.close()


def is_interactive(command: list[str]) -> bool:
    """The TUI form of a stage command (codex without exec, claude without -p, agy prompt-interactive)."""
    if command[0] == "codex":
        return "exec" not in command[1:2]
    if command[0] == "claude":
        return "-p" not in command and "--print" not in command
    return "--prompt-interactive" in command


def run_tests(commands: list[str], cwd: str) -> str | None:
    """Return None when every command passes, otherwise the failing command and its log tail."""
    for command in commands:
        try:
            proc = subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, errors="replace", check=False, timeout=TEST_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            log(f"test TIMED OUT: {command}")
            return f"$ {command}\n(timed out after {TEST_TIMEOUT_SECONDS:g}s)"
        log(f"test {'passed' if proc.returncode == 0 else 'FAILED'}: {command}")
        if proc.returncode:
            return f"$ {command}\n(exit {proc.returncode})\n{tail(proc.stdout + proc.stderr)}"
    return None


def git_head(cwd: str) -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def git_diff(cwd: str, base: str | None = None) -> tuple[str, bool | None]:
    """The diff to review and whether the run changed anything (None when that cannot be told).

    Diffs the work tree against the HEAD seen when the run started, so commits the implementer
    made still count."""
    # ponytail: uncommitted work from before the run shows up too.
    def git(*args: str) -> str | None:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace", check=False)
        return proc.stdout if proc.returncode == 0 else None

    if git("rev-parse", "--git-dir") is None:
        return "(not a git repository; no diff available)", None
    diff = git("diff", base or "HEAD")
    if diff is None:  # no commits yet
        diff = git("diff") or ""
    untracked = git("ls-files", "--others", "--exclude-standard") or ""
    body = diff[:MAX_DIFF_CHARS] + ("\n... diff truncated ..." if len(diff) > MAX_DIFF_CHARS else "")
    changed = bool(diff.strip() or untracked.strip())
    return (body + (f"\nUntracked files:\n{untracked}" if untracked else "") if changed else "(no changes)"), changed


def escalation(output: str) -> tuple[str, str] | None:
    found = ESCALATE_RE.match(last_line(output))
    return ("escalate", found.group(1)) if found else None


def validated_stage(value: object, name: str, platform: str) -> dict | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not router.model_ok(platform, value.get("model")):
        raise ValueError(f"pipeline {name} stage needs a model")
    if value.get("effort") is not None and value["effort"] not in router.EFFORT_ORDER:
        raise ValueError(f"pipeline {name} stage has an invalid effort")
    return {"model": value["model"], "effort": value.get("effort")}


def reuse_session(payload: dict) -> str | None:
    reuse = payload.get("reuse")
    if reuse is None:
        return None
    session = reuse.get("session") if isinstance(reuse, dict) else None
    if not isinstance(session, str) or not session:
        raise ValueError("route reuse session must be a non-empty string")
    return session


def validated_limits(pipe: dict) -> dict[str, int]:
    limits = {**router.PIPELINE_LIMITS, **(pipe.get("limits") or {})}
    for key in router.PIPELINE_LIMITS:
        if not isinstance(limits.get(key), int) or isinstance(limits[key], bool) or not 0 <= limits[key] <= router.PIPELINE_LIMITS[key]:
            raise ValueError(f"pipeline limit {key} must be an integer from 0 to {router.PIPELINE_LIMITS[key]}")
    return {key: limits[key] for key in router.PIPELINE_LIMITS}


class Pipeline:
    def __init__(self, payload: dict, test_commands: list[str], cwd: str, workdir: Path, plan_file: Path):
        self.commands, self.route_plan_path = router.validated_commands(payload)
        pipe = payload.get("pipeline") or {}
        self.platform = payload["platform"]
        self.limits = validated_limits(pipe)
        self.reviewer = validated_stage(pipe.get("review"), "review", self.platform)
        self.planner = validated_stage(pipe.get("replan"), "replan", self.platform)
        step = payload["steps"][-1]
        self.implementer = {"model": step["model"], "effort": step.get("effort")}
        self.task = pipe["task"] if isinstance(pipe.get("task"), str) else "(the original request is in the earlier prompt of this run)"
        self.scope_guard = f"\n{router.AUTOBAHN_SCOPE_GUARD}" if payload.get("scope_guard") else ""
        self.test_commands, self.cwd, self.workdir, self.plan_file = test_commands, cwd, workdir, plan_file
        self.counts = {"test": 0, "review": 0}
        self.replans = 0
        self.reviews = 0
        self.tests_passed: list[str] = []
        self.verbose = bool(os.environ.get(VERBOSE_ENV))
        self.base = git_head(cwd)
        self.plan_step = payload["steps"][0]

    @staticmethod
    def validate(payload: dict) -> None:
        pipe = payload.get("pipeline") or {}
        validated_limits(pipe)
        validated_stage(pipe.get("review"), "review", payload["platform"])
        validated_stage(pipe.get("replan"), "replan", payload["platform"])
        reuse_session(payload)
        commands, plan_path = router.validated_commands(payload)
        if plan_path is not None and not Path(plan_path).is_absolute():
            raise ValueError("route plan path must be absolute")
        if len(commands) > 1 and any(is_interactive(command) for command in commands):
            raise ValueError("a multi-stage route cannot use interactive commands")

    def state(self, phase: str, who: dict | None = None, attempt: int | None = None) -> None:
        state = {"phase": phase, "test_fixes": self.counts["test"], "review_fixes": self.counts["review"], "reviews": self.reviews, "replans": self.replans}
        (self.workdir / "state.json").write_text(json.dumps(state), encoding="utf-8")
        parts = [f"phase={phase}"]
        if who:
            parts += [f"model={who['model']}", f"effort={who.get('effort') or 'none'}"]
        if attempt:
            parts.append(f"attempt={attempt}")
        log(" ".join(parts))

    def stage(self, phase: str, argv: list[str], who: dict | None = None, attempt: int | None = None) -> tuple[int, str]:
        self.state(phase, who, attempt)
        if self.verbose:
            log("command: " + shlex.join([*argv[:-1], argv[-1][:VERBOSE_PROMPT_CHARS] + "..."]))
        return run_capture(argv, self.cwd)

    def plan_text(self) -> str:
        try:
            return self.plan_file.read_text(encoding="utf-8")[:MAX_PLAN_CHARS]
        except OSError:
            return "(no plan file)"

    def fix(self, kind: str, detail: str) -> tuple[int, str]:
        prompt = (
            f"Fix a failed {kind} check.\nOriginal request:\n{self.task}\n\n"
            f"Plan file (read first when it exists): {self.plan_file}\n\nFailure:\n{detail}\n"
        )
        argv = router.stage_command(self.platform, self.implementer, FIX_INSTRUCTIONS + self.scope_guard, prompt, "edit")
        return self.stage("fix", argv, self.implementer, self.counts[kind])

    def replan(self, kind: str, detail: str) -> tuple[int, str]:
        assert self.planner is not None
        plan_prompt = (
            f"Re-plan after a failed attempt ({kind}).\nOriginal request:\n{self.task}\n\n"
            f"Evidence:\n{detail}\n\nThe repository already holds the previous attempt's changes; plan from its current state.\n"
            f"Write the plan JSON to exactly: {self.plan_file}\n"
        )
        instructions = router.PLANNER_INSTRUCTIONS_TEMPLATE.format(plan_path=self.plan_file) + self.scope_guard
        argv = router.stage_command(self.platform, self.planner, instructions, plan_prompt, "plan", str(self.plan_file))
        rc, _ = self.stage("replan", argv, self.planner, self.replans)
        if rc:
            return rc, ""
        if not self.plan_file.exists():
            log("the re-planner wrote no plan file")
            return EXIT_NO_PLAN, ""
        execute_prompt = f"{router.IMPLEMENTER_PROMPT_PREFIX}{self.task}\n\nPlan file to read first: {self.plan_file}\n"
        instructions = router.IMPLEMENTER_INSTRUCTIONS_TEMPLATE.format(plan_path=self.plan_file) + self.scope_guard
        argv = router.stage_command(self.platform, self.implementer, instructions, execute_prompt, "edit")
        return self.stage("implement", argv, self.implementer, self.replans)

    def review(self) -> tuple[str, str] | int | None:
        """None on PASS, a failure on FAIL, or an exit code when the review itself broke."""
        assert self.reviewer is not None
        tests = "\n".join(f"PASS: {command}" for command in self.tests_passed) or (
            "No deterministic test command was configured; rely on the implementer's reported checks."
        )
        diff, changed = git_diff(self.cwd, self.base)
        if changed is False:
            # Fail closed without spending a review: an implementer that changed nothing did not finish.
            log("no changes in the working tree after implementation")
            return ("review", "The implementer finished without changing any file. Make the requested change.")
        prompt = (
            f"Original request:\n{self.task}\n\nPlan:\n{self.plan_text()}\n\n"
            f"Test results:\n{tests}\n\nDiff:\n{diff}\n"
        )
        self.reviews += 1
        argv = router.stage_command(self.platform, self.reviewer, REVIEW_INSTRUCTIONS, prompt, "read")
        rc, output = self.stage("review", argv, self.reviewer, self.reviews)
        if rc:
            return rc
        verdict = VERDICT_RE.match(last_line(output))
        if not verdict:
            log("review did not end with a VERDICT line; stopping instead of guessing")
            return EXIT_NO_VERDICT
        return None if verdict.group(1) == "PASS" else ("review", output[-MAX_LOG_CHARS:])

    def check(self) -> tuple[str, str] | int | None:
        self.tests_passed = []
        if self.test_commands:
            self.state("test")
        failure = run_tests(self.test_commands, self.cwd)
        if failure:
            return ("test", failure)
        self.tests_passed = list(self.test_commands)
        return self.review() if self.reviewer else None

    def run(self) -> int:
        if self.route_plan_path:
            rc, _ = self.stage("plan", self.commands[0], self.plan_step)
            if rc:
                return rc
            if not self.plan_file.exists():
                log("the planner wrote no plan file")
                return EXIT_NO_PLAN
        rc, output = self.stage("implement", self.commands[-1], self.implementer)
        if rc:
            return rc
        failure: tuple[str, str] | int | None = escalation(output)
        budget = {"test": self.limits["max_test_fixes"], "review": self.limits["review_fixes_before_replan"]}
        while True:
            if failure is None:
                failure = self.check()
            if failure is None:
                self.state("done")
                return 0
            if isinstance(failure, int):
                return failure
            kind, detail = failure
            if kind in budget and self.counts[kind] < budget[kind]:
                self.counts[kind] += 1
                rc, output = self.fix(kind, detail)
            elif self.planner and self.replans < self.limits["max_replans"]:
                self.replans += 1
                self.counts = {"test": 0, "review": 0}
                rc, output = self.replan(kind, detail)
            else:
                log(f"giving up: {kind} still failing after the fix and re-plan budget")
                self.state("failed")
                return EXIT_GAVE_UP
            if rc:
                return rc
            failure = escalation(output)


def run_route(payload: object, test_commands: list[str], cwd: str, cleanup: bool = False, own_session: str | None = None) -> int:
    _, plan_path = router.validated_commands(payload)
    workdir = Path(plan_path).parent if plan_path else Path(tempfile.mkdtemp(prefix="model-effort-pipeline-")).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    plan_file = Path(plan_path) if plan_path else workdir / "plan.json"
    try:
        runner = Pipeline(payload, test_commands, cwd, workdir, plan_file)
        exit_code = runner.run()
        session = reuse_session(payload)
        # Only the runner's own session may be marked: a shared route file must not write other sessions' records.
        if session and session == (own_session or os.environ.get(route_reuse.SESSION_ENV)):
            route_reuse.mark_outcome(session, runner.replans, exit_code)
        return exit_code
    finally:
        # A directory this runner made is always removed; a route's own plan dir only when asked,
        # and only when it is the router's own codex-route-* directory.
        if plan_path is None or (cleanup and workdir.name.startswith("codex-route-")):
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route-file", type=Path, required=True)
    parser.add_argument("--test-cmd", action="append", default=[], metavar="CMD", help=f"Deterministic check run without a model (repeatable; also {TEST_COMMAND_ENV})")
    parser.add_argument("--session", default=None, metavar="KEY", help=f"Session whose stored route this run may invalidate (default {route_reuse.SESSION_ENV})")
    parser.add_argument("--verbose", action="store_true", help=f"Log each stage command (also {VERBOSE_ENV})")
    parser.add_argument("--cleanup-plan-dir", action="store_true", help="Remove the route's plan directory afterwards")
    args = parser.parse_args(argv)
    if args.verbose:
        os.environ[VERBOSE_ENV] = "1"
    test_commands = [*args.test_cmd, *([os.environ[TEST_COMMAND_ENV]] if os.environ.get(TEST_COMMAND_ENV) else [])]
    try:
        payload = json.loads(args.route_file.read_text(encoding="utf-8"))
        router.validated_commands(payload)
        Pipeline.validate(payload)
    except (OSError, json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
        print(f"invalid route file: {exc}", file=sys.stderr)
        return 2
    commands, _ = router.validated_commands(payload)
    if len(commands) == 1 and is_interactive(commands[0]):
        # An interactive session needs the terminal: hand off without capturing anything.
        return subprocess.call(commands[0])
    return run_route(payload, test_commands, os.getcwd(), args.cleanup_plan_dir, args.session)


if __name__ == "__main__":
    raise SystemExit(main())
