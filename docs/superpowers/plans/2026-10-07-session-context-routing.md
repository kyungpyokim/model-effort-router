# Session context routing plan (2026-10-07)

## Problem

The hook classifier (Jev) sees only the current prompt. Follow-ups such as "진행", "응 만들어줘" or "둘 다 반영" often start the real work of a plan proposed earlier in the session. Without context, Jev returns `no_route` or a role/effort with no basis, so the most important turns get no advice. Accuracy is the priority.

## Decisions (user, 2026-10-07)

- Pass a summary of the whole session to Jev, not only the last message.
- The summary is produced by the host's subscription CLI (Claude: `claude -p` on Haiku, Codex: `codex exec` on the economy model with shell and exec tools disabled; canary-file read attempts failed on Codex 0.160.1, which is behavioral evidence for that version only, so other versions fall back to no Codex summary and no classifier context), reusing the isolated runner in `difficulty/subscription.py`. No extra API key; session text does not leave the host provider except the summary and recent turns sent to Jev.
- Scope: all hosts, phased. Claude and Codex first; OpenCode and Antigravity need host spikes.

## Design

- **Transcript readers** (`model_effort_router/context/transcripts.py`): host-specific parsers that turn `transcript_path` into ordered `(role, text)` turns. Only user and assistant text; tool calls/results, thinking/reasoning, attachments, meta and host-generated messages (`HARNESS_MESSAGE`) are excluded.
  - Claude JSONL: `type` user/assistant, `message.content` str or blocks; keep `text` blocks; skip `isMeta`, tool_result-only user entries.
  - Codex rollout JSONL: `response_item` with `payload.type == "message"` and role user/assistant (developer excluded).
- **Rolling summary store** (`context/summary.py`): per session JSON in the state dir (`route_log.log_path` naming): `{summary, covered_turns, updated_at}`. Atomic write, lock file to prevent concurrent refresh.
- **Refresh, off the critical path**: after routing, `user_prompt_submit` spawns a detached background process (`python3 -m model_effort_router.context.refresh ...`) that folds turns not yet covered into the summary (previous summary + new turns -> new summary, bounded length). Child env sets `GUARD_ENV` so the nested CLI's hooks never route. The prompt hook never waits for it.
- **Jev input**: `Session summary` (may lag one turn) + `Recent turns` (raw last turns not yet covered, tail-truncated to a budget) + `Current request`. Instructions: classify only the current request; use context to interpret it; a follow-up that approves or continues a proposed plan routes with that plan's role/effort; acknowledgements with nothing to execute stay `no_route`.
- **Config**: `context.enabled` (default true), `context.max_chars` (budget for summary + recent turns). Missing transcript or summary -> current-prompt-only behaviour (fail open).
- **Privacy**: README states that with `backend: jev` the session summary and recent turn text are sent to the Jev API. Tool output is never included.

## Phases

1. Core + Claude + Codex: readers, summary store, background refresh, Jev context input, config, tests with recorded transcript fixtures (no live calls).
2. Evaluation: extract follow-up cases (plan -> short approval) from local transcripts into a labeled corpus; live A/B (context on/off) after explicit user approval.
3. OpenCode: plugin passes session messages (via the OpenCode session API) to `mer route` (e.g. `--context-file`); summarizer CLI isolation for OpenCode needs a spike.
4. Antigravity: spike first. The PreInvocation hook does not classify yet, and the transcript content is decorated/truncated (`docs/spikes/antigravity-host-api.md`).

Live runs (model calls, plugin installs, global config) need explicit user approval at every phase.
