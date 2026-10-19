# OpenCode Model Effort Router

This local OpenCode plugin adds role, model, and effort recommendations to eligible prompts. It also provides the `mer` tool for explicit routing and `mer_report` for log summaries. Recommendations do not change the active model or execute work.

## Install for a project

Install the shared runtime once from the repository root:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
```

Install this plugin's pinned OpenCode SDK dependency:

```sh
cd plugins/opencode-model-effort-router
bun install --frozen-lockfile
```

Add the plugin path to the project's `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["./plugins/opencode-model-effort-router"]
}
```

OpenCode resolves the path relative to `opencode.json`. The bundle is not installed globally and does not edit OpenCode configuration.

## Model advice

The defaults use OpenCode Zen's `opencode/mimo-v2.6-flash-free` for execution and `opencode/nemotron-3-ultra-free` for reasoning. Reasoning alternatives are `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, and `opencode-go/grok-4.7`. Availability can change; confirm IDs in `/models`. Override entries in `.model-effort-router.json` if needed:

```json
{
  "models": {
    "opencode": {
      "execution": {"primary": "provider/model-id", "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "provider/model-id", "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"], "efforts": ["low", "medium", "high", "xhigh", "max"]}
    }
  }
}
```

`primary` is the recommendation; `alternatives` are user-selectable and do not trigger automatic model switching. Legacy model-level `fallback` settings are accepted for compatibility but no longer used. OpenCode lists the MiMo free offer as potentially using prompts to improve the model during its free period. The Nemotron free endpoint is a trial; OpenCode says session data is logged to improve NVIDIA products and asks users not to submit personal or confidential data. Check the current [OpenCode Zen privacy terms](https://opencode.ai/docs/zen/#privacy) before sending sensitive work.

The plugin uses OpenCode's V2 plugin API, pinned to `@opencode/plugin` 2.0.24. Model selection remains under host/user control.
