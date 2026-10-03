# Model-Effort Router (Claude Code plugin)

Same two parts as the Codex plugin, on the Claude Code host. The **`mer` CLI is the main path**: it classifies a request, runs it as one `claude -p` session with the model and effort the Router chose, gates it, escalates the same session (`--resume`) on a failed gate, and adds an independent read-only review for high-risk work. The **UserPromptSubmit hook is advisory only**: it adds a short note (difficulty, risk flags, recommended model/effort, plan-first and review advice) and never blocks, denies or enforces anything. When the session Claude Code starts with (`model` and `effortLevel` in your user, project or local settings) already is the recommended one, the model/effort line is left out, and the note is skipped entirely if there is no plan-first or review advice either (a `/model` switch made inside the running session is not visible to the hook).

Status: unit-tested, and the session mechanics were checked live on Claude Code 2.1.285 (2026-10-03, see "Verified live"). Not yet installed as a plugin; no pilot measurement yet.

## Install (run these yourself)

```bash
# from the repo root (python3 scripts/sync_plugin.py first if you changed model_effort_router/)
claude plugin marketplace add ./
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
- Fixed context: mer's `claude -p` sessions are lean by default (`{"session": {"claude_context": "lean"}}`). Lean implement/resume sessions load all settings and instructions (CLAUDE.md chain, `~/.claude/rules`, your permissions and hooks) but turn your enabled plugins off (`--settings '{"enabledPlugins": {"<id>": false, ...}}'` for every plugin enabled in the user settings or the workdir's `.claude/settings(.local).json`; no flag if none) and MCP servers off (`--strict-mcp-config`). Lean read-only sessions (review, plan) load only user settings with all hooks disabled (`--setting-sources user --settings '{"disableAllHooks": true}'`; your user deny rules still apply) and never project or local settings in either mode, so a reviewed change cannot run its own hooks. Turning plugins off also drops guard hooks that plugins provide (PreToolUse validators and the like) in lean implement sessions; your own settings hooks and deny rules still apply. `"full"` keeps everything (the old unrestricted argv; read-only: `--setting-sources user`). It is a per-repo or user config key like `subagent_policy`; the Codex host ignores it.
- `mer chat '<request>'` classifies, then replaces itself with interactive `claude --model M [--effort E] -- <request>` (mer changes into `--cwd` first; Claude Code has no cwd flag). Plan/review-only requests start in `--permission-mode plan`.
- `--dry-run` prints the decision, ladder and the exact first `claude` command and starts no session.
- Usage is per `claude -p` invocation (input = input + cache creation + cache read tokens); it is logged per call with thread ids (`session_id`), never prompt text.
- Sessions started by mer run with `MER_CLASSIFIER=1`, so this plugin's hook stays quiet inside them.
- The difficulty backend is host-independent (Jev by default config you set). The `subscription` fallback runs `claude -p --model claude-haiku-4-5 --permission-mode dontAsk --tools "" --safe-mode --strict-mcp-config --no-session-persistence` here (safe mode skips CLAUDE.md, skills, plugins, hooks, MCP and memory to keep it fast and unbiased).

## Hook

Same output as the Codex hook (`hookSpecificOutput.additionalContext`), fail-open, no output for non-routed prompts or `/router off`, `MER_CLASSIFIER=1` makes it a no-op. Configuration files (`.model-effort-router.json`, user config) are the same as for Codex; see `plugins/codex-model-effort-router/README.md`.

## Maintenance

The plugin bundles a copy of `model_effort_router/`. After editing core: `python3 scripts/sync_plugin.py` (it syncs BOTH plugin bundles; a unit test fails if either drifts).

## Verified live (Claude Code 2.1.285, 2026-10-03, `evaluation/probes/claude_live_probe.sh`)

- Claude Code 2.1.280 does not know `claude-sonnet-5-5` (`[claude-code:unrecognized_model]`); 2.1.285 does. Keep Claude Code current.
- The `-p --output-format json` result has `type`, `is_error`, `session_id`, `result`, `usage` (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`), `total_cost_usd`, `modelUsage` and `subagent_stats`. An expired login is `is_error: true` with subtype `success` and the reason in `result`.
- `usage` is per invocation; `total_cost_usd` and `modelUsage` are cumulative for the session (a resume shows earlier models too). Claude Code also makes a small Haiku call once per new session (~900 input tokens) that appears only in `modelUsage`/`total_cost_usd`, not in `usage`.
- `--resume <id>` keeps the session id and switches `--model`/`--effort` (Sonnet 5.5 -> Opus 5.5 confirmed).
- `--permission-mode auto` runs a shell command without a prompt. `--disallowedTools Agent` removes the subagent tool (it is not in the session's tool list; `subagent_stats.spawned` 0).
- The read-only review argv cannot edit: asked to change a file, the session reported only Read/Glob/Grep and the file stayed unchanged.
- The isolated classifier call (`--safe-mode --tools ""`) works and authenticates: about 3.2 s and 3.7k input tokens on Haiku.
- `mer run --host claude` on the pilot L1 task: ok, one Sonnet 5.5/medium session, correct diff plus a test; 167k tokens (mostly cache creation: the user-level Claude Code setup is loaded into implement sessions).

## Verified live (2026-10-03/04)

- Plugin install (marketplace `./`), the UserPromptSubmit hook and its `additionalContext` reaching the conversation.
- Review and review-fix paths (pilots c1r/c3: `changes_requested` then fixed), quality and cost against a stock Claude Code baseline (plan Phase 5).
- Lean context (probe steps 7, 8, 8b): `enabledPlugins: false` via `--settings` drops the plugins while ~/.claude/rules and CLAUDE.md still load (first-call cache write 31.6k -> 21.8k tokens); read-only sessions run no project/local hooks and `disableAllHooks` also stops a hook given in `--settings`.

## Unverified (needs a live check)

- The escalation path (a failed gate resuming the session at the next profile): no pilot run escalated.
- Whether `usage`/`modelUsage` count Agent-tool (subagent) tokens at L5: no pilot run used the Agent tool.
- Hook timeout units and whether a changed hook config needs re-trusting after an update.

## Nimble classifier (optional)

- Nimble backend (local, free): `ollama pull nimble` (about 9.4 GB), then `{"difficulty": {"backend": "nimble", "fallback": "subscription"}}`, or as Jev's local fallback `{"difficulty": {"backend": "jev", "fallback": "nimble"}}` (compare on corpus-v1: Nimble exact 78% / under 21 / 1 critical miss vs Jev 82% / 5 / 0). It talks to Ollama's `systemone` endpoint on localhost only (`http://127.0.0.1:11434/v1/systemone`; any loopback port is accepted, a non-loopback `url` is a config error and is refused before anything is sent). Optional `difficulty.nimble`: `{"model": "nimble", "url": "...", "risk_thresholds": {"auth": 0.6}, "l4_min_prob": 0.0, "l4_min_prob_by_flag": {}, "l4_promote_prob": 0.2}` (the defaults); env `MER_NIMBLE_MODEL`, `MER_NIMBLE_URL`; config beats env beats defaults. Pre-load the model (`ollama run nimble` once, or set `OLLAMA_KEEP_ALIVE`): a cold load can exceed the 12 s hook timeout, and that call then falls back. Risk thresholds are Jev's; Nimble under-rates L4/L5, so its defaults turn the L4 demotion off and promote to L4/L5 when P(L4)+P(L5) >= 0.2 (`l4_promote_prob`, tuned on corpus-v1 itself: overfit risk). Re-check with a compare run (`python3 -m evaluation.compare --backends nimble --live`).
