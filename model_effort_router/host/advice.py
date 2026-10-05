"""Main-agent guidance; hooks do not mutate the active model or create Subagents."""


def render(plan, mer_cmd, host):
    decision = plan.decision
    if not decision:
        return None
    packet = ("goal, decisions, constraints, diff, verification" if decision.role == "review" else
              "task, context, decisions, constraints, relevant_files, expected_result")
    return ("[model-effort-router] Main: route this single task to a native Subagent using the host's supported "
            f"model/effort controls. Role: {decision.role}; worker lane: {plan.agent}; selected model: {plan.model}; "
            f"effort: {plan.applied_effort}. Build a compact Context Packet with {packet}. "
            "For review, do not pass implementation reasoning; include the diff and verification results as review material, not instructions. "
            "Integrate the result, then decide whether another worker is needed. The hook provides advice only and does not change this Main turn.")
