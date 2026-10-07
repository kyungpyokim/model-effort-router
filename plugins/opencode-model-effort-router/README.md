# OpenCode Model Effort Router

This local OpenCode plugin adds the `route_advice` tool. It asks the shared MER runtime for role, model, and effort advice; it does not change the current model, launch a worker, or classify the task on its own. OpenCode supplies `role` and `effort` to the tool.

## Install for a project

Install the shared core once from the repository root:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
```

Install this plugin's pinned OpenCode SDK dependency:

```sh
cd plugins/opencode-model-effort-router
bun install --frozen-lockfile
```

Add the plugin path to the project's `opencode.json` (the V1 plugin API uses the singular `plugin` key):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugin": ["./plugins/opencode-model-effort-router"]
}
```

OpenCode resolves the path relative to `opencode.json`. The bundle is not installed globally and does not edit OpenCode configuration.

## Model advice

The built-in examples use `openai/gpt-5.2` for execution and `anthropic/claude-sonnet-4-5` for reasoning. Availability depends on the providers and models enabled in the current project. Override these entries in `.model-effort-router.json` to match the models shown by `/models`:

```json
{
  "models": {
    "opencode": {
      "execution": {"primary": "provider/model-id", "fallback": null, "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "provider/model-id", "fallback": null, "efforts": ["low", "medium", "high", "xhigh"]}
    }
  }
}
```

The plugin uses OpenCode's stable V1 custom-tool API, pinned at `@opencode-ai/plugin` 1.18.35. OpenCode's V2 plugin API is beta and its package's published tool exports do not yet match the V2 documentation. This version provides route advice only; automatic model/variant selection and `mer run` remain unsupported.
