# Antigravity Model Effort Router

Antigravity `PreInvocation` integration for the shared MER runtime. The hook classifies the latest user request and recommends a role, model, and effort. It cannot change the active model, and Antigravity's model controls do not guarantee an exact model slug or effort.

On the first model invocation of a turn the hook reads the latest `<USER_REQUEST>` from `transcriptPath`, classifies it with the configured difficulty chain, and recommends the execution or reasoning lane. If the transcript cannot be read, it recommends the configured execution profile at the highest supported effort. Classifier calls may take up to 30 seconds; the hook fails open. Configured alternatives are shown as user-selectable recommendations and do not trigger retries.

Configure `models.antigravity` in `.model-effort-router.json` or `~/.config/model-effort-router/config.json`:

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

Install the shared runtime with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) and [`report` skill](skills/report/SKILL.md). Historical `run` log rows remain readable; current MER versions do not create them.
