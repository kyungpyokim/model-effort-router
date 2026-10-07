#!/usr/bin/env python3
"""Suggest the configured model profile for native Antigravity Subagents."""

import json
import os
import sys
from pathlib import Path


def main():
    try:
        data = json.loads(sys.stdin.read())
        if data.get("invocationNum") != 0:
            return
        home = Path.home()
        data_home = Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share")
        runtime = Path(os.environ.get("MER_CORE_PATH") or data_home / "model-effort-router/runtime")
        if not runtime.is_absolute():
            return
        sys.path.insert(0, str(runtime))
        from model_effort_router.adapters.antigravity import resolve_model
        from model_effort_router.host.advice import effort_pair
        from model_effort_router.host.codex_hooks import load_configs
        from model_effort_router.policy.config import resolve_config

        workspaces = data.get("workspacePaths") or []
        repo, user = load_configs(workspaces[0] if workspaces else os.getcwd(), os.environ)
        config = resolve_config(repo=repo, user=user)
        if config.mode != "auto":
            return
        execution = config.models["antigravity"]["execution"]
        supported = [effort for effort in ("medium", "high") if effort in execution["efforts"]]
        if not supported:
            return
        effort = supported[-1]
        primary = execution["primary"]
        resolve_model(primary, effort, supported)  # validates the primary/effort pair
        alternatives = tuple(
            model
            for model in execution.get("alternatives", [])
            if model != primary and resolve_model(model, effort, supported).model
        )
        model_advice = effort_pair(primary, effort)  # display the bare model; the slug folds the effort in
        if alternatives:
            model_advice += (
                f"; other configured options: {', '.join(alternatives)} (user-selectable, not automatic fallbacks)"
            )
        message = (
            "[model-effort-router] Preferred delegated profile: "
            f"{model_advice}. Give a native Antigravity Subagent a concise context packet "
            "from the current request and relevant conversation. For code changes, delegate implementation, "
            "integrate it, then run the separate write-capable review workflow. This is guidance for "
            "Subagent selection; the host's current Subagent controls do not guarantee this exact model or "
            "effort, and the hook cannot change the current Main model. Do not claim the profile was applied "
            "unless the host confirms it."
        )
        print(json.dumps({"injectSteps": [{"ephemeralMessage": message}]}))
    except Exception:
        return  # Hooks must fail open and never block the user's request.


if __name__ == "__main__":
    main()
