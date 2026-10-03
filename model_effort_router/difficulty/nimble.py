"""Nimble backend: Bespoke Nimble run locally through Ollama (`ollama pull nimble`, plan 8.3).

Ollama serves the same `systemone` API as TypeSafe Jev (POST /v1/systemone: choice / noul / score questions), so the
request and parsing are the shared SystemOneBackend path in jev.py. Differences: a local URL, no API key and no
Authorization header, and a loopback-only guard so the task text can never leave the machine by a typo (any other
host raises before sending, and the fallback chain takes over; the config url is also checked when the config is
validated). Any loopback port is accepted. Options: config `difficulty.nimble` beats env
(MER_NIMBLE_MODEL, MER_NIMBLE_URL) beats the defaults.
"""
import urllib.parse
import urllib.request

from .decision import RISK_FLAGS
from .jev import L4_MIN_PROB, L4_MIN_PROB_BY_FLAG, RISK_THRESHOLD, RISK_THRESHOLDS, SystemOneBackend, _RefuseRedirect, default_transport

DEFAULT_URL = "http://127.0.0.1:11434/v1/systemone"  # the address, not the name: no resolver dependence
DEFAULT_MODEL = "nimble"  # ollama tag `nimble` = nimble:9b
MODEL_ENV, URL_ENV = "MER_NIMBLE_MODEL", "MER_NIMBLE_URL"
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
OPTION_KEYS = ("model", "url", "risk_thresholds", "l4_min_prob", "l4_min_prob_by_flag")
# UNCALIBRATED for Nimble: these start as Jev's calibrated values (corpus-v1, plan 22.2/22.3) and need their own
# evaluation.compare run before they mean anything for this model; tune through `difficulty.nimble`.
NIMBLE_RISK_THRESHOLDS = dict(RISK_THRESHOLDS)
NIMBLE_L4_MIN_PROB = L4_MIN_PROB
NIMBLE_L4_MIN_PROB_BY_FLAG = dict(L4_MIN_PROB_BY_FLAG)

# No proxies (an http_proxy in the environment must not carry local task text elsewhere) and no redirects.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirect)


def local_transport(url, headers, body, timeout_s):
    return default_transport(url, headers, body, timeout_s, _LOCAL_OPENER)


def check_local_url(url):
    """http(s) to a loopback host only; raises ValueError otherwise (before anything is sent)."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError as exc:
        raise ValueError(f"nimble url is not a valid URL: {url!r}") from exc
    if parts.scheme not in ("http", "https") or host not in LOOPBACK_HOSTS or parts.username or parts.password:
        raise ValueError(f"nimble url must be http(s) to localhost, 127.0.0.1 or ::1, got {url!r}")
    return url


def _prob(v, what):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 1:
        raise ValueError(f"difficulty.nimble.{what} must be a number in [0, 1], got {v!r}")
    return v


def _by_flag(raw, what):
    if not isinstance(raw, dict):
        raise ValueError(f"difficulty.nimble.{what} must be an object of risk flag -> probability")
    unknown = sorted(set(raw) - set(RISK_FLAGS))
    if unknown:
        raise ValueError(f"difficulty.nimble.{what}: unknown risk flags {unknown}")
    return {f: _prob(v, f"{what}.{f}") for f, v in raw.items()}


def validate_options(raw):
    """The `difficulty.nimble` config object -> a clean dict. Unknown keys/flags and bad probabilities raise ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("difficulty.nimble must be an object")
    unknown = sorted(set(raw) - set(OPTION_KEYS))
    if unknown:
        raise ValueError(f"unknown difficulty.nimble keys {unknown}; allowed: {list(OPTION_KEYS)}")
    out = {}
    for key in ("model", "url"):
        if key in raw:
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise ValueError(f"difficulty.nimble.{key} must be a non-empty string")
            out[key] = raw[key]
    if "url" in out:
        check_local_url(out["url"])  # a bad url is a config error up front (checked again at send time: env, defaults)
    if "l4_min_prob" in raw:
        out["l4_min_prob"] = _prob(raw["l4_min_prob"], "l4_min_prob")
    for key in ("risk_thresholds", "l4_min_prob_by_flag"):
        if key in raw:
            out[key] = _by_flag(raw[key], key)
    return out


class NimbleBackend(SystemOneBackend):
    name = "nimble"

    def __init__(self, transport=local_transport, model=None, env=None, options=None):
        super().__init__(transport, model, env)
        self._options = validate_options(options or {})

    def _endpoint(self, env):
        o = self._options
        url = check_local_url(o.get("url") or env.get(URL_ENV) or DEFAULT_URL)
        return url, {"Content-Type": "application/json"}, self._model or o.get("model") or env.get(MODEL_ENV) or DEFAULT_MODEL

    def _tuning(self):
        o = self._options
        return ({**NIMBLE_RISK_THRESHOLDS, **o.get("risk_thresholds", {})}, RISK_THRESHOLD,
                o.get("l4_min_prob", NIMBLE_L4_MIN_PROB), {**NIMBLE_L4_MIN_PROB_BY_FLAG, **o.get("l4_min_prob_by_flag", {})})
