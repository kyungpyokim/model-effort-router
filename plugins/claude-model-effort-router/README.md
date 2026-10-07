# Claude Code Model Effort Router

Claude Code UserPromptSubmit integration for the shared MER runtime. The hook adds route and Subagent guidance; it does not change Main's model or launch a Subagent.

Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) for role/effort routing and the [`review` skill](skills/review/SKILL.md) for the implementation-to-review workflow.

Each lane's `primary` is the recommended Subagent model. Add host-supported model IDs to `alternatives` to include user-selectable options in the hook advice; these are not automatic retries. `fallback` remains reserved for a confirmed pre-execution retry:

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

Replace the example alternatives with model IDs available to your Claude Subagents. The hook recommends the primary and lists configured alternatives; it does not change Main's model or launch a Subagent.
