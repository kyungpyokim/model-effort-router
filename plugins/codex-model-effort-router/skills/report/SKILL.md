---
name: report
description: Use when the user wants to see which model and effort each request was routed to, and how many tokens it used, from the router logs.
---

# Routing Report

Run `mer report` (the plugin's `bin/mer`) and show the user its output. Options: `--session <id prefix>` limits it to one session, `--since <n>m|h|d` keeps only recent events (for example `12h`), `--limit <n>` sets how many recent rows to list (default 20).

- Rows come from the session logs in `~/.local/state/model-effort-router` (`MER_STATE_DIR` overrides): `route` (routed model, effort, role, classifier, advice action), historical `run` events, and `subagent` lifecycle events.
- New MER versions only route model/effort settings. Old `run` rows may remain in logs and are still reported for compatibility; their tokens are not current session usage.
- `subagent` rows are host telemetry only; MER does not launch, review, fix, or verify work.
- The summary covers every matching session: routed `(model, effort)` pairs, advice actions, Subagent route matches where available, and classifier health (errors, fallbacks, latency average and p95, failure causes).
- Prompts and Subagent output are never in the logs. If the report is empty, no request has been routed yet.
