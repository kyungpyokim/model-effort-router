# claude-task-router

Four native Claude Code subagents — `research` (haiku, low), `coding` (sonnet,
medium), `review` (opus, high), `complex` (fable, xhigh) — replacing the old
`model-effort-router` bundle's subprocess launcher for Claude.

Claude Code supports an `effort` field in subagent frontmatter. It applies while
that agent is active, subject to an environment override or configured effort cap.
The frontmatter-effort guarantee for Fable and affected Opus models requires
Claude Code 2.1.267+; on older versions, a saved effort hold can override the
agent's configured effort.

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
claude -p --plugin-dir plugins/claude-task-router --agent task-router:coding "재고 API에 페이지네이션 추가"
```

Plugin agents are named `task-router:<agent>` (for example,
`task-router:coding`). `--agent` with `--plugin-dir` selects that concrete
plugin agent. `scripts/eval_task_router.py` verifies only the selected model
and successful CLI result; its displayed effort is static configuration from
agent frontmatter, validated by `scripts/validate_bundle.py`. It cannot verify
effective runtime effort because environment and policy settings can override it.
