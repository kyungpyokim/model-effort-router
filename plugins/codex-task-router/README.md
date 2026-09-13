# codex-task-router

Replacement for the old `model-effort-router` bundle. No classifier subprocess,
no JSON schema, no `codex exec` shell-out chain — three native Codex agent
profiles, registered directly in `~/.codex/config.toml` the same way the other
65 ECC agents already there are registered.

## Why the old bundle didn't route right

- `scripts/install_plugins.py` installs Codex agents via
  `codex plugin marketplace add` + `codex plugin add`. Its own comment admits
  this is unreliable ("Codex local marketplace support can vary by client
  version"), which is why that bundle also ships a `bin/codex-route` subprocess
  fallback (`codex exec -m <model> -c model_reasoning_effort=<effort> ...`).
  Two independent code paths, either can silently fail to apply model/effort.
- Auditing the 65 agent TOML files already in `~/.codex/agents/` (installed
  directly into `config.toml`, bypassing the marketplace) shows 63 of them
  pinned to `gpt-5.6-terra` regardless of role — including every `*_reviewer`
  agent that should be on `gpt-5.6-sol`. Model/effort assignment silently
  defaulted to one model everywhere.

Direct `[agents.<name>]` + `config_file` registration in `config.toml` is the
mechanism actually proven to work (`reviewer.toml` → `sol`, `explorer.toml` →
`terra`, both apply correctly today). This plugin uses only that mechanism.

## Agents

| agent | model | effort | use for |
|---|---|---|---|
| `research` | `gpt-5.6-luna` | high | lookups, comparisons, reading code/docs, no file writes |
| `coding` | `gpt-5.6-terra` | medium (pass `-c model_reasoning_effort="high"` for bigger changes) | features, fixes, tests, local refactors |
| `complex` | `gpt-6-astra` | high | architecture, ambiguous/high-stakes work, escalation |

Review already has a correct native agent — `reviewer` (`gpt-5.6-sol` / high,
in `~/.codex/agents/reviewer.toml`) — so this plugin does not duplicate it.

## Install

```bash
cp plugins/codex-task-router/agents/*.toml ~/.codex/agents/
```

Then add to `~/.codex/config.toml` under the existing `[agents]` table:

```toml
[agents.research]
config_file = "agents/research.toml"
description = "Research and investigation only: lookups, comparisons, reading code/docs. No file writes."

[agents.coding]
config_file = "agents/coding.toml"
description = "Implementation: features, fixes, tests, local refactors."

[agents.complex]
config_file = "agents/complex.toml"
description = "Frontier-tier: architecture, ambiguous or high-stakes work, escalation from coding/review."
```

## Use

```bash
codex --agent research "이 라이브러리 최신 버전 API 변경점 조사"
codex --agent coding "재고 API에 페이지네이션 추가"
codex --agent complex "결제 시스템 아키텍처 재설계"
```

Or let Codex's own multi-agent delegation (`features.multi_agent = true`,
already on) pick the agent by matching the task against each `description`.
