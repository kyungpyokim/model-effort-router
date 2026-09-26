"""Counter plugin: keeps its call count in the provided context."""


def register(ctx):
    ctx["plugin"] = "counter"
    ctx["calls"] = 0

    def bump():
        ctx["calls"] += 1
        return ctx["calls"]

    ctx["bump"] = bump
