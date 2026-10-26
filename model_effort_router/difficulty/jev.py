"""TypeSafe `systemone` classifier using a direct role/effort contract."""

import http.client
import json
import os
import re
import threading
import unicodedata
import urllib.error
import urllib.request

from .. import prompts
from .chain import HttpStatusError
from .decision import TARGETS, DifficultyDecision, DifficultyInput
from .subscription import MAX_PATHS, MAX_TASK_CHARS, BackendOutputError

URL = "https://api.typesafe.ai/v1/systemone"
KEY_ENV = "TYPESAFE_API_KEY"
MODEL_ENV = "MER_JEV_MODEL"
DEFAULT_MODEL = "jev-latest"


class MissingKeyError(RuntimeError):
    pass


# The classifier questions live in prompts/jev_questions.json; every instruction ends with the shared context rule.
_QUESTIONS_DOC = prompts.data("jev_questions")
CONTEXT_RULE = _QUESTIONS_DOC["context_rule"]
QUESTIONS = prompts.fill(_QUESTIONS_DOC["questions"], context_rule=CONTEXT_RULE)
# Asked only by backends with `provides_target` (JevBackend); Nimble's target accuracy is unmeasured.
TARGET_QUESTION = prompts.fill(_QUESTIONS_DOC["target"], context_rule=CONTEXT_RULE)


def state_text(task):
    paths = "\n".join(task.paths[:MAX_PATHS]) or "(none)"
    project = f"Active project:\n{task.repo_summary[:MAX_TASK_CHARS]}\n\n" if task.repo_summary else ""
    head = f"Session context:\n{task.context}\n\nCurrent request:\n" if task.context else "Task:\n"
    return f"{project}{head}{task.task[:MAX_TASK_CHARS]}\n\nRelevant paths:\n{paths}"


class _RefuseRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "redirect refused", headers, fp)


_OPENER = urllib.request.build_opener(_RefuseRedirect)
_SAFE_ERROR_VALUE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,79}\Z")
_SENSITIVE_LABEL = re.compile(
    r"(?i)(?<![a-z0-9_])((?:\\?[\"'])?(?:[a-z0-9_.-]+[_-])?(?:api[\s_-]*key|private[\s_-]*key|client[\s_-]*secret|"
    r"access[_-]?token|refresh[_-]?token|authorization|password|secret|credential|token|key)(?:\s+provided)?(?:\\?[\"'])?\s*[:=]).*"
)
_AUTH_VALUE = re.compile(r"(?i)\b(?:Basic|Bearer)\s+\S+")
_TOKEN_VALUE = re.compile(r"(?i)\b(?:sk|pk|rk|xox[baprs])[-_][A-Za-z0-9_-]{8,}\b")
_DIAGNOSTIC_CHARS = 240


def _sensitive_key(key):
    key = "".join(char for char in str(key) if unicodedata.category(char) not in {"Cc", "Cf"})
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).lower()
    parts = set(re.split(r"[^a-z0-9]+", normalized))
    compact = normalized.replace("_", "")
    return bool(parts & {"key", "token", "password", "secret", "credential", "authorization"}) or any(
        label in compact for label in ("apikey", "privatekey", "clientsecret", "accesstoken", "refreshtoken")
    )


def _redact_diagnostic(value, secrets):
    if isinstance(value, dict):
        return {
            _redact_diagnostic(key, secrets): "[REDACTED]" if _sensitive_key(key) else _redact_diagnostic(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_diagnostic(item, secrets) for item in value]
    if not isinstance(value, str):
        return value
    value = value.encode("utf-8", "replace").decode("utf-8")
    value = "".join(
        " " if char.isspace() else "" if unicodedata.category(char) in {"Cc", "Cf"} else char for char in value
    )
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = _AUTH_VALUE.sub("[REDACTED]", value)
    value = _TOKEN_VALUE.sub("[REDACTED]", value)
    value = " ".join(value.split())
    value = _SENSITIVE_LABEL.sub(r"\1[REDACTED]", value)
    return value


def _diagnostic_excerpt(value, secrets=()):
    try:
        value = _redact_diagnostic(value, secrets)
        if not isinstance(value, str):
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (RecursionError, TypeError, ValueError):
        return "unserializable"
    value = " ".join(value.split())
    return value[:_DIAGNOSTIC_CHARS]


def _error_diagnostics(text, secrets=()):
    """Keep bounded provider error details with structured and common-credential redaction."""
    if not text:
        return "body=empty"
    try:
        payload = json.loads(text)
    except RecursionError:
        return f"body=json_too_deep; detail={_diagnostic_excerpt(text, secrets)}"
    except (TypeError, ValueError) as exc:
        return f"body=invalid_json:{type(exc).__name__}; detail={_diagnostic_excerpt(text, secrets)}"
    if not isinstance(payload, dict):
        return f"body=non_object:{type(payload).__name__}; detail={_diagnostic_excerpt(payload, secrets)}"
    error = payload.get("error", payload)
    if not isinstance(error, dict):
        return f"error=non_object:{type(error).__name__}; detail={_diagnostic_excerpt(error, secrets)}"
    fields = []
    for key in ("code", "type", "param"):
        value = error.get(key)
        if isinstance(value, str) and _SAFE_ERROR_VALUE.fullmatch(value):
            fields.append(f"{key}={_diagnostic_excerpt(value, secrets)}")
    message = error.get("message")
    if isinstance(message, str) and message:
        fields.append(f"message={_diagnostic_excerpt(message, secrets)}")
    return "; ".join(fields) or f"error=no_safe_identifiers; detail={_diagnostic_excerpt(error, secrets)}"


def _post(url, headers, body, timeout_s, opener=None):
    plain = {k: v for k, v in headers.items() if k.lower() != "authorization"}
    req = urllib.request.Request(url, data=body, headers=plain, method="POST")
    if "Authorization" in headers:
        req.add_unredirected_header("Authorization", headers["Authorization"])
    try:
        with (opener or _OPENER).open(req, timeout=timeout_s) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        try:
            text = exc.read(16_384).decode("utf-8", "replace")
        except (OSError, http.client.HTTPException):
            text = ""
        finally:
            try:
                exc.close()
            except OSError:
                pass  # body-read failure must not hide the received status
        return exc.code, text


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
        return DifficultyDecision(
            role=data["role"],
            effort=data["effort"],
            tier=data.get("tier"),
            backend=backend,
            confidence=data.get("confidence"),
            reason_code=data.get("reason_code"),
            target=data.get("target"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise BackendOutputError(f"{backend} returned an invalid role/effort decision") from exc


class SystemOneBackend:
    name = None
    calls_model = True
    provides_target = False
    questions = QUESTIONS

    def __init__(self, transport=default_transport, model=None, env=None, api_key=None, **_):
        self._transport, self._model, self._env, self._api_key = transport, model, env, api_key
        self.last_usage = None

    def _endpoint(self, env):
        raise NotImplementedError

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = None
        env = os.environ if self._env is None else self._env
        url, headers, model = self._endpoint(env)
        questions = {**self.questions, "target": TARGET_QUESTION} if self.provides_target else self.questions
        body = json.dumps({"state": state_text(task), "model": model, "questions": questions}).encode()
        status, text = self._transport(url, headers, body, timeout_s)
        if not 200 <= status < 300:
            secrets = [value for key, value in headers.items() if _sensitive_key(key)]
            secrets.extend(value.split()[-1] for value in secrets if len(value.split()) > 1)
            raise HttpStatusError(self.name, status, _error_diagnostics(text, secrets))
        try:
            data = json.loads(text)
            used = data.get("usage")
            if isinstance(used, dict):
                self.last_usage = {
                    k: v
                    for k, v in used.items()
                    if k in ("input_tokens", "output_tokens")
                    and isinstance(v, int)
                    and not isinstance(v, bool)
                    and v >= 0
                }
            answers = data["answers"]
            parsed = {key: answers[key].get("choice") for key in ("role", "effort") if key in answers}
            if "tier" in answers and isinstance(answers["tier"], dict):
                parsed["tier"] = answers["tier"].get("choice")
            if self.provides_target:
                target = answers["target"].get("choice")
                if target not in TARGETS:
                    raise BackendOutputError(f"{self.name} target answer is missing or not one of the offered choices")
                parsed["target"] = target
            confidence = answers["role"].get("confidence") if isinstance(answers["role"], dict) else None
            if confidence is not None:
                parsed["confidence"] = confidence
            return parse_decision(parsed, self.name)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if isinstance(exc, BackendOutputError):
                raise
            raise BackendOutputError(f"{self.name} response missing role/effort/target answers") from exc


class JevBackend(SystemOneBackend):
    name = "jev"
    provides_target = True  # its decision carries the routing target; the router asks it first

    def _endpoint(self, env):
        key = self._api_key or env.get(KEY_ENV)
        if not key:
            raise MissingKeyError(f"{KEY_ENV} is not set")
        return (
            URL,
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            self._model or env.get(MODEL_ENV) or DEFAULT_MODEL,
        )
