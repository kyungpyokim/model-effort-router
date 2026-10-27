# Claude Code Model Effort Router

Claude Code `UserPromptSubmit` integration for the shared MER runtime. The hook recommends a role, model, and effort; it does not change Main's active settings or execute work. SessionStart and PostModelSwitch hooks record the active model name so routing advice can compare it with the recommendation. PostModelSwitch needs Claude Code v2.1.251 or later; `claude -p` and `--resume --model` do not provide verified model-switch tracking.

Install the shared runtime with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`router` skill](skills/router/SKILL.md), [`classify` skill](skills/classify/SKILL.md), and [`report` skill](skills/report/SKILL.md). Historical `run` log rows remain readable; current MER versions do not create them.

Configure `primary` and optional `alternatives` for each lane. Alternatives are user-selectable recommendations; legacy model-level `fallback` settings are accepted for compatibility but no longer used.

```json
{
  "models": {
    "claude": {
      "execution": {"primary": "claude-sonnet-5-5", "alternatives": ["claude-fable-5-1", "provider/model-id"]},
      "reasoning": {"primary": "claude-opus-5-5", "alternatives": ["claude-fable-5-1", "provider/another-model"]}
    }
  }
}
```

MER recommends a Claude model and supported effort; select them using Claude Code's model and effort controls. Recommendations do not create Agent profiles or launch subagents.

Historical `run` rows may appear in reports, but current MER versions do not create them. See the [shared configuration and classifier guide](../../README.md) for details.
