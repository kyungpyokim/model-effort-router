"""Shared process entrypoints for plugins sharing one installed core."""

import importlib
import os
import sys


RUNTIME_API = 1


class RuntimeCompatibilityError(RuntimeError):
    """The plugin launcher and shared core use different runtime APIs."""


def _check_api(runtime_api):
    if runtime_api != RUNTIME_API:
        raise RuntimeCompatibilityError(
            "Plugin and shared core APIs differ; update all plugins and the shared core together"
        )


def _load_main(module):
    try:
        return importlib.import_module(module, __package__).main
    except ImportError:
        print(
            "Shared core is incomplete; reinstall it with python3 scripts/install_core.py from a matching checkout.",
            file=sys.stderr,
        )
        return None


def cli(host, *, runtime_api=1):
    _check_api(runtime_api)
    os.environ["MER_HOST"] = host
    main = _load_main(".cli")
    if main is None:
        return 2
    return main()


def gate(host=None, *, runtime_api=1):
    _check_api(runtime_api)
    if host is not None:
        os.environ["MER_HOST"] = host
    main = _load_main(".gate.run")
    if main is None:
        return 2
    return main()


def hook(host, plugin_root, *, runtime_api=1):
    try:
        _check_api(runtime_api)
        os.environ["MER_HOST"] = host
        from .host.codex_hooks import main

        return main("UserPromptSubmit", plugin_root)
    except BaseException:  # hook failures must never block the user's prompt
        return 0


class ModelEffortRouter:
    """Plugin host settings over the stable function entrypoints."""

    host = None
    gate_host = None
    runtime_api = None

    @classmethod
    def run_cli(cls):
        return cli(cls.host, runtime_api=cls.runtime_api)

    @classmethod
    def run_gate(cls):
        return gate(cls.gate_host, runtime_api=cls.runtime_api)

    @classmethod
    def run_hook(cls, plugin_root):
        return hook(cls.host, plugin_root, runtime_api=cls.runtime_api)
