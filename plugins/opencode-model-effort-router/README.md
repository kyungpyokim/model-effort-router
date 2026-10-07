# OpenCode Model Effort Router

This local OpenCode plugin runs MER automatically on submitted prompts and appends role, model, and effort advice. It also adds the `mer` tool for an explicit recommendation. It does not change the current model or launch a worker.

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

Add the plugin path to the project's `opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["./plugins/opencode-model-effort-router"]
}
```

OpenCode resolves the path relative to `opencode.json`. The bundle is not installed globally and does not edit OpenCode configuration.

The prompt hook checks each submitted prompt before it is sent to the model and adds advice only when MER classifies it for routing. With the default `subscription` classifier, automatic routing uses the installed and authenticated Codex CLI (`codex exec`) for classification. Unrouted prompts pass through unchanged; if routing is disabled or classification fails, the prompt continues without MER advice. OpenCode model selection and worker execution remain manual.

## Model advice

The defaults use OpenCode Zen's `opencode/mimo-v2.6-flash-free` for execution and `opencode/nemotron-3-ultra-free` for reasoning. Reasoning alternatives are `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, and `opencode-go/grok-4.7`. Availability can change; confirm the IDs in `/models`. Override these entries in `.model-effort-router.json` if needed:

```json
{
  "models": {
    "opencode": {
      "execution": {"primary": "provider/model-id", "fallback": null, "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "provider/model-id", "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"], "fallback": null, "efforts": ["low", "medium", "high", "xhigh", "max"]}
    }
  }
}
```

MER recommends the lane's `primary` model based on the routed role and returns `model_options` with that recommendation followed by configured alternatives. Add models available in your OpenCode `/models` list to `alternatives`:

```json
{
  "models": {
    "opencode": {
      "execution": {
        "primary": "opencode/mimo-v2.6-flash-free",
        "alternatives": ["provider/another-model"],
        "fallback": null,
        "efforts": ["low", "medium", "high", "xhigh", "max"]
      },
      "reasoning": {
        "primary": "opencode/nemotron-3-ultra-free",
        "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"],
        "fallback": null,
        "efforts": ["low", "medium", "high", "xhigh", "max"]
      }
    }
  }
}
```

`primary` is MER's recommendation; `alternatives` are user-selectable options and do not trigger automatic model switching. `fallback` remains reserved for a confirmed pre-execution retry. OpenCode lists the MiMo free offer as potentially using prompts to improve the model during its free period. The Nemotron free endpoint is a trial; OpenCode says session data is logged to improve NVIDIA products and asks users not to submit personal or confidential data. Check the current [OpenCode Zen privacy terms](https://opencode.ai/docs/zen/#privacy) before sending sensitive work.

The plugin uses OpenCode's V2 plugin API, pinned to `@opencode/plugin` 2.0.24. It provides route advice only; automatic model/variant selection and `mer run` remain unsupported.
