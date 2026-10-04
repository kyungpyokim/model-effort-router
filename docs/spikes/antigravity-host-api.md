# Antigravity CLI host verification

Verified on 2026-10-04 with `agy` 1.2.16. Scope is the CLI; IDE behavior is not verified.

## Evidence

- `agy --help` exposes `--prompt-interactive`, `--model`, `--effort`, `--conversation`, `--mode plan`, and `--output-format json`. There is no documented tools-off, MCP-off, plugins-off, or subagent-zero option equivalent to the isolated existing classifiers.
- `agy models` lists `gemini-3.8-flash-{medium,high}`, `claude-sonnet-5-5-{medium,high}`, and `claude-opus-5-5-{medium,high}`. The adapter chooses these tiers; abstract xhigh applies high and preserves xhigh in the resolved profile.
- A temporary empty directory probe ran `agy -p 'Reply exactly MER_PROBE_OK. Do not use any tools or modify files.' --model gemini-3.8-flash-medium --effort medium --mode plan --output-format json --print-timeout 35s`. Exit 0; response `MER_PROBE_OK`; SUCCESS envelope with conversation_id, duration_seconds, num_turns, and usage counters. No global configuration or plugin installation was performed. The JSON result does not report the resolved model, so service-side model identity is unverified.
- Sanitized observed result: `{"conversation_id":"<opaque-id>","status":"SUCCESS","response":"MER_PROBE_OK\n","num_turns":1,"usage":{"input_tokens":21016,"output_tokens":74,"thinking_tokens":68,"cache_read_tokens":0,"total_tokens":21090}}`.
- The probe's own transcript is under `~/.gemini/antigravity-cli/brain/<id>/.system_generated/logs/transcript.jsonl`. The user entry has step_index 0, source USER_EXPLICIT, type USER_INPUT, status DONE, content, and truncated_fields. The content is a decorated `<USER_REQUEST>` plus metadata; even this short request had `truncated_fields: ["content"]`.
- In that transcript, `--mode plan` expands `/plan` instructions requesting an implementation-plan artifact and approval. This observation does **not** prove enforcement against filesystem writes, terminal, MCP, or subagents. No destructive permission probe was run.

## Release decision

Ship the minimal native bundle and interactive `mer chat`. It uses the existing router/session policy with manual profiles or configured Nimble/Jev. The default subscription classifier is explicitly rejected, including as a fallback, before any child call. A direct unsupported-host SubscriptionBackend call also fails instead of falling through to Codex. Offline `chat --dry-run --level Lx` is supported.

`mer run`, resume/escalation, automated review, and plan/review-only chat stay unsupported. There is no claim of read-only enforcement. Raw parser usage is preserved without assuming cumulative/delta or billing semantics. Actual resume/profile changes were not probed because automated execution remains disabled.

Do not enable a PreInvocation hook yet: the initial hook transcript timing and reliable complete raw user-turn extraction have not been verified. Observed decorated/truncated content is insufficient to define that trust boundary. A future hook requires bounded regular-file access, reliable turn identity, atomic deduplication, multi-workspace handling, and fail-open behavior from the plan. No placeholder hook is shipped.

Validation of the native manifest and skill uses `agy plugin validate plugins/antigravity-model-effort-router`; results are recorded below after implementation. Global installation remains a documented user action. Fixture tests exercise the bundled entrypoint against a fake `agy` executable and record argv, cwd, and recursion guard.

## References

- [Plugin format and installation](https://antigravity.google/docs/plugins/)
- [Headless output and permissions](https://antigravity.google/docs/cli/headless/)
- [Hook lifecycle and transcript input](https://antigravity.google/docs/hooks/)

## Validation results

Passed: `agy plugin validate`; full unittest discovery (641 tests); `scripts/sync_plugin.py --check`; `git diff --check`. Adapter/parser branch coverage in a temporary venv: 100%.
