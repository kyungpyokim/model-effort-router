# Codex Model Effort Router

Codex `UserPromptSubmit` integration for the shared MER runtime. The hook recommends a role, model, and effort; it does not change the active turn's settings or execute work.

Install the shared runtime with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`router` skill](skills/router/SKILL.md), [`classify` skill](skills/classify/SKILL.md), and [`report` skill](skills/report/SKILL.md). Historical `run` log rows remain readable; current MER versions do not create them.

Configure `primary` and optional `alternatives` for each lane. Alternatives are user-selectable recommendations and do not switch models automatically. Legacy model-level `fallback` settings are accepted for compatibility but no longer used.

```json
{
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "alternatives": ["gpt-6-astra", "provider/model-id"]},
      "reasoning": {"primary": "gpt-6.1-sol", "alternatives": ["gpt-6-astra", "provider/another-model"]}
    }
  }
}
```

The host reports Subagent lifecycle events when available; MER does not launch those agents. Historical `run` rows may appear in reports, but current MER versions do not create them.

See the [shared configuration and classifier guide](../../README.md) for the complete setup.
