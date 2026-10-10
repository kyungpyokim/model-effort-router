# Codex Model Effort Router

Codex UserPromptSubmit integration for the shared MER runtime. The hook adds route and Subagent guidance; it does not mutate the current turn or spawn a Subagent.

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

## Workflow log

Each session appends to `~/.local/state/model-effort-router/<session>-<hash>.log.jsonl` (override with `MER_STATE_DIR`). The workflow reads in order: `route` (decision plus `advice`: `spawn`, `inline_same_model`, `advise`, or `no_route`, with the routed model and the invocation Main was told to make) -> `subagent_start` -> `run` (`mer` worker runs) -> `subagent_stop`. Prompts and Subagent output are never stored.

- A `subagent_start` carries `correlation.expected` (the session's latest logged `route`) and `correlation.matched`. `matched_on` says what was compared: `["model"]` on Codex (the Subagent's reported model against the routed model), `["agent_type"]` on Claude (the agent type against `model-effort-router:effort-<effort>`; Claude's payload has no model). Effort is never verified. `matched` is `null` when nothing is comparable: no prior route, the model or agent type is missing, the route was `inline_same_model`, or the Claude route is haiku (no effort agent).
- A `subagent_stop` copies the `correlation` of the `subagent_start` with the same `agent_id`; without one it is `null`.
- Subagent events record Codex's `turn_id` as `agent_turn_id`: it is the child's turn, not the route's `turn_id`.
- Limits: only the last 64 KB of the log is searched for the latest route, and prompts with routing `off` write no `route` event, so a Subagent started after one is compared with the previous logged route.

```bash
jq -c 'select(.event|test("route|subagent|run")) | {ts,event,action:.advice.action,model:(.model // .advice.routed_model),matched:.correlation.matched}' ~/.local/state/model-effort-router/<session>-*.log.jsonl
```
