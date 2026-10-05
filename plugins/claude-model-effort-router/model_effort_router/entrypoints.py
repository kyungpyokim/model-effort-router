"""Shared process entrypoints for self-contained plugin bundles."""
import os


def cli(host):
    os.environ["MER_HOST"] = host
    from .cli import main
    return main()


def gate(host=None):
    if host is not None:
        os.environ["MER_HOST"] = host
    from .gate.run import main
    return main()


def hook(host, plugin_root):
    try:
        os.environ["MER_HOST"] = host
        from .host.codex_hooks import main
        return main("UserPromptSubmit", plugin_root)
    except BaseException:  # hook failures must never block the user's prompt
        return 0
