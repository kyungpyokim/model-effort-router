# Codex Model Effort Router

Codex UserPromptSubmit integration for the shared MER runtime. The hook adds route and Subagent guidance; it does not mutate the current turn or spawn a Subagent. Main is responsible for following the advice: prepare the task packet, dispatch the selected host-native Subagent, and integrate its result.

Routing is advisory-only. The current hook signals do not establish a verified dispatch-to-child identity bridge for an edit gate. Hooks cannot force delegation for read-only work, universally enforce code edits, or guarantee runtime model/effort compliance. Main should apply the recommended route when dispatching; model and effort remain recommendations unless Codex exposes enforceable signals.

Install the shared runtime from the repository with `python3 scripts/install_core.py`. Use `MER_CORE_PATH="$PWD"` for development. See the [`classify` skill](skills/classify/SKILL.md) for role/effort routing and the [`review` skill](skills/review/SKILL.md) for the implementation-to-review workflow.

Each lane's `primary` is the recommended Subagent model. Add host-supported model IDs to `alternatives` to include user-selectable options in the hook advice; these are not automatic retries. `fallback` remains reserved for a confirmed pre-execution retry:

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

Replace the example alternatives with model IDs available to your Codex Subagents. The hook recommends the primary and lists configured alternatives; it does not change the current turn's model or launch a Subagent.
