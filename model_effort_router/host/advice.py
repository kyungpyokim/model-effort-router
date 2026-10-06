"""Main-agent guidance; hooks do not mutate the active model or create Subagents."""


def render(plan, mer_cmd, host):
    decision = plan.decision
    if not decision:
        return None
    is_review = decision.role == "review"
    packet = ("goal, decisions, constraints, actual diff, verification status/results" if is_review else
              "task, context, decisions, constraints, relevant_files, expected_result")
    handoff = (
        "Use facts from the current request and relevant conversation to populate the packet, label unknowns, and include the completed packet directly in the host-native Subagent invocation. "
        "Do not forward the full conversation or private reasoning. "
    )
    if is_review:
        handoff += (
            "Mark checks that were not run as not run. Ask the review Subagent to inspect the diff, fix actionable findings, run relevant verification, and report changes and unresolved issues. "
        )
    return ("[model-effort-router] Main: route this single task to a native Subagent using the host's supported "
            f"model/effort controls. Role: {decision.role}; worker lane: {plan.agent}; selected model: {plan.model}; "
            f"effort: {plan.applied_effort}. Build a compact Context Packet with {packet}. {handoff}"
            "Integrate the result, then decide whether another worker is needed. The hook provides advice only; it does not inspect Main's conversation or invoke the Subagent, and does not change this Main turn's model/settings.")
