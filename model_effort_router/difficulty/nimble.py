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

from .jev import SystemOneBackend, _RefuseRedirect, default_transport

DEFAULT_URL = "http://127.0.0.1:11434/v1/systemone"  # the address, not the name: no resolver dependence
DEFAULT_MODEL = "nimble"  # ollama tag `nimble` = nimble:9b
MODEL_ENV, URL_ENV = "MER_NIMBLE_MODEL", "MER_NIMBLE_URL"
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
OPTION_KEYS = ("model", "url")

# No proxies (an http_proxy in the environment must not carry local task text elsewhere) and no redirects.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _RefuseRedirect)


def local_transport(url, headers, body, timeout_s):
    return default_transport(url, headers, body, timeout_s, _LOCAL_OPENER)


def check_local_url(url, name="nimble"):
    """http(s) to a loopback host only; raises ValueError otherwise (before anything is sent)."""
    try:
        parts = urllib.parse.urlsplit(url)
        host = parts.hostname
    except ValueError as exc:
        raise ValueError(f"{name} url is not a valid URL: {url!r}") from exc
    if parts.scheme not in ("http", "https") or host not in LOOPBACK_HOSTS or parts.username or parts.password:
        raise ValueError(f"{name} url must be http(s) to localhost, 127.0.0.1 or ::1, got {url!r}")
    return url


def validate_options(raw, name="nimble"):
    """Validate local SystemOne model/url options and return a clean dict."""
    if not isinstance(raw, dict):
        raise ValueError(f"difficulty.{name} must be an object")
    unknown = sorted(set(raw) - set(OPTION_KEYS))
    if unknown:
        raise ValueError(f"unknown difficulty.{name} keys {unknown}; allowed: {list(OPTION_KEYS)}")
    out = {}
    for key in ("model", "url"):
        if key in raw:
            if not isinstance(raw[key], str) or not raw[key].strip():
                raise ValueError(f"difficulty.{name}.{key} must be a non-empty string")
            out[key] = raw[key]
    if "url" in out:
        check_local_url(out["url"], name)  # a bad url is a config error up front (checked again at send time: env, defaults)
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
