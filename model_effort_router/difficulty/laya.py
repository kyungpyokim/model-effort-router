"""Laya local SystemOne classifier. Configure via difficulty.laya, then MER_LAYA_* env vars."""

from .. import prompts
from .jev import QUESTIONS, SystemOneBackend
from .nimble import check_local_url, local_transport, validate_options as validate_local_options

DEFAULT_URL = "http://127.0.0.1:8000/v1/systemone"
DEFAULT_MODEL = "laya"
MODEL_ENV, URL_ENV, KEY_ENV = "MER_LAYA_MODEL", "MER_LAYA_URL", "MER_LAYA_API_KEY"

# Ollama MLX rejects instructions outside the checkpoint's question budget instead of clipping them,
# so these are shorter than Jev's (prompts/laya_instructions.json).
_INSTRUCTIONS_DOC = prompts.data("laya_instructions")
_CONTEXT_RULE = _INSTRUCTIONS_DOC["context_rule"]
_INSTRUCTIONS = prompts.fill(_INSTRUCTIONS_DOC["instructions"], context_rule=_CONTEXT_RULE)


def validate_options(raw):
    return validate_local_options(raw, "laya")


class LayaBackend(SystemOneBackend):
    name = "laya"
    questions = {name: {**question, "instructions": _INSTRUCTIONS[name]} for name, question in QUESTIONS.items()}

    def __init__(self, transport=local_transport, model=None, env=None, options=None, **kwargs):
        super().__init__(transport, model, env, **kwargs)
        self._options = validate_options({} if options is None else options)

    def _endpoint(self, env):
        url = check_local_url(self._options.get("url") or env.get(URL_ENV) or DEFAULT_URL, self.name)
        headers = {"Content-Type": "application/json"}
        key = self._api_key or env.get(KEY_ENV)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        model = self._model or self._options.get("model") or env.get(MODEL_ENV) or DEFAULT_MODEL
        return url, headers, model
