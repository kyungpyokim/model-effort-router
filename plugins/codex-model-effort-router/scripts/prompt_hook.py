#!/usr/bin/env python3
"""Force a single model-effort route from a Codex or Claude prompt hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


BYPASS_ENV = "MODEL_EFFORT_ROUTER_HOOK_BYPASS"


def extract_prompt(payload: object) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("prompt", "user_prompt"):
        prompt = payload.get(key)
        if isinstance(prompt, str) and prompt.strip():
            return prompt.strip()
    return None


def hook_env(environ: dict[str, str]) -> dict[str, str]:
    return {**environ, BYPASS_ENV: "1"}


def run_route(prompt: str, platform: str, root: Path, cwd: str | None, environ: dict[str, str]) -> tuple[bool, str]:
    router = root / "scripts" / "router.py"
    workdir = cwd if cwd and Path(cwd).is_dir() else None
    env = hook_env(environ)
    classified = subprocess.run(
        [sys.executable, str(router), prompt, "--platform", platform, "--format", "json"],
        text=True,
        capture_output=True,
        check=False,
        cwd=workdir,
        env=env,
    )
    if classified.returncode:
        return False, "model-effort classification failed"
    try:
        json.loads(classified.stdout)
    except json.JSONDecodeError:
        return False, "model-effort classification returned invalid JSON"

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as route_file:
        route_file.write(classified.stdout)
        route_path = Path(route_file.name)
    try:
        replay = subprocess.run(
            [sys.executable, str(router), "--route-file", str(route_path)],
            text=True,
            capture_output=True,
            check=False,
            cwd=workdir,
            env=env,
        )
        if replay.returncode or not replay.stdout.strip():
            return False, "model-effort route replay failed"
        executed = subprocess.run(
            ["bash", "-c", replay.stdout.strip()],
            check=False,
            cwd=workdir,
            env=env,
            stdout=sys.stderr,
            stderr=sys.stderr,
        )
        return executed.returncode == 0, "completed" if executed.returncode == 0 else f"failed with exit status {executed.returncode}"
    finally:
        route_path.unlink(missing_ok=True)


def handle_payload(payload: object, platform: str, root: Path, environ: dict[str, str]) -> dict[str, str] | None:
    if environ.get(BYPASS_ENV) == "1":
        return None
    prompt = extract_prompt(payload)
    if not prompt or prompt.startswith("/"):
        return None
    cwd = payload.get("cwd") if isinstance(payload, dict) and isinstance(payload.get("cwd"), str) else None
    _, detail = run_route(prompt, platform, root, cwd, environ)
    return {"decision": "block", "reason": f"Model-effort routed task {detail}; the original session prompt was blocked."}


def main() -> int:
    platform = sys.argv[1] if len(sys.argv) == 2 else None
    if platform not in {"codex", "claude-code"}:
        print("usage: prompt_hook.py <codex|claude-code>", file=sys.stderr)
        return 2
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    response = handle_payload(payload, platform, Path(__file__).resolve().parents[1], dict(os.environ))
    if response:
        print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
