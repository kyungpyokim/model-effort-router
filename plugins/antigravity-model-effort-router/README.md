# Antigravity Model Effort Router

Antigravity hook integration for the shared MER runtime. The `PreInvocation` hook advises Main about a configured target profile for delegated software work. It cannot change Main's active model or launch the Subagent. Antigravity's documented Subagent model controls select `inherit`, `flash`, or `pro` tiers; they do not guarantee an exact model slug or effort, so this configured profile is advisory. `mer run` remains unsupported on this host.

On the first model invocation of a turn the hook reads the latest `<USER_REQUEST>` from `transcriptPath` (the payload has no prompt), classifies it with the configured difficulty chain, and advises the lane (`execution` or `reasoning`) and effort (`medium`/`high`) for that request. If the request cannot be read from the transcript it falls back to static advice from `models.antigravity.execution` at the highest supported effort (default `gemini-3.8-flash`, `high`). Classifiers are network calls, so the hook timeout is 30s and it fails open. It lists configured `alternatives` as user-selectable advice; the `primary` remains the recommendation and alternatives do not trigger retries. Configure it in `.model-effort-router.json` or `~/.config/model-effort-router/config.json`:

```json
{
  "models": {
    "antigravity": {
      "execution": {
        "primary": "gemini-3.8-flash",
        "alternatives": ["claude-sonnet-5-5", "provider/model-id"],
        "efforts": ["medium", "high"]
      }
    }
  }
}
```

Replace the example alternative with a model ID supported by your Antigravity setup. Its native Subagent controls select `inherit`, `flash`, or `pro` tiers and do not guarantee an exact model slug or effort, so all model advice remains advisory. Repo config overrides user config. Supported efforts are `medium` and `high`. Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) for role/effort routing and the [`review` skill](skills/review/SKILL.md) for review guidance. The [`report` skill](skills/report/SKILL.md) (`mer report`) lists the model, effort, and token usage recorded in the logs.
