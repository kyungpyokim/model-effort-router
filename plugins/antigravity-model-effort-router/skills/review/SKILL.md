---
name: review
description: Use when a nontrivial code change needs independent review and actionable fixes.
---

# Review and Fix for Antigravity

Use a separate, write-capable native Antigravity Subagent for this review workflow. Do not use `mer run` on this host.

When a supported reviewer is available:

- Skip docs-only and trivial mechanical changes.
- Send a concise packet containing goal, decisions, constraints, actual diff, and verification status/results. Mark checks that were not run as `not run`; omit the full conversation and private implementation reasoning.
- Ask the Subagent to inspect correctness, security, data loss, and maintainability risks; fix actionable findings within scope, run relevant verification, and report changes and unresolved issues. Treat the configured hook model/effort as a preference; do not claim the host applied it unless confirmed.
- Request another review only after meaningful code changes.
