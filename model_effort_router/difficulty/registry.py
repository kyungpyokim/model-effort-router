"""name -> factory registry. New backends register here; Router Core is untouched."""

from .jev import JevBackend
from .laya import LayaBackend
from .nimble import NimbleBackend
from .openai_decisions import OpenAIDecisionsBackend
from .subscription import SubscriptionBackend

BACKENDS = {
    "subscription": SubscriptionBackend,
    "jev": JevBackend,
    "nimble": NimbleBackend,
    "laya": LayaBackend,
    "openai_decisions": OpenAIDecisionsBackend,
}


def register(name, factory, registry=BACKENDS):
    if name in registry:
        raise ValueError(f"backend already registered: {name}")
    registry[name] = factory


def create(name, registry=BACKENDS, **options):
    """`options` (e.g. a backend's validated config) are passed to the factory only when given."""
    if name == "nimble_jev":
        raise ValueError(
            "difficulty.backend 'nimble_jev' was removed; use 'nimble' with fallback 'jev'"
        )
    return registry[name](**options)  # KeyError for unknown names
