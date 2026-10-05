"""name -> factory registry. New backends register here; Router Core is untouched."""
from .conditional import NimbleJevBackend
from .jev import JevBackend
from .nimble import NimbleBackend
from .subscription import SubscriptionBackend

BACKENDS = {"subscription": SubscriptionBackend, "jev": JevBackend, "nimble": NimbleBackend, "nimble_jev": NimbleJevBackend}


def register(name, factory, registry=BACKENDS):
    if name in registry:
        raise ValueError(f"backend already registered: {name}")
    registry[name] = factory


def create(name, registry=BACKENDS, **options):
    """`options` (e.g. nimble's validated config) are passed to the factory only when given."""
    return registry[name](**options)  # KeyError for unknown names
