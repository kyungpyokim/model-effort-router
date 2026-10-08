# Claude Code Model Effort Router

Claude Code UserPromptSubmit integration for the shared MER runtime. The hook adds route and Subagent guidance; it does not change Main's model or launch a Subagent. SessionStart and PostModelSwitch hooks store the session's model name (interactive sessions only; `claude -p` provides neither) so the first prompt and the prompt right after `/model` can compare it with the routed model; `--resume --model` is unverified. PostModelSwitch needs Claude Code v2.1.251 or later; older versions have not been tested with this hooks.json.

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

Claude Code Agent calls can override `model` per call (aliases `sonnet`, `opus`, `haiku`, `fable`) but take effort only from the agent definition, so the plugin ships `agents/effort-{low,medium,high,xhigh,max}.md`, one worker per effort level. The hook advice names the call to make, for example `Agent(subagent_type="model-effort-router:effort-high", model="opus")`. Haiku has no effort support, so its advice is a plain `Agent(model="haiku")`; a model ID without an alias gets no call, and Main handles the task directly or uses a project agent in `.claude/agents/` with `model:` set. Main may also handle a task directly when its own model and effort already match.
