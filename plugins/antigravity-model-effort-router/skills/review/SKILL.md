---
name: review
description: Use when a nontrivial code change needs independent review and actionable fixes.
---

# Review and Fix for Antigravity

This workflow requires a host-supported, write-capable Subagent. Antigravity execution isolation is currently unverified, so do not use `mer run` or claim an independent review-and-fix pass unless the host provides a verified execution path.

When a supported reviewer is available:

- Skip docs-only and trivial mechanical changes.
- Send a concise packet containing goal, decisions, constraints, actual diff, and verification status/results. Mark checks that were not run as `not run`; omit the full conversation and private implementation reasoning.
- Ask the Subagent to inspect correctness, security, data loss, and maintainability risks; fix actionable findings within scope, run relevant verification, and report changes and unresolved issues.
- Request another review only after meaningful code changes.
