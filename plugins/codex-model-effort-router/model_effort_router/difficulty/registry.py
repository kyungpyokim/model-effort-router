"""name -> factory registry. New backends register here; Router Core is untouched."""
from .subscription import SubscriptionBackend

BACKENDS = {"subscription": SubscriptionBackend}


def register(name, factory, registry=BACKENDS):
    if name in registry:
        raise ValueError(f"backend already registered: {name}")
    registry[name] = factory


def create(name, registry=BACKENDS):
    return registry[name]()  # KeyError for unknown names
