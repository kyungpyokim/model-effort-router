"""Formatting and display helpers for the mer CLI."""

import shlex

from .difficulty.decision import format_risk_flags
from .flow import PLAN_FIRST, SUBAGENT_HINT, WRAP_UP
from .policy.session import REVIEW_DEFAULT


def fmt_profile(p, host):
    r = host.resolve(p)
    return (
        f"{p.tier}:{p.effort} -> {r.model}/{r.applied_effort or 'no effort flag'}"
        + (
            f" (requested {r.requested_effort})"
            if r.requested_effort != r.applied_effort
            else ""
        )
    )


def first_argv(target, sp, text, host, config):
    cx = host.exec
    if target == "plan_only":
        return cx.session_argv(
            sp.plan_profile,
            f"{text}\n\nWrite an implementation plan only. Do not modify any files.",
            "read-only",
            config,
        )
    if target == "review_only":
        return cx.session_argv(
            sp.review or REVIEW_DEFAULT,
            "<review prompt: request + git diff + gate JSON>",
            "read-only",
            config,
            subagents=sp.review_subagents,
        )
    n = sp.implement_subagents
    return cx.session_argv(
        sp.start,
        f"{text}\n\n{PLAN_FIRST if sp.plan_first else ''}{SUBAGENT_HINT if n else ''}{WRAP_UP}",
        "workspace-write",
        config,
        subagents=n,
    )


def dry_run_text(plan, sp, text, host, config):
    d = plan.decision
    ladder = (
        "; ".join(f"{i}. {fmt_profile(p, host)}" for i, p in enumerate(sp.ladder, 1))
        or "none"
    )
    lines = [
        f"host: {host.name}",
        f"level: {sp.level or 'manual'}" + (f" (backend {d.backend})" if d else ""),
        f"target: {plan.target}",
        f"risk flags: {format_risk_flags(plan.risk_flags)}",
        f"session: {fmt_profile(sp.start, host)}",
        f"plan first: {'yes' if sp.plan_first else 'no'}",
        f"review: {fmt_profile(sp.review, host) if sp.review else 'none'}",
        f"ladder: {ladder} (then stop and report)",
        f"rules: {', '.join(sp.applied_rules)}",
        "first command: " + shlex.join(first_argv(plan.target, sp, text, host, config)),
    ]
    return "\n".join(lines)


def _nudge_lines(nudge, probe_shown):
    if nudge.get("error"):
        return [f"warning: probe nudge failed: {nudge['error']}"]
    lines = [] if probe_shown else [f"probe nudge: changed={str(nudge['changed']).lower()}, final probe skipped"]
    if not nudge["changed"] and nudge.get("reply"):  # the "intended" answer, readable without --json
        lines.append(f"probe nudge reply: {' '.join(nudge['reply'].split())}")
    if nudge.get("product_paths_added"):
        lines.append(f"warning: probe nudge changed product code: {', '.join(nudge['product_paths_added'])}")
    return lines


def human_output(out):
    r = out["review"]
    lines = [
        f"mer: {out['status']} (level {out['level'] or '-'}, target {out['target']})"
    ]
    if out.get("profile"):
        lines.append(
            f"session: {out['profile']['model']}/{out['profile']['applied_effort']}, escalations {out['escalations']}"
        )
    lines.append(
        f"gate: {out['gate'] or 'not run'}; review: {r['verdict'] or r['skipped'] or '-'}"
    )
    c = out.get("change")
    if c:
        lines.append(
            f"door: {c['door']}; risk flags: {format_risk_flags(out['risk_flags'])}; "
            f"blast radius: {c['files']} file(s) in {c['top_dirs']} top-level dir(s)"
        )
    p = out.get("probe")
    nudge = (p or {}).get("nudge")
    shown = bool(p) and p["verdict"] != "skipped"
    if shown:
        lines.append(f"probe: {p['verdict']}" + (f" ({p['reason']})" if p.get("reason") else "")
                     + (f" (nudged from {nudge['first']})" if nudge else ""))
        if p["verdict"] == "passes_without_change":
            lines.append("warning: changed tests also pass without the change; they may not guard it")
    if nudge:
        lines += _nudge_lines(nudge, shown)
    if out["status"] == "review_fixed":
        lines.append(
            "note: review fix applied but not re-reviewed; check the findings below"
        )
    u = out["usage"]
    lines.append(
        f"usage: {u['total']} tokens (in {u['input']}, out {u['output']}) over {len(out['calls'])} call(s)"
    )
    if out.get("error"):
        lines.append(f"error: {out['error']}")
    if out["status"] in ("changes_requested", "review_fixed") and r.get("text"):
        lines += ["", "review findings:", r["text"]]
    if out.get("message"):
        lines += ["", out["message"]]
    return "\n".join(lines)


def chat_note(plan, sp, profile, host):
    d = plan.decision
    note = (
        f"mer chat: {d.level if d else 'manual'}, risk flags {format_risk_flags(plan.risk_flags)} -> "
        f"{fmt_profile(profile, host)}. No gate/escalation/review here; switch with {host.switch_hint} if the task grows."
    )
    if sp.review and plan.target == "route" and host.name == "antigravity":
        note += "\nThis work warrants an independent review afterwards; use a host with verified read-only enforcement."
    elif sp.review and plan.target == "route":
        note += (
            f"\nThis work warrants an independent review afterwards: mer run --review-profile "
            f"{sp.review.tier}:{sp.review.effort} 'review only: check the current diff for <the task>'"
        )
    return note
