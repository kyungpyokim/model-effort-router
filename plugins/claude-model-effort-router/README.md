# Model-Effort Router (Claude Code plugin)

Same two parts as the Codex plugin, on the Claude Code host. The **`mer` CLI is the main path**: it classifies a request, runs it as one `claude -p` session with the model and effort the Router chose, gates it, escalates the same session (`--resume`) on a failed gate, and adds an independent read-only review for high-risk work. The **UserPromptSubmit hook is advisory only**: it adds a short note (difficulty, risk flags, recommended model/effort, plan-first and review advice) and never blocks, denies or enforces anything.

Status: unit-tested only. Nothing here has been installed or run against a live Claude Code (see "Unverified").

## Install (run these yourself)

```bash
# from the repo root (python3 scripts/sync_plugin.py first if you changed model_effort_router/)
claude plugin marketplace add .
claude plugin install model-effort-router@model-effort-router-local
```

The marketplace file is `.claude-plugin/marketplace.json` at the repo root. Claude Code asks you to trust plugin hooks; until you do there is no advice. After updating the plugin, re-check the hook in `/hooks`.

## Models and effort

| tier | model | efforts |
|---|---|---|
| economy, balanced | claude-sonnet-5-5 | low, medium, high, xhigh, max |
| frontier | claude-opus-5-5 | low, medium, high, xhigh, max |

A model with no supported efforts (claude-haiku-4-5, choose it through `ClaudeConfig`) gets no `--effort` flag. Switch inside Claude Code with `/model` and `/effort`.

## mer CLI

`python3 <plugin>/bin/mer run [--cwd DIR] [--dry-run [--level L1..L5 | --classify]] [--max-escalations N] [--json] '<request>'` (the wrapper defaults to `--host claude`; `--host codex` or `MER_HOST=codex` selects the Codex host).

- Implement sessions: `claude -p --output-format json --model M [--effort E] --permission-mode auto`. Resumes add `--resume <session_id>`. No bypass flags are used anywhere.
- Independent review (L4/L5, auth/security) and plan-only sessions: `--permission-mode dontAsk --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --disallowedTools Agent --strict-mcp-config --setting-sources user`. `--tools` limits the tool set itself (`--allowedTools` only pre-approves, so project settings or MCP could otherwise grant Edit/Bash); project/local settings and MCP servers are not loaded.
- Subagent policy (`session.subagent_policy`): L1-L4 deny the Agent tool (`--disallowedTools Agent`); L5 leaves it allowed because Claude Code has no concurrency cap, so only the prompt hint limits it; `codex` policy passes no flag.
- `mer chat '<request>'` classifies, then replaces itself with interactive `claude --model M [--effort E] -- <request>` (mer changes into `--cwd` first; Claude Code has no cwd flag). Plan/review-only requests start in `--permission-mode plan`.
- `--dry-run` prints the decision, ladder and the exact first `claude` command and starts no session.
- Usage is per `claude -p` invocation (input = input + cache creation + cache read tokens); it is logged per call with thread ids (`session_id`), never prompt text.
- Sessions started by mer run with `MER_CLASSIFIER=1`, so this plugin's hook stays quiet inside them.
- The difficulty backend is host-independent (Jev by default config you set). The `subscription` fallback runs `claude -p --model claude-haiku-4-5 --permission-mode dontAsk --tools "" --safe-mode --strict-mcp-config --no-session-persistence` here (safe mode skips CLAUDE.md, skills, plugins, hooks, MCP and memory to keep it fast and unbiased).

## Hook

Same output as the Codex hook (`hookSpecificOutput.additionalContext`), fail-open, no output for non-routed prompts or `/router off`, `MER_CLASSIFIER=1` makes it a no-op. Configuration files (`.model-effort-router.json`, user config) are the same as for Codex; see `plugins/codex-model-effort-router/README.md`.

## Maintenance

The plugin bundles a copy of `model_effort_router/`. After editing core: `python3 scripts/sync_plugin.py` (it syncs BOTH plugin bundles; a unit test fails if either drifts).

## Unverified (needs a live check)

- The `claude -p --output-format json` result shape (`type`, `is_error`, `session_id`, `result`, `usage.*`): parsing fails closed on anything else.
- Whether `--resume <id>` keeps the session id (mer follows the id the result reports), lets `--model`/`--effort` change, and keeps `--permission-mode auto`.
- `--permission-mode auto` actually running the Test Gate commands without prompts in `-p` mode, and `dontAsk` + `--allowedTools Read,Grep,Glob` giving a usable read-only review.
- `--disallowedTools Agent` removing subagents (the tool's name may differ), and `--` ending the variadic tool options before the prompt.
- `--tools ""` giving the classifier no tools, and `--no-session-persistence` with `-p`.
- Claude Code plugin manifest/marketplace field names, `${CLAUDE_PLUGIN_ROOT}` in hook commands, hook timeout units, and UserPromptSubmit `additionalContext` being surfaced.
- Classifier latency and tokens: whether `--safe-mode` really keeps the Haiku call within the hook's 12 s clamp and small (Jev needs about 600 tokens; claude -p carries a system prompt), and that auth still works in safe mode.
- Whether `--tools` accepts the comma form, `--setting-sources user` loads what a review needs (auth, model), and `--strict-mcp-config` without `--mcp-config` means no MCP servers.
- Whether `usage` in the `-p` JSON includes Agent-tool (subagent) tokens, and whether usage on `--resume` is per invocation (assumed) or cumulative. mer records `total_cost_usd` and `modelUsage` from the result, when present, as `host_reported` on each call record as a cross-check; absence is not an error.
- A model that rejects `--effort` values, and the `error` result shape (an error result raises and its usage is not logged).
