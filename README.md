# Model Effort Router

한국어 문서는 [README.ko.md](README.ko.md)를 참고하세요.

MER classifies a development request as a **role + effort**, maps that pair to a host model, and can run an external worker request. Main remains responsible for conversation context, deciding which steps are needed, and invoking host-native Subagents. MER does not change the current Codex turn. Worker runs can opt into verification-driven effort promotion.

## Installation

The host plugin does not include the shared runtime. Clone this repository and install the runtime first:

```sh
git clone https://github.com/kyungpyokim/model-effort-router-next.git
cd model-effort-router-next
python3 scripts/install_core.py
python3 scripts/install_core.py --check
```

Then install the plugin for your host from the repository root:

**Codex CLI** — add this repository's Codex marketplace and install its plugin:

```sh
codex plugin marketplace add https://github.com/kyungpyokim/model-effort-router-next --sparse .agents/plugins --sparse plugins/codex-model-effort-router
codex plugin add model-effort-router@model-effort-router
```

**Claude Code** — add this repository's Claude marketplace, install the plugin, then start a new session:

```sh
claude plugin marketplace add kyungpyokim/model-effort-router-next
claude plugin install model-effort-router@model-effort-router
```

**Antigravity CLI** — install the local plugin directory:

```sh
agy plugin install ./plugins/antigravity-model-effort-router
```

Antigravity can classify and advise, but worker execution is not supported. Marketplace plugin installs do not install or update the shared runtime; rerun `python3 scripts/install_core.py` from this checkout when updating it. See the [Codex plugin guide](https://developers.openai.com/plugins/build/plugins), [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces), and [Antigravity plugin guide](https://antigravity.google/docs/plugins/) for host-specific details.

## Routing contract

The classifier returns `role` and `effort`; `confidence` and `reason_code` are optional. Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. The first four use the execution model; the rest use the reasoning model. Effort is `low`, `medium`, `high`, or `xhigh`. Independent risk detection can raise a safety-sensitive review/design request to at least `high`, but never changes its role or model lane.

Defaults are Codex execution `gpt-6-luna`, reasoning `gpt-6.1-sol`; Claude execution `claude-sonnet-5-5`, reasoning `claude-opus-5-5`. Each host/lane has configurable primary, fallback, and supported efforts. MER never infers execution fallback from stderr or retries after a worker may have started; only an explicit pre-execution-unavailable signal permits it. Classifier providers may fall through to the configured next classifier. If all fail, CLI routing returns an error; hooks fail open and leave the user request unblocked.

## Classifier backend setup

The classifier backend decides the request's role and effort. It is separate from `models.<host>`, which selects the worker model. The built-in classifier default is `subscription` with no fallback. To use hosted Jev as the primary role/effort classifier, configure `difficulty.backend` as `jev`:

```json
{
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10}
}
```

Jev uses the TypeSafe `jev-latest` model by default. Store its API key in `~/.config/model-effort-router/config.json`, never in repository config:

```json
{
  "jev": {"api_key": "your-typesafe-api-key"}
}
```

The configured primary backend runs first; the fallback runs only if it fails.

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

On the latest 150-case synthetic holdout, Jev outperformed Nimble on role, effort, and exact joint classification:

| Backend | Role | Effort | Role + effort |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 141/150 (94.0%) | 119/150 (79.3%) | 111/150 (74.0%) |
| Nimble | 124/150 (82.7%) | 101/150 (67.3%) | 85/150 (56.7%) |

We recommend Jev when classification accuracy is the priority. Nimble provides local inference; set its fallback to `none` if requests must stay on-device. These results come from 150 synthetic cases and are directional, not a measure of real-world traffic. See the [evaluation report](docs/evaluation/README.md).

## Use

```sh
python3 <plugin>/bin/mer route --host codex --json 'Review the authentication changes'
python3 <plugin>/bin/mer route --host codex --role implementation --effort high --json 'Implement the approved design'
python3 <plugin>/bin/mer run --host codex --role test --effort medium 'Run and fix the focused tests'
```

`mer route` classifies/maps only. By default, `mer run` executes exactly one worker request. Reasoning roles run read-only. Antigravity can classify and provide advice, but worker execution is unsupported because Subagent isolation is unverified. `mer chat` was removed; use the route result to ask Main to invoke the selected Subagent. Explicit `--role` and `--effort` bypass automatic hook eligibility and must be provided together.

After a run, MER compares the repository's changed paths before and after the worker. When changes are detected, text output reports the `door` (`one-way` for data migration, data loss, or payment risk; otherwise `two-way`) and estimated `blast_radius` (`local` or `broad`), plus changed-file and top-level-directory counts. JSON includes the same values under `change`, with the resulting `risk_flags`. Blast radius is a path-based estimate; review the actual changes to assess impact.

### Low-first worker runs

```sh
python3 <plugin>/bin/mer run --host codex --role fix --effort low --low-first \
  --verify 'python3 -m unittest discover -s tests' --json 'Fix the approved bug'
```

For execution roles, `--low-first` starts at low and promotes to medium, then high only after the fixed verification command exits with a positive nonzero code. If high fails, it stops with `status: approval_required` before calling xhigh. Only pass `--approve-xhigh` when the user has explicitly approved xhigh for that run; agents must obtain approval before setting it. The configured model must support all four efforts. Each attempt starts a fresh session in the same workspace, keeping edits and receiving the original context plus the previous failure. Worker errors, cancellation, verification start failures, signal termination, and timeouts stop the loop. `--timeout` limits each worker attempt; `--verify-timeout` limits each check (default 300 seconds).

An approval stop returns `continuation_context` with the original request and last failure. After approval, pass that context as the request in the same workspace with `--low-first --role <same-role> --effort xhigh --approve-xhigh --verify <same-command>` to run only the xhigh continuation. Its usage is a separate run; combine both records when measuring the full task. Without the explicit xhigh effort, a new invocation starts at low. One-shot xhigh runs also require `--approve-xhigh`.

`--verify` is an explicit argv command executed without shell expansion, using the parent process's privileges and environment. Freeze meaningful completion checks before work starts: fixing argv does not make worker-editable tests tamper-proof. The last 2,000 characters of check output are sent to the next worker and returned in JSON; keep secrets out of that output. Persistent route logs store only attempt metadata, token counts, and check status/duration.

JSON and route logs record `first_pass`, `escalation_count`, and each attempt's effort, worker usage, and verification duration. `usage` sums reported worker tokens; `usage_missing` counts attempts with absent/incomplete usage. Classifier usage is separate. Deterministic checks add execution time but no router model call; any external model calls inside the check are unmeasured, so the token figures are not a complete validation cost.

For exploratory comparison, `--retry-low` adds one low retry with the same failure feedback before medium. Compare it with normal low-first on separate, equally initialized workspaces and report the full chain and usage; do not run both arms on the already-modified workspace.

Main should pass a compact Context Packet (`task`, `context`, `decisions`, `constraints`, `relevant_files`, `expected_result`). For review, pass only `goal`, `decisions`, `constraints`, `diff`, and `verification`; do not forward another agent's private reasoning or the full conversation by default. Hooks only provide this guidance and do not create native Subagents themselves.

## Configuration

Configuration uses JSON in `.model-effort-router.json` at the repository root or `~/.config/model-effort-router/config.json`; repository values override user values. Existing user files are not rewritten. Example:

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10},
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "fallback": "gpt-6.1-sol", "efforts": ["low", "medium", "high", "xhigh"]},
      "reasoning": {"primary": "gpt-6.1-sol", "fallback": "gpt-6-luna", "efforts": ["low", "medium", "high", "xhigh"]}
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
