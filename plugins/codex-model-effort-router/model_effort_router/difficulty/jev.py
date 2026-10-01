"""Jev backend: TypeSafe `systemone` API, one `score` question for the level + one `noul` per risk flag (plan 8.2).

Transport is injectable so tests never touch the network.
Transport contract: transport(url, headers, body_bytes, timeout_s) -> (status, text); raises on network error/timeout.
Any non-2xx, bad JSON or missing/invalid answer raises, so the fallback chain takes over.
"""
import json
import os
import threading
import urllib.error
import urllib.request

from .decision import LEVELS, RISK_FLAGS, DifficultyDecision, DifficultyInput
from .subscription import LEVEL_DESCRIPTIONS, MAX_PATHS, MAX_TASK_CHARS, BackendOutputError

URL = "https://api.typesafe.ai/v1/systemone"
KEY_ENV = "TYPESAFE_API_KEY"
MODEL_ENV = "MER_JEV_MODEL"
DEFAULT_MODEL = "jev-latest"
RISK_THRESHOLD = 0.5  # noul probability at or above this sets the flag (per-flag values: RISK_THRESHOLDS)
# flag -> threshold, calibrated on the 40-case seed corpus (plan 22.2, 2026-10-01): Jev over-flags at 0.5 (precision
# 51%); these keep every labeled flag (with the rule-based detector merged) at 79% precision. Small sample: recheck.
RISK_THRESHOLDS = {"security": 0.85, "auth": 0.5, "payment": 0.95, "data_migration": 0.7, "data_loss": 0.75,
                   "concurrency": 0.8}

_RISK_HELP = {
    "security": "security-sensitive code (crypto, input sanitising, vulnerabilities, secrets)",
    "auth": "authentication or authorization (login, sessions, tokens, permissions)",
    "payment": "payments, billing or money handling",
    "data_migration": "a schema or data migration",
    "data_loss": "a risk of deleting or corrupting existing data",
    "concurrency": "concurrency (threads, locks, races, async ordering)",
}
QUESTIONS = {
    "level": {
        "type": "score",
        "instructions": "Rate the difficulty of this software task, from the easiest level to the hardest.",
        "criteria": list(LEVEL_DESCRIPTIONS),
    },
    **{f: {"type": "noul", "instructions": f"Does this task involve {_RISK_HELP[f]}?"} for f in RISK_FLAGS},
}


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    """The API is never redirected: a 30x becomes an HTTP error status (and the chain falls back)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_RefuseRedirect)


def _post(url, headers, body, timeout_s):
    plain = {k: v for k, v in headers.items() if k.lower() != "authorization"}
    req = urllib.request.Request(url, data=body, headers=plain, method="POST")
    if "Authorization" in headers:  # never copied onto a redirected request
        req.add_unredirected_header("Authorization", headers["Authorization"])
    try:
        with _OPENER.open(req, timeout=timeout_s) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # status only: never echo headers
        return exc.code, ""


def default_transport(url, headers, body, timeout_s):
    """`urlopen(timeout=)` bounds each socket op, not DNS or a trickling body: enforce a total deadline."""
    out = {}

    def call():
        try:
            out["ok"] = _post(url, headers, body, timeout_s)
        except Exception as exc:
            out["err"] = exc

    worker = threading.Thread(target=call, daemon=True)  # ponytail: an overrun thread lingers until the process exits
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError(f"jev exceeded {timeout_s}s")
    if "err" in out:
        raise out["err"]
    return out["ok"]


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


LEVEL_KEYS = tuple(str(i) for i in range(len(LEVELS)))  # score probabilities are keyed by criterion index


def _level_and_dist(ans):
    """Fail closed: any other key set or scale (unverified against a live response) raises."""
    probs = ans.get("probabilities")
    if not isinstance(probs, dict) or set(probs) != set(LEVEL_KEYS):
        raise BackendOutputError("jev level probabilities must be keyed exactly 0..4")
    vals = [_num(probs[k]) for k in LEVEL_KEYS]
    if any(v is None or v < 0 for v in vals) or sum(vals) <= 0:
        raise BackendOutputError("jev level probabilities are not usable")
    top = max(vals)
    idx = max(i for i, v in enumerate(vals) if v == top)  # tie -> higher level is safer
    total = sum(vals)
    return LEVELS[idx], {lv: v / total for lv, v in zip(LEVELS, vals)}


def _risk(answers, flag):
    """The noul value in [0, 1] (bool accepted). Missing or anything else raises: a lost risk flag must not pass silently."""
    ans = answers.get(flag)
    v = ans.get("noul") if isinstance(ans, dict) else None
    v = float(v) if isinstance(v, bool) else _num(v)
    if v is None or not 0 <= v <= 1:
        raise BackendOutputError(f"jev answer for {flag} is missing or not a probability")
    return v


class JevBackend:
    name = "jev"
    calls_model = True  # external API; route events log its usage

    def __init__(self, transport=default_transport, model=None, env=None):
        self._transport, self._model, self._env = transport, model, env
        self.last_usage = None  # {"input_tokens", "output_tokens"} of the latest call
        self.last_risk_scores = None  # raw noul per flag of the latest call (evaluation: threshold calibration)

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = self.last_risk_scores = None
        env = os.environ if self._env is None else self._env
        key = env.get(KEY_ENV)
        if not key:
            raise RuntimeError(f"{KEY_ENV} is not set")
        model = self._model or env.get(MODEL_ENV) or DEFAULT_MODEL
        paths = "\n".join(task.paths[:MAX_PATHS]) or "(none)"
        body = json.dumps({
            "state": f"Task:\n{task.task[:MAX_TASK_CHARS]}\n\nChanged/expected paths:\n{paths}",
            "model": model, "questions": QUESTIONS,
        }).encode("utf-8")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        status, text = self._transport(URL, headers, body, timeout_s)
        if not 200 <= status < 300:
            raise RuntimeError(f"jev HTTP {status}")
        try:
            data = json.loads(text)
            used = data.get("usage") if isinstance(data, dict) else None
            if isinstance(used, dict):  # billed even if the answers turn out unusable
                self.last_usage = {k: used[k] for k in ("input_tokens", "output_tokens") if _num(used.get(k)) is not None}
            answers = data["answers"]
            level_ans = answers["level"]
        except (ValueError, KeyError, TypeError) as exc:
            raise BackendOutputError("jev response missing answers.level") from exc
        if not isinstance(level_ans, dict):
            raise BackendOutputError("jev level answer is not an object")
        level, dist = _level_and_dist(level_ans)
        conf = _num(level_ans.get("confidence"))
        scores = {f: _risk(answers, f) for f in RISK_FLAGS}
        self.last_risk_scores = scores
        flags = tuple(f for f in RISK_FLAGS if scores[f] >= RISK_THRESHOLDS.get(f, RISK_THRESHOLD))
        resp_model = data.get("model")
        codes = ("jev",) + ((resp_model,) if isinstance(resp_model, str) else ())
        return DifficultyDecision(
            level, self.name, confidence=conf if conf is not None and 0 <= conf <= 1 else None,
            distribution=dist, reason_codes=codes, risk_flags=flags)
