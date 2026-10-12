#!/usr/bin/env bash
# Update this machine's installs to the checkout/marketplace version.
# Usage: scripts/deploy.sh [core|claude|codex|antigravity|opencode ...]   (no argument = all)
# Marketplace installs (claude, codex) pull from GitHub: merge to main first.
# core, antigravity and opencode use this checkout: run it on an up-to-date main.
set -u
cd "$(dirname "$0")/.."

PLUGIN=model-effort-router
failed=()

step() { printf '\n==> %s\n' "$1"; }
have() { command -v "$1" >/dev/null 2>&1 || { echo "skip: $1 not installed"; return 1; }; }
run() { "$@" || failed+=("$*"); }

deploy_core() {
  step "shared runtime"
  run python3 scripts/install_core.py && run python3 scripts/install_core.py --check
}
deploy_claude() {
  step "claude"
  have claude || return 0
  run claude plugin marketplace update "$PLUGIN"
  run claude plugin update "$PLUGIN@$PLUGIN"
}
deploy_codex() {
  step "codex"
  have codex || return 0
  run codex plugin marketplace upgrade "$PLUGIN"
  run codex plugin add "$PLUGIN@$PLUGIN"
}
deploy_antigravity() {
  step "antigravity"
  have agy || return 0
  run agy plugin validate ./plugins/antigravity-model-effort-router
  run agy plugin install ./plugins/antigravity-model-effort-router
  # the manifest has no version, so verify the installed copy matches this checkout
  run diff -r -x __pycache__ ./plugins/antigravity-model-effort-router "$HOME/.gemini/config/plugins/$PLUGIN"
}
deploy_opencode() {
  step "opencode"
  have bun || return 0
  # opencode.json points at this checkout's plugin path, so only dependencies need syncing
  pushd plugins/opencode-model-effort-router >/dev/null || return 1
  run bun install --frozen-lockfile
  popd >/dev/null
}

hosts=("$@")
[ ${#hosts[@]} -eq 0 ] && hosts=(core claude codex antigravity opencode)

git fetch -q origin 2>/dev/null
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main 2>/dev/null)" ]; then
  echo "warning: checkout is not at origin/main; core, antigravity and opencode will use this checkout" >&2
fi

for host in "${hosts[@]}"; do
  case "$host" in
    core | claude | codex | antigravity | opencode) "deploy_$host" ;;
    *) echo "unknown target: $host (core|claude|codex|antigravity|opencode)" >&2; exit 2 ;;
  esac
done

printf '\n'
if [ ${#failed[@]} -gt 0 ]; then
  printf 'failed: %s\n' "${failed[@]}" >&2
  exit 1
fi
echo "done. Start a new session in each host for the hooks to apply."
