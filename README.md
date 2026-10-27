# Model Effort Router

한국어 문서는 [README.ko.md](README.ko.md)를 참고하세요.

MER (Model Effort Router) classifies a development request as a **role + effort** and recommends the matching host model. MER handles model and effort selection; the host handles work, review, and fixes. Recommendations do not change the active turn's settings.

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

All host integrations provide model/effort advice only. Marketplace plugin installs do not install or update the shared runtime; rerun `python3 scripts/install_core.py` from this checkout when updating it. See the [Codex plugin guide](https://developers.openai.com/plugins/build/plugins), [Claude Code marketplace guide](https://code.claude.com/docs/en/plugin-marketplaces), and [Antigravity plugin guide](https://antigravity.google/docs/plugins/) for host-specific details.

## Updating and releasing

A plugin update only reaches installed users when its `version` changes, and marketplace installs never touch the shared runtime. After a change is merged to `main`, update every local install with one command:

```sh
git checkout main && git pull
scripts/deploy.sh                 # all targets
scripts/deploy.sh claude codex    # or pick targets: core|claude|codex|antigravity|opencode
```

| Target | What it runs | Source |
|---|---|---|
| `core` | `scripts/install_core.py` and `--check` | this checkout |
| `claude` | `claude plugin marketplace update`, `claude plugin update` | GitHub `main` |
| `codex` | `codex plugin marketplace upgrade`, `codex plugin add` | GitHub `main` |
| `antigravity` | `agy plugin validate`, `agy plugin install` | this checkout |
| `opencode` | `bun install --frozen-lockfile` (`opencode.json` already points at this checkout) | this checkout |

A target whose CLI is missing is skipped. The script warns when the checkout is not at `origin/main`, continues past a failing step, and exits non-zero with the failed commands listed. Start a new session in each host afterwards so the hooks reload.

Release checklist:

1. Bump `version` in the Claude and Codex `plugin.json`, OpenCode `package.json` and `package-lock.json`, and the two version assertions in `tests/test_opencode_plugin.py` and `tests/test_plugin_bundle.py`.
2. Merge to `main` and wait for the `main` CI run to pass.
3. Tag the merge commit as `model-effort-router--vX.Y.Z` and publish a GitHub Release titled `Model Effort Router X.Y.Z` (`gh release create`).
4. Run `scripts/deploy.sh`.

## Routing contract

The classifier returns `role` and `effort`; `confidence` and `reason_code` are optional. Roles are `implementation`, `fix`, `lint`, `test`, `plan`, `design`, `review`, and `analysis`. The first four use the execution model; the rest use the reasoning model. Effort is `low`, `medium`, `high`, `xhigh`, or `max`. Independent risk detection can raise a safety-sensitive review/design request to at least `high`, but never changes its role or model lane.

Defaults are Codex execution `gpt-6-luna` and reasoning `gpt-6.1-sol`; Claude execution `claude-sonnet-5-5` and reasoning `claude-opus-5-5`; Antigravity execution `gemini-3.8-flash` and reasoning `gemini-4-argon`; OpenCode advice execution `opencode/mimo-v2.6-flash-free`, reasoning `opencode/nemotron-3-ultra-free` with reasoning alternatives `opencode-go/glm-5.3`, `opencode-go/kimi-k3`, and `opencode-go/grok-4.7`. Each host/lane accepts `primary`, optional `alternatives`, and supported efforts. `primary` is recommended; alternatives are listed as user-selectable choices. Legacy model-level `fallback` values are accepted for config compatibility but are no longer used. For example:

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

If a lane's `efforts` omits `max` and lists `ultra` (for a model whose picker goes from `xhigh` straight to `ultra`), the classifier's `max` is applied as `ultra`. `ultra` also adds automatic task delegation, so expect more tokens.

Replace the example IDs with models available to the host. OpenCode returns `model_options`; the other hooks include configured alternatives in their advice. Alternatives are recommendations only and never trigger model switching. Classifier providers may fall through to the configured next classifier. If all fail, CLI routing returns an error; hooks fail open and leave the user request unblocked.

## Classifier backend setup

The classifier backend decides the request's role and effort. It is separate from `models.<host>`, which supplies the recommended host model. The built-in classifier default is `subscription` with no fallback. To use hosted Jev as the primary role/effort classifier, configure `difficulty.backend` as `jev`:

```json
{
  "difficulty": {"backend": "jev", "fallback": "subscription", "timeout_s": 10}
}
```

With `backend: jev`, every prompt that is not host-generated is sent to the Jev API, which decides eligibility (`route` or `no_route`), role and effort. There is no keyword prefilter: whichever classifier is configured judges every non-blank prompt (a non-Jev backend always routes, so chit-chat costs one classifier call too).

`fallback` may also be a list, tried in order after `backend`, e.g. `"fallback": ["openai_decisions", "nimble"]`. The `timeout_s` of each backend is capped so the whole chain fits the hook's 30 second limit (12s each for one or two backends, 8s for three).

**Session context (Claude and Codex hooks).** So that short follow-ups such as "go ahead" are classified by the work they continue, the hook also sends Jev a session summary and the most recent user/assistant turns (text only, never tool output) next to the current prompt. The summary is produced in the background by the host's own CLI (`claude -p` on Haiku; `codex exec` on the economy model with its shell and exec tools disabled; the text goes on stdin) and stored under the state directory (summary files unused for 14 days are deleted); it lags one turn, and the newest turns are sent raw. The hook never waits for it. Disable it with `{"context": {"enabled": false}}` in repository or user config; `context.max_chars` (default 6000) bounds the summary plus recent turns. With `context.enabled: false`, only the current prompt is sent. The background summary needs the standalone `claude` CLI to be signed in (`claude auth login`); a session inside the Claude desktop app does not lend its sign-in to it, and without it the summary is skipped and an error event is logged. Codex summaries need the `codex` CLI signed in (`codex login`).

Codex limits: on Codex 0.160.1 a canary file stayed unreadable to `codex exec` with those tools disabled under direct, injected, and `functions.exec` / `spawn_agent` bypass attempts, while a run without the flags read it. That is behavioral evidence for that version only, not a guarantee. On any other Codex version the Codex summary is skipped (an error event is logged) and the Codex classifier gets neither the tool-disabling flags nor the session context. `--ignore-user-config` does not stop the global `~/.codex/AGENTS.md` from loading (observed: about 26k input tokens for a trivial prompt; `-c project_doc_max_bytes=0` did not help), so user-level Codex instructions add tokens to every Codex classifier and summary call.

Jev uses the TypeSafe `jev-latest` model by default. Store its API key in `~/.config/model-effort-router/config.json`, never in repository config:

```json
{
  "jev": {"api_key": "your-typesafe-api-key"}
}
```

Add an optional `"model"` to pick another Jev model, e.g. `{"jev": {"api_key": "...", "model": "jev-1.13-free"}}`; it overrides `MER_JEV_MODEL`, which overrides `jev-latest`.

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

For local classification with Laya, install its serving extra and bind the server to loopback:

```sh
python -m pip install 'laya[serve]'
LAYA_HOST=127.0.0.1 laya-serve
```

Select it in `.model-effort-router.json` or the global config:

```json
{"difficulty": {"backend": "laya", "laya": {"model": "laya", "url": "http://127.0.0.1:8000/v1/systemone"}}}
```

Laya defaults to model `laya` at `http://127.0.0.1:8000/v1/systemone`. Select `difficulty.backend: "laya"`; optional `difficulty.laya.model` and `.url` override defaults, followed by `MER_LAYA_MODEL` and `MER_LAYA_URL` environment variables. URLs must use HTTP(S) and point to `localhost`, `127.0.0.1`, or `::1`. Set `MER_LAYA_API_KEY` only when the local server requires bearer authentication. The default `laya` model alias resolves to the English checkpoint; this setup does not automatically select the multilingual checkpoint. Configure `fallback` separately if you want another classifier after Laya fails. See the [Laya HTTP API documentation](https://nandhakishorm.github.io/laya/http-api/).

### Classifier performance

On the 150-case v3 synthetic corpus, the recorded role/effort match rates were:

| Backend | Role | Effort | Role + effort |
|---|---:|---:|---:|
| Jev (`jev-latest`) | 141/150 (94.0%) | 119/150 (79.3%) | 111/150 (74.0%) |
| Nimble | 124/150 (82.7%) | 101/150 (67.3%) | 85/150 (56.7%) |
| Laya (`english`) | 90/150 (60.0%) | 38/150 (25.3%) | 30/150 (20.0%) |
| Laya (`laya:322m-multilingual-mlx-fp16`, Ollama MLX) | 56/150 (37.3%) | 30/150 (20.0%) | 11/150 (7.3%) |
| OpenAI Decisions API (`gpt-6-luna`) | 136/150 (90.7%) | 119/150 (79.3%) | 107/150 (71.3%) |

The Decisions API is the endpoint; `gpt-6-luna` is its model. Jev had the highest recorded match rates on this corpus. All results use the same previously evaluated cases, so treat them as agreement with adjudicated labels, not a fresh independent measure of real-world accuracy. The English and multilingual Laya rows also use different checkpoints, serving runtimes, and question instructions, so their score difference cannot isolate the effect of multilingual support. Nimble provides local inference; set its fallback to `none` if requests must stay on-device. See the [evaluation index](docs/evaluation/README.md), [English Laya run](docs/evaluation/laya-20261008.md), [multilingual Laya run](docs/evaluation/laya-multilingual-20261008.md), and [Decisions API run](docs/evaluation/openai-decisions-20261007.md).

## Use

```sh
python3 <plugin>/bin/mer route --host codex --json 'Review the authentication changes'
python3 <plugin>/bin/mer route --host codex --role implementation --effort high --json 'Implement the approved design'
python3 <plugin>/bin/mer report --since 12h --limit 10
python3 <plugin>/bin/mer on                        # enable router globally (mode: auto)
python3 <plugin>/bin/mer off                       # disable router globally (mode: off, bypass)
python3 <plugin>/bin/mer status                    # show active mode and config source
python3 <plugin>/bin/mer off --local               # disable router for current repository only
```

`mer route` classifies a request's role/effort and maps it to a host model. Provide `--role` and `--effort` together for an explicit route. MER does not execute workers, verification loops, reviews, or fixes. For script compatibility, `mer run` and `mer chat` return exit code 2 with guidance to use `mer route`. Historical `run` log entries remain readable by `mer report`.

`mer on` and `mer off` toggle routing globally or locally (`--local`). When disabled (`mode: "off"`), model routing is completely bypassed with zero classifier calls or hook advice overhead, falling back directly to host default models. `mer status` checks the current active status, mode, and config source.

OpenCode's `mer` tool returns the same model/effort recommendation, and `mer_report` summarizes logs. Host hooks add a recommendation; they do not change the active model or effort. The Codex and Claude desktop apps render no hook output, so the hook advice also asks Main to open its first reply line with the recommendation.

The intended host workflow is **task instruction → MER model/effort recommendation → host work → host review → host fixes**. MER ends after the recommendation; it does not launch workers, run the review, apply fixes, or run verification loops.

For `implementation` and `fix` requests the advice also asks Main to request an independent review with the plugin's `review` skill after nontrivial code changes (not docs, config or mechanical edits). This is an instruction to the model, not an enforced check: no hook blocks the turn or inspects the diff.

## Configuration

Configuration uses JSON in `.model-effort-router.json` at the repository root or `~/.config/model-effort-router/config.json`; repository values override user values. Existing user files are not rewritten. Example:

```json
{
  "router": {"mode": "auto"},
  "difficulty": {"backend": "jev", "timeout_s": 10},
  "models": {
    "codex": {
      "execution": {"primary": "gpt-6-luna", "alternatives": ["gpt-6-astra"], "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "gpt-6.1-sol", "alternatives": ["gpt-6-astra"], "efforts": ["low", "medium", "high", "xhigh", "max"]}
    },
    "claude": {
      "execution": {"primary": "claude-sonnet-5-5", "alternatives": ["claude-fable-5-1"], "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "claude-opus-5-5", "alternatives": ["claude-fable-5-1"], "efforts": ["low", "medium", "high", "xhigh", "max"]}
    },
    "antigravity": {
      "execution": {"primary": "gemini-3.8-flash", "alternatives": ["claude-sonnet-5-5"], "efforts": ["medium", "high"]},
      "reasoning": {"primary": "gemini-4-argon", "alternatives": ["claude-opus-5-5"], "efforts": ["medium", "high"]}
    },
    "opencode": {
      "execution": {"primary": "opencode/mimo-v2.6-flash-free", "efforts": ["low", "medium", "high", "xhigh", "max"]},
      "reasoning": {"primary": "opencode/nemotron-3-ultra-free", "alternatives": ["opencode-go/glm-5.3", "opencode-go/kimi-k3", "opencode-go/grok-4.7"], "efforts": ["low", "medium", "high", "xhigh", "max"]}
    }
  }
}
```

Legacy L1-L5, tier/profile, session, escalation, and `nimble_jev` settings are rejected with migration guidance. Replace tier overrides with `/router role=<role> effort=<effort>`; replace an old Main-session routing command with `mer route`. `nimble_jev` is removed; configure `nimble` and a separate classifier fallback such as `jev`.

Jev credentials belong only in the global user config; see [Classifier backend setup](#classifier-backend-setup). Repository config cannot provide this credential.

### Experimental: policy mode

`router.mode = "policy"` skips the classifier. The `UserPromptSubmit` hook injects the static model map (execution and reasoning lanes with supported efforts) as a model-selection reference. Every non-blank prompt gets the policy; it makes no model call. Codex and Claude only; other hosts stay silent.

- Enable: set `{"router": {"mode": "policy"}}` in the global user config, or start a prompt with `/router policy`. Switch back with `"mode": "auto"` (the default). An explicit `/router role=<role> effort=<effort>` keeps its normal behavior.
- This is an A/B experiment against `auto`; the losing mode will be removed after the comparison.
- Compare the two from the workflow logs: `python3 scripts/compare_modes.py [--since <unix ts>]` prints route counts, Subagent correlation counts, median hook latency, and classifier tokens per mode and host.

## Workflow log

Each session appends to `~/.local/state/model-effort-router/<session>-<hash>.log.jsonl` (override with `MER_STATE_DIR`). Workflow events include `route` (decision plus advice action), host-reported `subagent_start`/`subagent_stop`, historical `run` events, `context_refresh`, and fixed-code `error` events. Current MER versions do not emit `run` events; old entries remain readable for report compatibility. Prompts and Subagent output are not logged directly; bounded excerpts from a classifier's failed HTTP response may include text the provider echoed.

- A `subagent_start` carries `correlation.expected` (the session's latest logged `route`) and `correlation.matched`. Current route advice is marked `selection_only`: Codex can compare the host-reported Subagent model with the recommended model (`matched_on: ["model"]`); Claude exposes no model in its lifecycle payload, so current route events are unverified there (`matched_on: []`). MER records host events but does not launch or direct Subagents. Historical route events without `selection_only` retain their old Claude agent-type comparison. Effort is never verified.
- Classifier fallback: a `route` event carries `classifier_causes` (e.g. `["jev:HTTP 400 [code=invalid_request_error; message=Unknown model]"]`: backend names, error types, statuses, bounded structured identifiers, and up to 240 characters of response detail with sensitive fields and common credential patterns redacted) when a classifier failed and routing fell back, including on `no_route` and when every classifier fails. Detailed excerpts are stored in the local debug log, including when all classifiers fail; `mer report` can display these causes for debugging, while immediate hook advice and routing failure messages show backend plus status/type summaries. Routing errors record the exception type and stage without the exception message. Excerpts may contain provider-echoed text; review the log before sharing it. The hook shows `[model-effort-router] classifier fallback: jev failed (HTTP 503) → classified by openai_decisions`, or `classifier failed: ...; no routing advice this turn.` when every classifier fails. The Codex and Claude desktop apps do not show hook messages, so the advice also asks Main to tell the user.
- A `subagent_stop` copies the `correlation` of the `subagent_start` with the same `agent_id`; without one it is `null`.
- Subagent events record Codex's `turn_id` as `agent_turn_id`: it is the child's turn, not the route's `turn_id`.
- Hooks only provide the routing recommendation; they do not alter the active model or effort. The route log records the recommended profile and, where available, the current Main model. On Codex, a role config (`.codex/agents/*.toml`) may override the recommendation; host-reported Subagent model correlation can show whether the reported model matches, but it does not verify effort or control execution.
- Limits: only the last 64 KB of the log is searched for the latest route, and prompts with routing `off` write no `route` event, so a Subagent started after one is compared with the previous logged route.

```bash
jq -c 'select(.event|test("route|subagent|run")) | {ts,event,action:.advice.action,model:(.model // .advice.routed_model),matched:.correlation.matched}' ~/.local/state/model-effort-router/<session>-*.log.jsonl
```

### Report

`mer report` summarizes these logs. It lists recent route, host-reported Subagent start/stop, historical run, context-refresh, and error rows. Historical run rows may include verification outcome and duration; they describe pre-route-only runs and are retained for compatibility. The summary includes routed `(model, effort)` pairs, model recommendation actions, route matches where available, classifier health, Subagent lifecycle, context-refresh health, and classifier/context-refresh token totals.

- Options: `--session <id prefix>`, `--since <n>m|h|d` (for example `12h`), and `--limit <n>` (rows to list, default 20; `0` prints only the summary).
- Tokens are recorded for `route` (classifier) and `context_refresh`; historical `run` entries may contain worker tokens. Main and host Subagent turns are not logged, so their tokens are not shown. Exception messages, prompts, transcripts, verification output, and Subagent output are never written to the workflow log.
- Claude, Codex, and Antigravity ship `classify`, `router`, and `report` skills. OpenCode has the `mer` and `mer_report` tools, and its routes are logged per session through `mer route --session <id>`.

## Runtime development

`model_effort_router/` is the shared runtime source. Plugins contain host integration only. Use `MER_CORE_PATH="$PWD"` for development. Install and verify with:

```sh
python3 scripts/install_core.py
python3 scripts/install_core.py --check
MER_CORE_PATH="$PWD" python3 -m unittest discover -s tests
```

Install the `pre-commit` CLI, run
`npm --prefix plugins/opencode-model-effort-router ci`, and enable the repository
hooks with `git config core.hooksPath .githooks`. The hooks run Ruff for Python files and
the OpenCode package's ESLint and Prettier checks for TypeScript files.
