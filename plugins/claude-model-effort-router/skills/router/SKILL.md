---
name: router
description: Turn model-effort-router on or off (default: on). When off, model routing is completely bypassed.
---

# Router On/Off Control (Claude Code)

Enable or disable `model-effort-router`.

- **Default:** `on` (`auto`). The router automatically classifies development requests and recommends the optimal model tier and reasoning effort.
- **When `off`:** Model routing is completely bypassed. The classifier is not invoked, hooks return immediately without advice, and the host agent executes directly with its default or active model.

## Commands

### 1. Toggle Router
- **Turn off (this agent only when run via the plugin `mer` / `MER_HOST=claude`):**
  ```bash
  mer off
  # or: mer mode off
  # explicit host or all agents:
  mer off --host claude
  mer off --all
  ```
  Add `--local` to apply only to the current repository (`.model-effort-router.json`).
- **Turn on:**
  ```bash
  mer on
  # or: mer mode on
  # explicit host or all agents:
  mer on --host claude
  mer on --all
  ```
  Add `--local` to apply only to the current repository.
- **Check status:**
  ```bash
  mer status
  # or: mer status --all
  ```

### 2. Per-Turn Override
You can override routing for a single turn by starting the prompt with:
- `/router off` — Bypass routing for this turn only.
- `/router on` — Force routing for this turn only.

### 3. Configuration Files
- **Project-level:** `.model-effort-router.json` in the project root:
  ```json
  {
    "router": {
      "mode": "off"
    }
  }
  ```
- **Global:** `~/.config/model-effort-router/config.json`:
  ```json
  {
    "router": {
      "mode": "off"
    }
  }
  ```
