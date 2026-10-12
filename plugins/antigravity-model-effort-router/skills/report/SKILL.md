---
name: report
description: Use when the user wants to see which model and effort each request was routed to, and how many tokens it used, from the router logs.
---

# Routing Report

Run `mer report` (the plugin's `bin/mer`) and show the user its output. Options: `--session <id prefix>` limits it to one session, `--since <n>m|h|d` keeps only recent events (for example `12h`), `--limit <n>` sets how many recent rows to list (default 20).

- Rows come from the session logs in `~/.local/state/model-effort-router` (`MER_STATE_DIR` overrides): `route` (routed model, effort, role, classifier, advice action), `run` (`mer run` worker), and `subagent` (actual Subagent started, `matched` against the route).
- Tokens (`input`, `cached`, `output`) exist only for `route` (the classifier call) and `run` (the worker). The main conversation and Subagent turns are not logged, so their tokens are not shown.
- The summary covers every matching session, not just the listed rows: routed `(model, effort)` pairs, advice actions (`spawn`, `inline_same_model`, `advise`, `no_route`), how many Subagents `matched` the route (`unverified` when nothing was comparable), classifier health (errors, fallbacks, latency average and p95, failure causes), and classifier and worker token totals.
- Prompts and Subagent output are never in the logs. If the report is empty, no request has been routed yet.
