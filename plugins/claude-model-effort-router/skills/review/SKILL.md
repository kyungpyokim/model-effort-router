---
name: review
description: Use when a nontrivial code change is ready for independent review or actionable findings need to be fixed.
---

# Review and Fix for Claude Code

Use after implementation is integrated. Review the actual diff and have the reviewer fix actionable findings in the same pass.

- Skip docs-only and trivial mechanical changes.
- Delegate a separate host-native Subagent with workspace write access. Use `mer route --role review --effort <effort>` to select its model; this does not change Main's model or settings. `mer run --role review` is read-only and cannot make fixes.
- Send a concise packet containing goal, decisions, constraints, actual diff, and verification status/results. Mark checks that were not run as `not run`; omit the full conversation and private implementation reasoning.
- Ask the Subagent to inspect correctness, security, data loss, and maintainability risks; fix actionable findings within scope, run relevant verification, and report changes and unresolved issues.
- Request another review only after meaningful code changes.
