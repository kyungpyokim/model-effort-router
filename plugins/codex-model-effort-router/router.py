from model_effort_router.entrypoints import ModelEffortRouter


class CodexRouter(ModelEffortRouter):
    host = "codex"
    gate_host = "codex"
    runtime_api = 1
