"""name -> factory registry. New backends register here; Router Core is untouched."""
from .jev import JevBackend
from .subscription import SubscriptionBackend

BACKENDS = {"subscription": SubscriptionBackend, "jev": JevBackend}


def register(name, factory, registry=BACKENDS):
    if name in registry:
        raise ValueError(f"backend already registered: {name}")
    registry[name] = factory


def create(name, registry=BACKENDS):
    return registry[name]()  # KeyError for unknown names
