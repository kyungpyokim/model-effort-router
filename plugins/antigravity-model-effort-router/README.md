# Antigravity Model Effort Router

Antigravity hook integration for the shared MER runtime. The `PreInvocation` hook advises Main about a configured target profile for delegated software work. It cannot change Main's active model or launch the Subagent. Antigravity's documented Subagent model controls select `inherit`, `flash`, or `pro` tiers; they do not guarantee an exact model slug or effort, so this configured profile is advisory. `mer run` remains unsupported on this host.

The hook reads `models.antigravity.execution` and prefers the highest supported configured effort (`high`, then `medium`). The default is `gemini-3.8-flash` at `high` effort. It lists configured `alternatives` as user-selectable advice; the `primary` remains the recommendation and alternatives do not trigger retries. Configure it in `.model-effort-router.json` or `~/.config/model-effort-router/config.json`:

```json
{
  "models": {
    "antigravity": {
      "execution": {
        "primary": "gemini-3.8-flash",
        "alternatives": ["provider/model-id"],
        "efforts": ["medium", "high"]
      }
    }
  }
}
```

Replace the example alternative with a model ID supported by your Antigravity setup. Its native Subagent controls select `inherit`, `flash`, or `pro` tiers and do not guarantee an exact model slug or effort, so all model advice remains advisory. Repo config overrides user config. Supported efforts are `medium` and `high`. Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) for role/effort routing and the [`review` skill](skills/review/SKILL.md) for review guidance.
