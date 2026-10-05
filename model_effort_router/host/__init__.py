"""Environment guard shared by host executors."""
from ..difficulty.subscription import GUARD_ENV


def session_env(base):
    return {**base, GUARD_ENV: "1"}  # installed hooks stay quiet inside mer-driven sessions
