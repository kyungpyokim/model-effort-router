"""Greet plugin: registers a greeting helper into the provided context."""


def register(ctx):
    ctx["plugin"] = "greet"
    ctx["greet"] = lambda who: f"hello, {who}"
