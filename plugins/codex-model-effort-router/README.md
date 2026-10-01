# Model-Effort Router (Codex plugin, Phase 3)

Routes development requests through Plan, Implement, Test Gate and Review. The main agent runs each
stage as a subagent with the model and reasoning effort the Router chose; hooks inject the protocol
and deny spawns that deviate from it.

## Install (run these yourself; nothing here has been installed or run live)

The manifest must declare `skills` and `hooks` (fixed after a live install where `/hooks` showed nothing). Hook commands use `${CLAUDE_PLUGIN_ROOT}` because that variable is verified working in Codex 0.159.2.

```bash
# from the repo root (python3 scripts/sync_plugin.py first if you changed model_effort_router/)
codex plugin marketplace add .
codex plugin add model-effort-router@model-effort-router-local
```

Then start a Codex session and open `/hooks`: review and trust both hooks (UserPromptSubmit, PreToolUse).
**Untrusted hooks are skipped silently**, so until you trust them the Router is simply off.

## Configuration (JSON; YAML is deferred)

- Repo: `.model-effort-router.json` in the working directory. User: `$MER_USER_CONFIG`, else
  `${XDG_CONFIG_HOME:-~/.config}/model-effort-router/config.json`. Repo beats user.
- Same schema as Router Core: `{"router": {"mode": "auto|manual|off"}, "difficulty": {"backend": "subscription", "fallback": "none", "timeout_s": 10}}`.
- Jev backend (external difficulty classifier): `{"difficulty": {"backend": "jev", "fallback": "subscription"}}` in `.model-effort-router.json`, with `TYPESAFE_API_KEY` set in the environment Codex runs with. `MER_JEV_MODEL` optionally pins a model (default `jev-latest`). **The task text and paths are sent to the TypeSafe API** and billed there, separately from the subscription. Without the key the backend fails and the fallback applies.
- Test Gate commands: `{"gate": {"checks": {"test": "python3 -m unittest", "lint": "...", "typecheck": "...", "build": "..."}}}`.
  Otherwise discovered from AGENTS.md/CLAUDE.md, CI files, then package.json / pyproject.toml / Makefile.
  Checks not found are reported `not_run`, never passed.
- Per-request override: first line `/router off`, `/router implement=frontier:high`, ...
- State and log: `$MER_STATE_DIR`, else `${XDG_STATE_HOME:-~/.local/state}/model-effort-router/`
  (`<session>.plan.json`, `<session>.log.jsonl`; the log holds a prompt hash and length only).

## Gate CLI

`mer-gate` runs repo-defined commands (config, AGENTS.md/CLAUDE.md fenced blocks, CI, manifests). The main agent invokes it through its own shell tool, so sandboxing and approval apply; hooks never run it. Mark the last Review `--mark review done` so a finished plan can be dropped.

`python3 <plugin>/bin/mer-gate [--session ID] [--cwd DIR] [--timeout S]` prints JSON per check.
`--session ID --mark <stage> <done|failed|cancelled>` records a stage outcome so it can be retried (an implement retry still uses a fix round).

## mer CLI (request-level routing, Phase 7)

`python3 <plugin>/bin/mer run [--cwd DIR] [--dry-run [--level L1..L5 | --classify]] [--max-escalations N] [--json] "<request>"` classifies the request, runs it as ONE Codex session (`codex exec -m <model> -c model_reasoning_effort=<effort>`), runs the Test Gate, and on a failed gate resumes the same session (`codex exec resume`) at the next ladder profile (up to 2 steps). L4/L5 and risk-flagged work then get one independent read-only review of the git diff (`VERDICT: approved|changes_requested`); `changes_requested` does not escalate or re-review: the run ends with status `changes_requested` (exit 1) and the findings are printed/returned. Exit 0 only if the gate did not fail and a required review returned `approved` (no parseable verdict = `review_unknown`, no git repo = `review_skipped`, both exit 1).

- Your explicit `mer` call always routes; "plan only" requests run one read-only planning session, "review only" reviews the current diff. A directory that is not a git repo skips the review (mer never runs `git init`).
- `/router session=frontier:high` on the first line sets the session profile; risk-flagged work still gets plan-first and the independent review at its floor; `/router off` runs nothing.
- `--dry-run` prints the decision, profiles, ladder and exact first command and starts no session. It never calls a model-calling classifier: pass `--level L1..L5` to fix the level, or `--classify` to allow one classifier call. Escalation resumes keep `sandbox_mode="workspace-write"`. Run mer on a clean work tree: the review diffs against HEAD, so earlier uncommitted changes are reviewed too. Events (`route`, `session_start`, `gate`, `escalate`, `review`, `done`) go to the route log with hashes, token deltas and thread ids, never prompt text.
- Codex sessions started by mer run with `MER_CLASSIFIER=1`, so this plugin's hooks no-op inside them.

## Maintenance

The plugin bundles a copy of `model_effort_router/`. After editing core: `python3 scripts/sync_plugin.py`
(a unit test fails if the copy or `skills/.../SKILL.md` drifts).

## Known limitations

- Fail-open: any hook error, hook timeout, or untrusted hook means no routing and no enforcement. Errors go to the log as `error` events.
- Plugin updates change the hook hash; re-review and re-trust in `/hooks` after every update or the Router goes silent.
- A previous plan stays in force until the next routed prompt replaces it, all its stages are done, it is 2 h old, or 3 consecutive prompts did not route.
- `difficulty.timeout_s` above 12 is clamped to 12 (logged as `timeout_clamped`) so backend + fallback fit the 30 s hook timeout.
- A `running` stage older than 30 min is treated as dead; respawning implement always counts as a fix round.
- Stage `done` is inferred (the next stage starts, or the gate runs); SubagentStop carries no task name. A crashed or cancelled stage must be marked with `--mark` before retrying.
- Enforcement is deny-and-retry (documented). `updatedInput` rewriting is not used.
- Hook processes do not lock the state file; Codex runs hooks for one session sequentially as far as observed.
- Classification costs one nested `codex exec` (about 4-6 s, about 30k input tokens per the phase-0 spike).

## Unverified (needs a live check)

- Codex reads `.codex-plugin/plugin.json`. A root `plugin.json` with the Agent Plugins `$schema` made Codex ignore hooks/skills (observed in logs), so it was removed.
- `.agents/plugins/marketplace.json` field names (`source.source`, `source.path`) and the `codex plugin add <plugin>@<marketplace>` syntax.
- PreToolUse matcher `.*spawn_agent` (observed tool name `collaborationspawn_agent`; the documented `Agent` matcher was not tried).
- Plugin-delivered UserPromptSubmit actually firing, and the `MER_CLASSIFIER` guard stopping recursion from the nested classifier.
- Whether the main model follows the injected protocol, and denial reasons being acted on.
