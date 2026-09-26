# pluginbox

Dynamic plugin loading with per-plugin isolated contexts.

Run the acceptance checks from the fixture root:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest -q
```

## Fixture metadata

- Case: L5_new_plugin_architecture (implementation, L5)
- Task: Design and implement new dynamic plugin loading architecture with isolated contexts
- Expected initial test outcome: FAIL (pytest exit status 1)
- The loader dynamically discovers plugin files and registers them, so the
  discovery checks stay green; the isolation checks fail against the initial
  state, which executes every plugin against one shared context so state
  written by one plugin is visible to the other. They pass only once each
  plugin runs against its own isolated context and plugins cannot leak state
  into each other.

## Contracts

- `plugin_loader.load_plugins(plugin_dir)` discovers every `*.py` file in the
  directory (deterministic order), executes it, and calls its
  `register(ctx)` entry point; a file without `register` raises
  `ValueError`.
- Every plugin gets its own isolated context object: after loading, no two
  plugins share a context, and keys/counts written by one plugin never
  appear in (or mutate) another plugin's context.
- Registered exports keep working: `greet` returns `"hello, <name>"`,
  `bump` increments and returns the plugin's own call count.
- Plugins live under `plugins/`; loading runs offline from fixture-local
  sources only.
