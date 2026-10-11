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
- Classifier fallback: a `route` event carries `classifier_causes` (e.g. `["jev:HTTP 503"]`: backend names, error types or HTTP statuses, never error messages) when a classifier failed and routing fell back, including on `no_route` and when every classifier fails. The hook shows `[model-effort-router] classifier fallback: jev failed (HTTP 503) → classified by openai_decisions`, or `classifier failed: ...; no routing advice this turn.` when every classifier fails. The Codex and Claude desktop apps do not show hook messages, so the advice also asks Main to tell the user.
- A `subagent_stop` copies the `correlation` of the `subagent_start` with the same `agent_id`; without one it is `null`.
- Subagent events record Codex's `turn_id` as `agent_turn_id`: it is the child's turn, not the route's `turn_id`.
- The Codex app and the Claude desktop app do not display hook output, so the advice asks Main to start its first message of the turn (before any tool call) with `[routed: <model> · effort <effort>]` when it will spawn the Subagent, or `[main: <model>]` when Main will handle the task. This is an instruction to the model, not a guarantee; the log is the record. On Codex the advice also tells Main not to pass `agent_type` to `spawn_agent`, because a role config (`.codex/agents/*.toml`) overrides the routed model and effort; a mismatch shows as `correlation.matched: false`.
- Limits: only the last 64 KB of the log is searched for the latest route, and prompts with routing `off` write no `route` event, so a Subagent started after one is compared with the previous logged route.

```bash
jq -c 'select(.event|test("route|subagent|run")) | {ts,event,action:.advice.action,model:(.model // .advice.routed_model),matched:.correlation.matched}' ~/.local/state/model-effort-router/<session>-*.log.jsonl
```

### Experimental: policy mode

`router.mode = "policy"` skips the classifier. The `UserPromptSubmit` hook injects the static model map (execution and reasoning lanes with their supported efforts) and Main itself picks the lane and effort and decides whether to spawn a Subagent. Every non-blank prompt gets the policy (no keyword prefilter; Main skips trivial requests itself). It makes no model call. Codex and Claude only; other hosts stay silent.

- Enable: set `{"router": {"mode": "policy"}}` in the global user config, or start a prompt with `/router policy`. Switch back with `"mode": "auto"` (the default). An explicit `/router role=<role> effort=<effort>` keeps its normal behavior.
- This is an A/B experiment against `auto`; the losing mode will be removed after the comparison.
- Compare the two from the workflow logs: `python3 scripts/compare_modes.py [--since <unix ts>]` prints routed prompts, spawn-advised count, Subagent starts, match counts, median hook latency, and classifier tokens per mode and host.
