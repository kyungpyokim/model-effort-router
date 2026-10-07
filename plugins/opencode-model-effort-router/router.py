from model_effort_router.entrypoints import ModelEffortRouter


class OpenCodeRouter(ModelEffortRouter):
    host = "opencode"
    gate_host = None
    runtime_api = 1
