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
        from model_effort_router.host.codex_hooks import load_configs
        from model_effort_router.policy.config import resolve_config

        workspaces = data.get("workspacePaths") or []
        repo, user = load_configs(workspaces[0] if workspaces else os.getcwd(), os.environ)
        config = resolve_config(repo=repo, user=user)
        if config.mode != "auto":
            return
        profile = config.antigravity_hook
        selected = resolve_model(profile["model"], profile["effort"]).model
        message = (
            "[model-effort-router] Preferred delegated profile: "
            f"{selected}, effort {profile['effort']}. Give a native Antigravity Subagent a concise context packet "
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
