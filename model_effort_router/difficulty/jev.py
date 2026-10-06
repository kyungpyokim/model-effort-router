"""TypeSafe `systemone` classifier using a direct role/effort contract."""
import json
import os
import threading
import urllib.error
import urllib.request

from .decision import DifficultyDecision, DifficultyInput
from .subscription import MAX_PATHS, MAX_TASK_CHARS, BackendOutputError

URL = "https://api.typesafe.ai/v1/systemone"
KEY_ENV = "TYPESAFE_API_KEY"
MODEL_ENV = "MER_JEV_MODEL"
DEFAULT_MODEL = "jev-latest"


class MissingKeyError(RuntimeError):
    pass


QUESTIONS = {
    "role": {"type": "choice", "instructions": (
        "Which single role best describes the main deliverable of the request? "
        "Judge the requested output, not keywords in the text."
    ), "criteria": {
        "implementation": "Add new behavior or a feature.",
        "fix": "Repair a bug or failure in existing behavior.",
        "lint": "Fix only spelling, typos, formatting, style, or static-analysis issues such as unused imports.",
        "test": "Writing, changing, or running tests is the main goal.",
        "plan": "Produce a plan for work before executing it.",
        "design": "A structure, interface, or architecture proposal is the requested deliverable.",
        "review": "Inspect existing changes or code and report findings without modifying them.",
        "analysis": ("Explain causes or behavior, or answer in chat only (translation, wording, naming, "
                     "or a short message) without implementing or editing project files."),
    }},
    "effort": {"type": "choice", "instructions": (
        "Choose the reasoning effort from how hard the decisions are, not from how much code "
        "must be read. Judge it independently of role, file count, or keywords: planning or "
        "reviewing a change needs the same effort as making it."
    ), "criteria": {
        "low": ("One function, option, or explanation is involved and the request states or clearly "
                "implies the approach, even if that code must be read first."),
        "medium": ("Existing parts are connected or changed by established patterns, edge cases need "
                   "judgment, or missing details must be gathered before deciding."),
        "high": ("Correctness depends on interacting guarantees such as concurrency, consistency, "
                 "compatibility, or security, or real design tradeoffs or uncertain diagnosis remain."),
        "xhigh": ("Rare timing-dependent failures across several subsystems, or changes where a mistake "
                  "would corrupt or lose production data, bypass security, or cause irreversible harm."),
    }},
}


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_RefuseRedirect)


def _post(url, headers, body, timeout_s, opener=None):
    plain = {k: v for k, v in headers.items() if k.lower() != "authorization"}
    req = urllib.request.Request(url, data=body, headers=plain, method="POST")
    if "Authorization" in headers:
        req.add_unredirected_header("Authorization", headers["Authorization"])
    try:
        with (opener or _OPENER).open(req, timeout=timeout_s) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def default_transport(url, headers, body, timeout_s, opener=None):
    out = {}
    def call():
        try:
            out["ok"] = _post(url, headers, body, timeout_s, opener)
        except Exception as exc:
            out["err"] = exc
    worker = threading.Thread(target=call, daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        raise TimeoutError(f"systemone request exceeded {timeout_s}s")
    if "err" in out:
        raise out["err"]
    return out["ok"]


def parse_decision(data, backend):
    if not isinstance(data, dict):
        raise BackendOutputError("classifier response is not an object")
    try:
        return DifficultyDecision(role=data["role"], effort=data["effort"], backend=backend,
                                  confidence=data.get("confidence"), reason_code=data.get("reason_code"))
    except (KeyError, TypeError, ValueError) as exc:
        raise BackendOutputError(f"{backend} returned an invalid role/effort decision") from exc


class SystemOneBackend:
    name = None
    calls_model = True

    def __init__(self, transport=default_transport, model=None, env=None, api_key=None, **_):
        self._transport, self._model, self._env, self._api_key = transport, model, env, api_key
        self.last_usage = None

    def _endpoint(self, env):
        raise NotImplementedError

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = None
        env = os.environ if self._env is None else self._env
        url, headers, model = self._endpoint(env)
        paths = "\n".join(task.paths[:MAX_PATHS]) or "(none)"
        body = json.dumps({"state": f"Task:\n{task.task[:MAX_TASK_CHARS]}\n\nRelevant paths:\n{paths}",
                           "model": model, "questions": QUESTIONS}).encode()
        status, text = self._transport(url, headers, body, timeout_s)
        if not 200 <= status < 300:
            raise RuntimeError(f"{self.name} HTTP {status}")
        try:
            data = json.loads(text)
            used = data.get("usage")
            if isinstance(used, dict):
                self.last_usage = {k: v for k, v in used.items() if k in ("input_tokens", "output_tokens")
                                   and isinstance(v, int) and not isinstance(v, bool) and v >= 0}
            answers = data["answers"]
            parsed = {key: answers[key].get("choice") for key in ("role", "effort")}
            confidence = answers["role"].get("confidence") if isinstance(answers["role"], dict) else None
            if confidence is not None:
                parsed["confidence"] = confidence
            return parse_decision(parsed, self.name)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if isinstance(exc, BackendOutputError):
                raise
            raise BackendOutputError(f"{self.name} response missing role/effort answers") from exc


class JevBackend(SystemOneBackend):
    name = "jev"

    def _endpoint(self, env):
        key = self._api_key or env.get(KEY_ENV)
        if not key:
            raise MissingKeyError(f"{KEY_ENV} is not set")
        return URL, {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, \
            self._model or env.get(MODEL_ENV) or DEFAULT_MODEL
