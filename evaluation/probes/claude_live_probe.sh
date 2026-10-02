#!/usr/bin/env bash
# Live checks for the Claude Code host (plan Phase 5). Makes real model calls (a few short ones plus one small
# mer run); run it yourself. Everything is written to $OUT for analysis; nothing outside a temp dir is touched.
set -u
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$REPO/runs/claude-probe}"
mkdir -p "$OUT"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
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

echo "done: $OUT"
