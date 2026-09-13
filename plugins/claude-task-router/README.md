# claude-task-router

Four native Claude Code subagents — `research` (haiku), `coding` (sonnet),
`review` (opus), `complex` (fable, falls back to opus) — replacing the old
`model-effort-router` bundle's subprocess launcher for Claude.

No per-agent reasoning-effort field exists in Claude Code subagent frontmatter
(only `name`/`description`/`tools`/`model`) — effort/extended-thinking is a
session-wide setting, not something a subagent definition can override. Model
tier is the only differentiation axis available here.

## Install

Recommended — direct copy, same mechanism the 117 already-installed ECC
agents under `~/.claude/agents/ecc/` use (no manifest required at that level):

```bash
mkdir -p ~/.claude/agents/task-router
cp plugins/claude-task-router/agents/*.md ~/.claude/agents/task-router/
```

Claude Code auto-discovers `~/.claude/agents/**/*.md`; no restart of this
plugin's manifest/marketplace flow is required for that path.

This directory also carries a `.claude-plugin/plugin.json` manifest so
`claude plugin validate plugins/claude-task-router` passes and so it can be
loaded ad hoc for one call without installing, via `--plugin-dir`:

```bash
claude -p --plugin-dir plugins/claude-task-router --agent coding "재고 API에 페이지네이션 추가"
```

`--agent <name>` is a real flag (confirmed against `claude --help`) and,
combined with `--plugin-dir`, actually exercises agent selection — this is
what `scripts/eval_task_router.py` uses to verify the intended model is what
gets billed, not just a raw `--model` call.
