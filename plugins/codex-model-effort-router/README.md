# Model-Effort Router (Codex plugin)

Two parts. The **`mer` CLI is the main path**: it classifies a request, runs it as one Codex session with the model and
reasoning effort the Router chose, gates it, escalates the same session on failure, and adds an independent review for
high-risk work (see "mer CLI"). The **UserPromptSubmit hook is advisory only**: inside a normal Codex session it adds
a short note (difficulty, risk flags, recommended model/effort, plan-first and review advice). It never blocks, denies
or enforces anything and never asks the model to spawn subagents. (The earlier subagent orchestration and its
PreToolUse enforcement were removed in Phase 7.)

## Install (run these yourself; nothing here has been installed or run live)

The manifest must declare `skills` and `hooks` (fixed after a live install where `/hooks` showed nothing). Hook commands use `${CLAUDE_PLUGIN_ROOT}` because that variable is verified working in Codex 0.159.2.

```bash
# from the repo root (python3 scripts/sync_plugin.py first if you changed model_effort_router/)
codex plugin marketplace add .
codex plugin add model-effort-router@model-effort-router-local
```

Then start a Codex session and open `/hooks`: review and trust the hook (UserPromptSubmit).
**Untrusted hooks are skipped silently**, so until you trust it there is no advice. **After updating the plugin the hook set has changed (PreToolUse is gone): re-trust the hooks in `/hooks`.** The `mer` CLI needs no hook.

## Configuration (JSON; YAML is deferred)

- Repo: `.model-effort-router.json` in the working directory. User: `$MER_USER_CONFIG`, else
  `${XDG_CONFIG_HOME:-~/.config}/model-effort-router/config.json`. Repo beats user.
- Same schema as Router Core: `{"router": {"mode": "auto|manual|off"}, "difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10}}`.
- Jev backend (external difficulty classifier): `{"difficulty": {"backend": "jev", "fallback": "subscription"}}` in `.model-effort-router.json`, with `TYPESAFE_API_KEY` set in the environment Codex runs with. `MER_JEV_MODEL` optionally pins a model (default `jev-latest`). **The task text and paths are sent to the TypeSafe API** and billed there, separately from the subscription. Without the key the backend fails and the fallback applies.
- Test Gate commands: `{"gate": {"checks": {"test": "python3 -m unittest", "lint": "...", "typecheck": "...", "build": "..."}}}`.
  Otherwise discovered from AGENTS.md/CLAUDE.md, CI files, then package.json / pyproject.toml / Makefile.
  Checks not found are reported `not_run`, never passed.
- Per-request override: first line `/router off`, `/router session=frontier:high` (session profile; never below a risk floor).
- Log: `$MER_STATE_DIR`, else `${XDG_STATE_HOME:-~/.local/state}/model-effort-router/`
  (`<session>.log.jsonl`; it holds a prompt hash and length only, never prompt text).

## Advisory hook

For a routed prompt (a code-change, plan-only or review-only request; not questions, not `/router off`) the hook classifies it with the configured backend (jev or subscription) and adds only `additionalContext`, e.g.:

```
[model-effort-router] Advisory only: nothing is enforced and no subagents are needed. ...
Difficulty: L4 (confidence 0.62). Risk flags: auth.
Recommended session: gpt-6-sol, reasoning effort high; switch with /model if you want.
Plan first: write a short plan before changing code.
This work warrants an independent review (gpt-6-sol, reasoning effort high) after the change. Run it with `python3 <plugin>/bin/mer run --review-profile frontier:high 'review only: check the current diff for <the task>'`, or run the whole task through `python3 <plugin>/bin/mer run '<the task>'` (Test Gate, escalation and review included). Single-quote the request (write ' as '\'') so the shell expands nothing in it.
```

Non-routed prompts and `/router off` get no context at all. The hook is fail-open (any error, timeout or untrusted hook = no output), logs a `route` event, and no-ops when `MER_CLASSIFIER=1` (set inside mer-driven and classifier sessions).

## Gate CLI

`python3 <plugin>/bin/mer-gate [--cwd DIR] [--timeout S]` runs repo-defined commands (config, AGENTS.md/CLAUDE.md fenced blocks, CI, manifests) and prints JSON per check. `mer` runs the same gate itself; hooks never run it.

## mer CLI (request-level routing, Phase 7)

`python3 <plugin>/bin/mer run [--cwd DIR] [--dry-run [--level L1..L5 | --classify]] [--max-escalations N] [--json] "<request>"` classifies the request, runs it as ONE Codex session (`codex exec -m <model> -c model_reasoning_effort=<effort>`), runs the Test Gate, and on a failed gate resumes the same session (`codex exec resume`) at the next ladder profile (up to 2 steps). L4/L5 work, and auth/security-flagged work at any level, then gets one independent read-only review (other risk flags only raise its profile) of the git diff (`VERDICT: approved|changes_requested`); `changes_requested` does not escalate or re-review: the run ends with status `changes_requested` (exit 1) and the findings are printed/returned. Exit 0 only if the gate did not fail and a required review returned `approved` (no parseable verdict = `review_unknown`, no git repo = `review_skipped`, both exit 1).

- Your explicit `mer` call always routes; "plan only" requests run one read-only planning session, "review only" reviews the current diff. A directory that is not a git repo skips the review (mer never runs `git init`).
- `/router session=frontier:high` on the first line sets the session profile; risk-flagged work still gets plan-first, and auth/security or L4/L5 work the review at its floor; `/router off` runs nothing.
- `--dry-run` prints the decision, profiles, ladder and exact first command and starts no session. It never calls a model-calling classifier: pass `--level L1..L5` to fix the level, or `--classify` to allow one classifier call. Escalation resumes keep `sandbox_mode="workspace-write"`. Run mer on a clean work tree: the review diffs against HEAD, so earlier uncommitted changes are reviewed too. Events (`route`, `session_start`, `gate`, `escalate`, `review`, `done`) go to the route log with hashes, token deltas and thread ids, never prompt text.
- Codex sessions started by mer run with `MER_CLASSIFIER=1`, so this plugin's hooks no-op inside them.

## Maintenance

The plugin bundles a copy of `model_effort_router/`. After editing core: `python3 scripts/sync_plugin.py`
(a unit test fails if the copy drifts; `skills/.../SKILL.md` is hand-written).

## Known limitations

- Fail-open: any hook error, hook timeout, or untrusted hook means no advice. Errors go to the log as `error` events.
- Plugin updates change the hook hash; re-review and re-trust in `/hooks` after every update or the hook goes silent.
- `difficulty.timeout_s` above 12 is clamped to 12 (logged as `timeout_clamped`) so backend + fallback fit the 30 s hook timeout.
- The advice costs one classification per routed prompt: Jev about 541 input tokens; the subscription backend one nested `codex exec` (about 4-6 s, about 27k input tokens).

## Unverified (needs a live check)

- Codex reads `.codex-plugin/plugin.json`. A root `plugin.json` with the Agent Plugins `$schema` made Codex ignore hooks/skills (observed in logs), so it was removed.
- `.agents/plugins/marketplace.json` field names (`source.source`, `source.path`) and the `codex plugin add <plugin>@<marketplace>` syntax.
- Plugin-delivered UserPromptSubmit actually firing, and the `MER_CLASSIFIER` guard stopping recursion from the nested classifier.
- Whether the main model surfaces the advice to the user.
