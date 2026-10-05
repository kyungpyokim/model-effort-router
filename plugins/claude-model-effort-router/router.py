from model_effort_router.entrypoints import ModelEffortRouter


class ClaudeRouter(ModelEffortRouter):
    host = "claude"
    gate_host = "claude"
    runtime_api = 1
