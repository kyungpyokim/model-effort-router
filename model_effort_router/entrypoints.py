"""Shared process entrypoints for plugins sharing one installed core."""
import os


RUNTIME_API = 1


class RuntimeCompatibilityError(RuntimeError):
    """The plugin launcher and shared core use different runtime APIs."""


def _check_api(runtime_api):
    if runtime_api != RUNTIME_API:
        raise RuntimeCompatibilityError("Plugin and shared core APIs differ; update all plugins and the shared core together")


def cli(host, *, runtime_api=1):
    _check_api(runtime_api)
    os.environ["MER_HOST"] = host
    from .cli import main
    return main()


def gate(host=None, *, runtime_api=1):
    _check_api(runtime_api)
    if host is not None:
        os.environ["MER_HOST"] = host
    from .gate.run import main
    return main()


def hook(host, plugin_root, *, runtime_api=1):
    try:
        _check_api(runtime_api)
        os.environ["MER_HOST"] = host
        from .host.codex_hooks import main
        return main("UserPromptSubmit", plugin_root)
    except BaseException:  # hook failures must never block the user's prompt
        return 0
