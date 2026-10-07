"""OpenAI Decisions API role/effort classifier."""

import json
import os

from .decision import DifficultyDecision, DifficultyInput
from .jev import default_transport, parse_decision, state_text
from .jev import QUESTIONS as SYSTEMONE_QUESTIONS
from .subscription import BackendOutputError

URL = "https://api.openai.com/v1/decisions"
KEY_ENV = "OPENAI_API_KEY"
DEFAULT_MODEL = "gpt-6-luna"

QUESTIONS = [
    {
        "name": name,
        "type": "choice",
        "instructions": question["instructions"],
        "choices": [
            {"value": value, "description": description}
            for value, description in question["criteria"].items()
        ],
    }
    for name, question in SYSTEMONE_QUESTIONS.items()
]


class OpenAIDecisionsBackend:
    name = "openai_decisions"
    calls_model = True

    def __init__(self, transport=default_transport, env=None, api_key=None, model=None):
        self._transport = transport
        self._env = env
        self._api_key = api_key
        self._model = model
        self.last_usage = None

    def classify(self, task: DifficultyInput, timeout_s: float) -> DifficultyDecision:
        self.last_usage = None
        env = os.environ if self._env is None else self._env
        key = self._api_key or env.get(KEY_ENV)
        if not key:
            raise RuntimeError(f"{KEY_ENV} is not set")
        body = json.dumps(
            {
                "model": self._model or DEFAULT_MODEL,
                "input": state_text(task),
                "questions": QUESTIONS,
            }
        ).encode()
        status, text = self._transport(
            URL,
            {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            body,
            timeout_s,
        )
        if not 200 <= status < 300:
            raise RuntimeError(f"{self.name} HTTP {status}")
        try:
            data = json.loads(text)
            usage = data.get("usage")
            if isinstance(usage, dict):
                self.last_usage = {
                    k: v
                    for k, v in usage.items()
                    if k in ("input_tokens", "output_tokens")
                    and isinstance(v, int)
                    and not isinstance(v, bool)
                    and v >= 0
                }
            answers = data["answers"]
            if not isinstance(answers, list):
                raise TypeError("answers must be an array")
            by_name = {}
            for answer in answers:
                if not isinstance(answer, dict) or answer.get("name") not in (
                    "role",
                    "effort",
                ):
                    raise TypeError("invalid answer")
                name = answer["name"]
                if name in by_name or answer.get("type") != "choice":
                    raise TypeError("duplicate or non-choice answer")
                by_name[name] = answer
            parsed = {name: by_name[name]["choice"] for name in SYSTEMONE_QUESTIONS}
            confidence = by_name["role"].get("confidence")
            if confidence is not None:
                parsed["confidence"] = confidence
            return parse_decision(parsed, self.name)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            if isinstance(exc, BackendOutputError):
                raise
            raise BackendOutputError(
                f"{self.name} response missing role/effort answers"
            ) from exc
