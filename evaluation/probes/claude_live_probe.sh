#!/usr/bin/env bash
# Live checks for the Claude Code host (plan Phase 5). Makes real model calls (a few short ones plus one small
# mer run); run it yourself. Everything is written to $OUT for analysis; nothing outside a temp dir is touched.
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$REPO/runs/claude-probe}"
mkdir -p "$OUT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export MER_CORE_PATH="${MER_CORE_PATH:-$REPO}"
export MER_CLASSIFIER=1  # keep any installed router hook quiet inside these calls

echo "== 1. result shape (sonnet, medium, auto, Agent disallowed)"
(cd "$WORK" && /usr/bin/time -p claude -p --output-format json --model claude-sonnet-5-5 --effort medium \
  --permission-mode auto --disallowedTools Agent -- "Reply with exactly: ok") >"$OUT/1-shape.json" 2>"$OUT/1-time.txt"

SID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("session_id",""))' "$OUT/1-shape.json" 2>/dev/null)"
echo "== 2. resume with another model/effort (session $SID)"
(cd "$WORK" && claude -p --output-format json --resume "$SID" --model claude-opus-5-5 --effort high \
  -- "Reply with exactly: ok again") >"$OUT/2-resume.json" 2>"$OUT/2-err.txt"

echo "== 3. Agent tool really unavailable, and auto mode runs a shell command without a prompt"
(cd "$WORK" && claude -p --output-format json --model claude-sonnet-5-5 --effort medium --permission-mode auto \
  --disallowedTools Agent -- "Run the shell command 'python3 -c \"print(41+1)\"' and report its output. Then list every tool you have available, one name per line.") \
  >"$OUT/3-tools.json" 2>"$OUT/3-err.txt"

echo "== 4. read-only review argv cannot edit"
echo "x = 1" >"$WORK/a.py"
(cd "$WORK" && claude -p --output-format json --model claude-opus-5-5 --effort high --permission-mode dontAsk \
  --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --disallowedTools Agent --strict-mcp-config \
  --setting-sources user -- "Change a.py so x = 2, then tell me whether you could.") >"$OUT/4-readonly.json" 2>"$OUT/4-err.txt"
cat "$WORK/a.py" >"$OUT/4-a.py.after"

echo "== 5. isolated classifier call (haiku, safe mode, no tools): latency and tokens"
(cd "$WORK" && /usr/bin/time -p claude -p --output-format json --model claude-haiku-4-5 --permission-mode dontAsk \
  --tools "" --safe-mode --strict-mcp-config --no-session-persistence \
  -- "Answer with one word: easy or hard? Task: rename a variable.") >"$OUT/5-classifier.json" 2>"$OUT/5-time.txt"

echo "== 6. one small mer run on the pilot fixture (L1 message change)"
cp -R "$REPO/evaluation/pilot/fixture" "$WORK/fx"
(cd "$WORK/fx" && git init -q && git -c user.email=p@x -c user.name=p add -A && git -c user.email=p@x -c user.name=p commit -qm fixture)
(cd "$WORK/fx" && env -u MER_CLASSIFIER python3 "$REPO/plugins/claude-model-effort-router/bin/mer" run --host claude \
  "In shop/orders.py, change the error message 'insufficient stock for {sku}' to 'out of stock: {sku}'. Keep \`python3 -m unittest\` passing." \
  ) >"$OUT/6-mer.txt" 2>&1
(cd "$WORK/fx" && git diff) >"$OUT/6-mer.diff"

echo "== 7. lean context (mer's implement argv): CLAUDE.md and ~/.claude/rules must load, enabled plugins must be off"
mkdir -p "$WORK/lean"
printf '# Project instructions\nProject marker: PELICAN-42\n' >"$WORK/lean/CLAUDE.md"
USER_SETTINGS="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/settings.json"
# the same plugin-off JSON mer builds: every plugin enabled (true) in the user settings (and the cwd's project/local files) -> false
PLUGINS_OFF="$(python3 - "$USER_SETTINGS" "$WORK/lean/.claude/settings.json" "$WORK/lean/.claude/settings.local.json" <<'PY'
import json, sys
off = {}
for path in sys.argv[1:]:
    try:
        enabled = json.load(open(path)).get("enabledPlugins")
    except (OSError, ValueError, AttributeError):
        continue
    if isinstance(enabled, dict):
        off.update({k: False for k, v in enabled.items() if v is True})
print(json.dumps({"enabledPlugins": off}, sort_keys=True, separators=(",", ":")) if off else "")
PY
)"
SETTINGS_ARG=(); [ -n "$PLUGINS_OFF" ] && SETTINGS_ARG=(--settings "$PLUGINS_OFF")
echo "$PLUGINS_OFF" >"$OUT/7-plugins-off.json"
(cd "$WORK/lean" && claude -p --output-format json --model claude-sonnet-5-5 --effort medium --permission-mode auto \
  --disallowedTools Agent --strict-mcp-config "${SETTINGS_ARG[@]}" \
  -- "Reply with the project marker from your CLAUDE.md instructions, then list the names of any skills or plugins you were told about, then list the file paths of every instruction file (CLAUDE.md or rules) whose contents you were given.") \
  >"$OUT/7-lean.json" 2>"$OUT/7-err.txt"
# compare usage in 7-lean.json with 1-shape.json (step 1 runs the full context): the lean fixed context should be far smaller
python3 - "$OUT/7-lean.json" "$OUT/7-plugins-off.json" "${CLAUDE_CONFIG_DIR:-$HOME/.claude}" >"$OUT/7-check.txt" <<'PY'
import json, os, sys
try:
    reply = str(json.load(open(sys.argv[1])).get("result", ""))
except (OSError, ValueError):
    reply = ""
try:
    ids = list(json.loads(open(sys.argv[2]).read() or "{}").get("enabledPlugins", {}))
except (OSError, ValueError):
    ids = []
rules = os.path.join(sys.argv[3], "rules")
print("reply parsed:", bool(reply))
print("lists a path under ~/.claude/rules (expected: yes):", "yes" if (rules in reply or "/.claude/rules" in reply) else "NO")
names = {i.split("@")[0] for i in ids}  # e.g. superpowers@marketplace -> superpowers
hit = sorted(n for n in names if n and (n + ":" in reply or n in reply))
print("names an enabled plugin id or its skills prefix (expected: none):", hit or "none")
print("plugins switched off:", sorted(ids))
PY
cat "$OUT/7-check.txt"

echo "== 8. lean read-only argv must not run project/local hooks (expected: neither marker exists, is_error false)"
mkdir -p "$WORK/ro/.claude"
for kind in project local; do
  f="$WORK/ro/.claude/settings.json"; [ "$kind" = local ] && f="$WORK/ro/.claude/settings.local.json"
  printf '{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"touch %s/hook-fired-%s"}]}]}}\n' "$WORK/ro" "$kind" >"$f"
done
is_error() { python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("is_error"))' "$1" 2>/dev/null || echo "unparseable"; }
(cd "$WORK/ro" && claude -p --output-format json --model claude-opus-5-5 --effort high --permission-mode dontAsk \
  --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --disallowedTools Agent --strict-mcp-config \
  --setting-sources user --settings '{"disableAllHooks": true}' -- "Reply with exactly: ok") >"$OUT/8-readonly.json" 2>"$OUT/8-err.txt"
{ echo "8-readonly.json is_error: $(is_error "$OUT/8-readonly.json")  (must be False: a rejected --settings must not look like a pass)"
  for kind in project local; do
    if [ -e "$WORK/ro/hook-fired-$kind" ]; then echo "hook-fired-$kind: YES (project/local settings were loaded)"; else echo "hook-fired-$kind: no"; fi
  done; } >"$OUT/8-hooks.txt"

echo "== 8b. same argv, but --settings ALSO carries a SessionStart hook: disableAllHooks must win (expected: no marker)"
mkdir -p "$WORK/ro2"
FLAG_SETTINGS="$(python3 -c 'import json,sys; print(json.dumps({"disableAllHooks": True, "hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "touch " + sys.argv[1] + "/hook-fired-flag"}]}]}}))' "$WORK/ro2")"
(cd "$WORK/ro2" && claude -p --output-format json --model claude-opus-5-5 --effort high --permission-mode dontAsk \
  --tools Read,Grep,Glob --allowedTools Read,Grep,Glob --disallowedTools Agent --strict-mcp-config \
  --setting-sources user --settings "$FLAG_SETTINGS" -- "Reply with exactly: ok") >"$OUT/8b-readonly.json" 2>"$OUT/8b-err.txt"
{ echo "8b-readonly.json is_error: $(is_error "$OUT/8b-readonly.json")  (must be False, else the test proves nothing)"
  if [ -e "$WORK/ro2/hook-fired-flag" ]; then echo "hook-fired-flag: YES (disableAllHooks was NOT honoured)"; else echo "hook-fired-flag: no"; fi; } >>"$OUT/8-hooks.txt"
cat "$OUT/8-hooks.txt"

echo "done: $OUT"
