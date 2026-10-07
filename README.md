# Model Effort Router

한국어 문서는 [README.ko.md](README.ko.md)를 참고하세요.

MER classifies a development request as a **role + effort**, maps that pair to a host model, and can run an external worker request. Main remains responsible for conversation context, deciding which steps are needed, and invoking host-native Subagents. MER does not change the current Codex turn. Worker runs can opt into verification-driven effort promotion.

## Installation

The host plugin does not include the shared runtime. Clone this repository and install the runtime first:

```sh
git clone https://github.com/kyungpyokim/model-effort-router.git
cd model-effort-router
python3 scripts/install_core.py
python3 scripts/install_core.py --check
```

Then install the plugin for your host from the repository root:

**Codex CLI** — add this repository's Codex marketplace and install its plugin:

```sh
codex plugin marketplace add https://github.com/kyungpyokim/model-effort-router --sparse .agents/plugins --sparse plugins/codex-model-effort-router
codex plugin add model-effort-router@model-effort-router
```

**Claude Code** — add this repository's Claude marketplace, install the plugin, then start a new session:

```sh
claude plugin marketplace add kyungpyokim/model-effort-router
claude plugin install model-effort-router@model-effort-router
```

**Antigravity CLI** — install the local plugin directory:

```sh
agy plugin install ./plugins/antigravity-model-effort-router
```

**OpenCode** — install the pinned local plugin dependency, then add the plugin path to the project's `opencode.json`:

```sh
cd plugins/opencode-model-effort-router
bun install --frozen-lockfile
```

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["./plugins/opencode-model-effort-router"]
}
```

All host integrations can provide a primary model recommendation and configured alternatives. Codex, Claude, and Antigravity include them in hook advice; OpenCode returns them in `model_options`. These options do not switch a host's active model or trigger retries. See each plugin README for host-specific limits.

Antigravity and OpenCode provide route advice only; worker execution is unsupported. Marketplace plugin installs do not install or update the shared runtime; rerun `python3 scripts/install_core.py` from this checkout when updating it. See the [Codex plugin guide](https://developers.openai.com/plugins/build/plugins), [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces), and [Antigravity plugin guide](https://antigravity.google/docs/plugins/) for host-specific details.

## Routing contract

The classifier returns `role` and `effort`; `confidence` and `reason_code` are optional. Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. The first four use the execution model; the rest use the reasoning model. Effort is `low`, `medium`, `high`, `xhigh`, or `max`. Independent risk detection can raise a safety-sensitive review/design request to at least `high`, but never changes its role or model lane.

Defaults are Codex execution `gpt-6-luna` and reasoning `gpt-6.1-sol`; Claude execution `claude-sonnet-5-5` and reasoning `claude-opus-5-5`; Antigravity delegated profile `gemini-3.8-flash`; OpenCode advice execution `opencode/mimo-v2.6-flash-free`, reasoning `opencode/nemotron-3-ultra-free` with reasoning alternatives `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, and `opencode-go/grok-4.7`. Each host/lane accepts `primary`, optional `alternatives`, `fallback`, and supported efforts. `primary` is recommended; alternatives are listed as user-selectable choices. For example:

```json
{
  "models": {
    "codex": {
      "execution": {
        "primary": "gpt-6-luna",
        "alternatives": ["gpt-6-astra", "provider/model-id"]
      },
      "reasoning": {
        "primary": "gpt-6.1-sol",
        "alternatives": ["gpt-6-astra", "provider/another-model"]
      }
    }
  }
}
```

Replace the example IDs with models available to the host. OpenCode returns `model_options`; the other hooks include configured alternatives in their advice. Alternatives never trigger execution retries. MER never infers execution fallback from stderr or retries after a worker may have started; only an explicit pre-execution-unavailable signal permits it. Classifier providers may fall through to the configured next classifier. If all fail, CLI routing returns an error; hooks fail open and leave the user request unblocked.

## Classifier backend setup

The classifier backend decides the request's role and effort. It is separate from `models.<host>`, which selects the worker model. The built-in classifier default is `subscription` with no fallback. To use hosted Jev as the primary role/effort classifier, configure `difficulty.backend` as `jev`:

```json
{
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10}
}
```

With `backend: jev`, every prompt that is not host-generated is sent to the Jev API, which decides eligibility (`route` or `no_route`), role and effort. The keyword rules only gate the fallback backend when Jev fails.

**Session context (Claude and Codex hooks).** So that short follow-ups such as "go ahead" are classified by the work they continue, the hook also sends Jev a session summary and the most recent user/assistant turns (text only, never tool output) next to the current prompt. The summary is produced in the background by the host's own CLI (`claude -p` on Haiku, text on stdin; Codex sessions send only the raw recent turns, because `codex exec` cannot yet be run without a shell) and stored under the state directory (summary files unused for 14 days are deleted); it lags one turn, and the newest turns are sent raw. The hook never waits for it. Disable it with `{"context": {"enabled": false}}` in repository or user config; `context.max_chars` (default 6000) bounds the summary plus recent turns. With `context.enabled: false`, only the current prompt is sent. The background summary needs the standalone `claude` CLI to be signed in (`claude auth login`); a session inside the Claude desktop app does not lend its sign-in to it, and without it the summary is skipped and an error event is logged.

Jev uses the TypeSafe `jev-latest` model by default. Store its API key in `~/.config/model-effort-router/config.json`, never in repository config:

```json
{
  "jev": {"api_key": "your-typesafe-api-key"}
}
```

The configured primary backend runs first; the fallback runs only if it fails.

OpenAI Decisions API is also available as the opt-in `openai_decisions` backend (model `gpt-6-luna`):

```json
{"difficulty": {"backend": "openai_decisions", "fallback": "subscription", "timeout_s": 10}}
```

Set `OPENAI_API_KEY`, or store the key only in global `~/.config/model-effort-router/config.json`:

```json
{"openai": {"api_key": "your-openai-api-key"}}
```

For local classification with Nimble, install Ollama and ensure its local server is running, then pull the model:

```sh
ollama pull nimble
```

Nimble defaults to model `nimble` at `http://127.0.0.1:11434/v1/systemone` and needs no API key. Select it with `difficulty.backend: "nimble"`; for example:

```json
{
  "difficulty": {
    "backend": "nimble",
    "fallback": "jev",
    "timeout_s": 10,
    "nimble": {
      "model": "nimble",
      "url": "http://127.0.0.1:11434/v1/systemone"
    }
  }
}
```

Add the `difficulty` object to `.model-effort-router.json` in the repository root or to `~/.config/model-effort-router/config.json`. `difficulty.nimble.model` and `.url` override the defaults. Nimble URLs must use HTTP(S) and point to `localhost`, `127.0.0.1`, or `::1`; MER rejects non-loopback URLs, so Nimble requests stay on the machine. In the example above, a Nimble failure sends the task to hosted Jev through TypeSafe; configure Jev's API key if you want that fallback.

### Classifier performance

On the 150-case v3 synthetic corpus, the recorded role/effort match rates were:

| Backend | Role | Effort | Role + effort |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 141/150 (94.0%) | 119/150 (79.3%) | 111/150 (74.0%) |
| Nimble | 124/150 (82.7%) | 101/150 (67.3%) | 85/150 (56.7%) |
| OpenAI Decisions API (`gpt-6-luna`) | 136/150 (90.7%) | 119/150 (79.3%) | 107/150 (71.3%) |

The Decisions API is the endpoint; `gpt-6-luna` is its model. Jev had the highest recorded match rates on this corpus. All three results use the same previously evaluated cases, so treat them as agreement with the adjudicated labels, not a fresh independent measure of real-world accuracy. Nimble provides local inference; set its fallback to `none` if requests must stay on-device. See the [evaluation index](docs/evaluation/README.md) and [Decisions API run details](docs/evaluation/openai-decisions-20261007.md).

## Use

```sh
python3 <plugin>/bin/mer route --host codex --json 'Review the authentication changes'
python3 <plugin>/bin/mer route --host codex --role implementation --effort high --json 'Implement the approved design'
python3 <plugin>/bin/mer run --host codex --role test --effort medium 'Run and fix the focused tests'
```

`mer route` classifies/maps only. By default, `mer run` executes exactly one worker request. Reasoning roles run read-only. Antigravity can classify and provide advice, but worker execution is unsupported because Subagent isolation is unverified. OpenCode exposes route advice through the `mer` tool; it does not switch the active model or run workers. `mer chat` was removed; use the route result to ask Main to invoke the selected Subagent. Explicit `--role` and `--effort` bypass automatic hook eligibility and must be provided together.

After a run, MER compares the repository's changed paths before and after the worker. When changes are detected, text output reports the `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`), plus changed-file and top-level-directory counts. JSON includes the same values under `change`, with the resulting `risk_flags`. Blast radius is a path-based estimate; review the actual changes to assess impact.

### Low-first worker runs

```sh
python3 <plugin>/bin/mer run --host codex --role fix --effort low --low-first \
  --verify 'python3 -m unittest discover -s tests' --json 'Fix the approved bug'
```

For execution roles, `--low-first` starts at low and promotes through medium and high after verification failures. It stops for approval before xhigh and again before max. Pass `--approve-xhigh` or `--approve-max` only when the user has explicitly approved that effort for the run. The configured model must support all five efforts. Each attempt starts a fresh session in the same workspace, keeping edits and receiving the original context plus the previous failure. Worker errors, cancellation, verification start failures, signal termination, and timeouts stop the loop. `--timeout` limits each worker attempt; `--verify-timeout` limits each check (default 300 seconds).

An approval stop returns `continuation_context` with the original request and last failure. After xhigh approval, pass that context in the same workspace with `--low-first --role <same-role> --effort xhigh --approve-xhigh --verify <same-command>` to run the xhigh continuation. If xhigh fails, approve max separately and continue with `--effort max --approve-max`. Each continuation is a separate run; combine their records when measuring the full task. Without an explicit xhigh or max effort, a new invocation starts at low. One-shot xhigh and max runs require their matching approval flag.

`--verify` is an explicit argv command executed without shell expansion, using the parent process's privileges and environment. Freeze meaningful completion checks before work starts: fixing argv does not make worker-editable tests tamper-proof. The last 2,000 characters of check output are sent to the next worker and returned in JSON; keep secrets out of that output. Persistent route logs store only attempt metadata, token counts, and check status/duration.

JSON and route logs record `first_pass`, `escalation_count`, and each attempt's effort, worker usage, and verification duration. `usage` sums reported worker tokens; `usage_missing` counts attempts with absent/incomplete usage. Classifier usage is separate. Deterministic checks add execution time but no router model call; any external model calls inside the check are unmeasured, so the token figures are not a complete validation cost.

For exploratory comparison, `--retry-low` adds one low retry with the same failure feedback before medium. Compare it with normal low-first on separate, equally initialized workspaces and report the full chain and usage; do not run both arms on the already-modified workspace.

Hooks provide Context Packet fields and instructions, not a completed packet from Main's conversation. Main should use the current request and relevant conversation to populate a compact packet (`task`, `context`, `decisions`, `constraints`, `relevant_files`, `expected_result`) and include it directly in the host-native Subagent invocation. For review, pass only `goal`, `decisions`, `constraints`, the actual diff, and verification status/results; mark checks that were not run as not run. Do not forward private reasoning or the full conversation by default. Hooks do not inspect Main's conversation or create native Subagents. `mer run` is a separate one-worker path and cannot read Main's conversation, so include needed context in its explicit task input.

## Configuration

Configuration uses JSON in `.model-effort-router.json` at the repository root or `~/.config/model-effort-router/config.json`; repository values override user values. Existing user files are not rewritten. Example:

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10},
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "alternatives": ["gpt-6-astra"], "fallback": "gpt-6.1-sol", "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "gpt-6.1-sol", "alternatives": ["gpt-6-astra"], "fallback": "gpt-6-luna", "efforts": ["low", "medium", "high", "xhigh", "max"]}
    },
    "claude": {
      "execution": {"primary": "claude-sonnet-5-5", "alternatives": ["claude-fable-5-1"], "fallback": "claude-opus-5-5", "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "claude-opus-5-5", "alternatives": ["claude-fable-5-1"], "fallback": "claude-sonnet-5-5", "efforts": ["low", "medium", "high", "xhigh", "max"]}
    },
    "antigravity": {
      "execution": {"primary": "gemini-3.8-flash", "alternatives": ["claude-opus-5-5"], "fallback": null, "efforts": ["medium", "high"]},
      "reasoning": {"primary": "claude-opus-5-5", "fallback": null, "efforts": ["medium", "high"]}
    },
    "opencode": {
      "execution": {"primary": "opencode/mimo-v2.6-flash-free", "fallback": null, "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "opencode/nemotron-3-ultra-free", "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"], "fallback": null, "efforts": ["low", "medium", "high", "xhigh", "max"]}
    }
  }
}
```

Legacy L1-L5, tier/profile, session, escalation, and `nimble_jev` settings are rejected with migration guidance. Replace tier overrides with `/router role=<role> effort=<effort>`; replace an old Main-session routing workflow with `mer route` plus a Main-selected Subagent. `nimble_jev` is removed; configure `nimble` and a separate classifier fallback such as `jev`.

Jev credentials belong only in the global user config; see [Classifier backend setup](#classifier-backend-setup). Repository config cannot provide this credential.

## Runtime development

`model_effort_router/` is the shared runtime source. Plugins contain host integration only. Use `MER_CORE_PATH="$PWD"` for development. Install and verify with:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests
```
