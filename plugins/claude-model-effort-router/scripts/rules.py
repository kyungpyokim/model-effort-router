"""Difficulty, risk tiers, and rule evaluation for the model-effort router."""

from __future__ import annotations

LEVELS = ("L1", "L2", "L3", "L4", "L5")
LEVEL_NAMES = {
    "L1": "trivial",
    "L2": "simple",
    "L3": "standard",
    "L4": "complex",
    "L5": "advanced",
}
# Risk tiers raise the reasoning effort of the planning/judging stage at L5 (or swap
# an Antigravity model); they are not levels. Both non-standard tiers imply L5.
# "normal" and "standard" are treated equivalently as baseline risk tier.
RISK_TIERS = ("standard", "elevated", "critical")
TIER_LEVEL = "L5"
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
TASK_TYPES = ("implementation", "design", "review", "local_refactoring", "architectural_refactoring")
CODE_CHANGE_TASK_TYPES = ("implementation", "local_refactoring", "architectural_refactoring")
READ_ONLY_TASK_TYPES = ("design", "review")
RISK_FLAGS = (
    "security_sensitive",
    "authentication",
    "authorization",
    "payment",
    "data_migration",
    "public_api_change",
)
SECURITY_FLOOR_FLAGS = ("security_sensitive", "authentication", "authorization", "payment")

YES_NO = ("yes", "no")
YES_NO_UNKNOWN = ("yes", "no", "unknown")
CRITICAL_SECURITY_DOMAINS = ("payment", "crypto", "auth", "permissions", "pii")
SECURITY_DOMAINS = ("none", "auth", "payment", "secrets", "crypto", "permissions", "pii", "unknown")

FACTS = {
    "mechanical_only": YES_NO,
    "files_touched": ("0", "1", "2-5", "6+", "unknown"),
    "crosses_module_boundary": YES_NO_UNKNOWN,
    "crosses_service_boundary": YES_NO_UNKNOWN,
    "fix_or_result_known": YES_NO,
    "intermittent_or_concurrency": YES_NO_UNKNOWN,
    "needs_new_structure": YES_NO,
    "changes_security_or_payment_logic": YES_NO_UNKNOWN,
    "reviews_security_sensitive_code": YES_NO_UNKNOWN,
    "security_domain": SECURITY_DOMAINS,
    "changes_public_api_contract": YES_NO_UNKNOWN,
    "changes_persisted_data": YES_NO_UNKNOWN,
    "irreversible_or_ledger_or_crypto": YES_NO_UNKNOWN,
    "changes_trust_boundary": YES_NO_UNKNOWN,
    "blast_radius": ("narrow", "broad", "unknown"),
    "silent_failure_material_harm": YES_NO_UNKNOWN,
    "requires_code_understanding": YES_NO_UNKNOWN,
}

OPTIONAL_FACT_DEFAULTS = {"requires_code_understanding": "unknown"}

DIFFICULTY_RULES = (
    ("critical", "irreversible_or_ledger_or_crypto", {"irreversible_or_ledger_or_crypto": ("yes",)}),
    ("elevated", "new_structure_across_services_with_open_result",
     {"needs_new_structure": ("yes",), "crosses_service_boundary": ("yes",), "fix_or_result_known": ("no",)}),
    ("elevated", "critical_domain_trust_boundary",
     {"security_domain": CRITICAL_SECURITY_DOMAINS, "changes_trust_boundary": ("yes",)}),
    ("elevated", "changes_security_or_payment_logic", {"changes_security_or_payment_logic": ("yes",)}),
    ("elevated", "intermittent_across_services", {"intermittent_or_concurrency": ("yes",), "crosses_service_boundary": ("yes",)}),
    ("elevated", "broad_blast_radius_with_silent_harm", {"blast_radius": ("broad",), "silent_failure_material_harm": ("yes",)}),
    ("L5", "security_domain_critical", {"security_domain": CRITICAL_SECURITY_DOMAINS}),
    ("L5", "needs_new_structure", {"needs_new_structure": ("yes",)}),
    ("L5", "intermittent_or_concurrency", {"intermittent_or_concurrency": ("yes",)}),
    ("L5", "open_result_across_modules", {"fix_or_result_known": ("no",), "crosses_module_boundary": ("yes",)}),
    ("L4", "reviews_security_sensitive_code", {"reviews_security_sensitive_code": ("yes",)}),
    ("L4", "crosses_module_boundary", {"crosses_module_boundary": ("yes",)}),
    ("L4", "crosses_service_boundary", {"crosses_service_boundary": ("yes",)}),
    ("L4", "changes_public_api_contract", {"changes_public_api_contract": ("yes",)}),
    ("L4", "changes_persisted_data", {"changes_persisted_data": ("yes",)}),
    ("L4", "files_touched_6_plus", {"files_touched": ("6+",)}),
    ("L3", "files_touched_2_to_5", {"files_touched": ("2-5",)}),
    ("L3", "open_fix_or_result", {"fix_or_result_known": ("no",)}),
)


def normalise_level(level: str) -> str:
    value = level.upper()
    if value not in LEVELS:
        raise ValueError(f"unknown level: {level} (expected one of {', '.join(LEVELS)})")
    return value


def normalise_task_type(task_type: str) -> str:
    value = task_type.lower()
    if value not in TASK_TYPES:
        raise ValueError(f"unknown task_type: {task_type} (expected one of {', '.join(TASK_TYPES)})")
    return value


def normalise_tier(tier: str) -> str:
    t = tier.lower()
    if t == "normal":
        return "standard"
    if t not in RISK_TIERS:
        raise ValueError(f"unknown risk tier: {tier} (expected one of normal/standard, elevated, critical)")
    return t


def higher_level(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


def higher_tier(a: str, b: str) -> str:
    norm_a, norm_b = normalise_tier(a), normalise_tier(b)
    return norm_a if RISK_TIERS.index(norm_a) >= RISK_TIERS.index(norm_b) else norm_b


def raise_effort(current: str | None, floor: str) -> str:
    if current is None:
        return floor
    if current not in EFFORT_ORDER:
        raise ValueError(f"unknown effort: {current} (expected one of {', '.join(EFFORT_ORDER)})")
    return current if EFFORT_ORDER.index(current) >= EFFORT_ORDER.index(floor) else floor


def unknown_facts(facts: dict[str, str]) -> tuple[str, ...]:
    return tuple(name for name in FACTS if facts.get(name) == "unknown")


def unresolved_facts(facts: dict[str, str]) -> tuple[str, ...]:
    """Facts that stayed unknown and are worth a question to the user (optional facts are not)."""
    return tuple(name for name in unknown_facts(facts) if name not in OPTIONAL_FACT_DEFAULTS)


def evaluate_rules(facts: dict[str, str]) -> tuple[str, str, list[str], tuple[str, ...]]:
    """Apply DIFFICULTY_RULES: returns (level, risk tier, matched rule names, unresolved facts).

    Only explicit answers match a rule; an unknown fact never raises the level."""
    level = "L1" if facts["mechanical_only"] == "yes" else "L2"
    tier = "standard"
    matched: list[str] = []
    for rule_level, name, conditions in DIFFICULTY_RULES:
        if not all(facts[fact] in values for fact, values in conditions.items()):
            continue
        matched.append(f"{rule_level}:{name}")
        if rule_level in RISK_TIERS:
            tier = higher_tier(tier, rule_level)
            rule_level = TIER_LEVEL
        level = higher_level(level, rule_level)
    return level, tier, matched, unresolved_facts(facts)


def risk_flags_from_facts(facts: dict[str, str]) -> dict[str, bool]:
    flags = {flag: False for flag in RISK_FLAGS}
    flags["security_sensitive"] = facts["changes_security_or_payment_logic"] == "yes"
    flags["data_migration"] = facts["changes_persisted_data"] == "yes"
    flags["public_api_change"] = facts["changes_public_api_contract"] == "yes"
    return flags


def apply_risk_escalation(level: str, risk_tier: str, risk_flags: dict[str, bool]) -> tuple[str, str]:
    if any(risk_flags.get(flag) for flag in SECURITY_FLOOR_FLAGS):
        risk_tier = higher_tier(risk_tier, "elevated")
    elif any(risk_flags.get(flag) for flag in RISK_FLAGS):
        level = higher_level(level, "L4")
    if risk_tier != "standard":
        level = higher_level(level, TIER_LEVEL)
    return level, risk_tier


def is_read_only_inspect(task_type: str, facts: dict[str, str]) -> bool:
    """Read-only inspect tasks: query/analysis/explanation without code modification."""
    if task_type in READ_ONLY_TASK_TYPES and facts.get("files_touched") in ("0", ""):
        return True
    return False


def is_trivial_edit_fast_path(task_type: str, risk_tier: str, facts: dict[str, str]) -> bool:
    """Check if task satisfies all 6 Trivial Edit Fast Path criteria:
    - normal/standard risk tier
    - requires_code_understanding == no
    - mechanical_only == yes
    - files_touched in ('0', '1')
    - no module/service boundary crossing
    - no new structure needed
    - no security, payment, data migration, public API, trust boundary changes
    - narrow blast radius & no silent failure harm
    """
    if task_type not in CODE_CHANGE_TASK_TYPES:
        return False
    if normalise_tier(risk_tier) != "standard":
        return False
    if facts.get("requires_code_understanding") == "yes":
        return False
    if facts.get("mechanical_only") != "yes":
        return False
    if facts.get("files_touched") not in ("0", "1"):
        return False
    if facts.get("crosses_module_boundary") == "yes" or facts.get("crosses_service_boundary") == "yes":
        return False
    if facts.get("needs_new_structure") == "yes":
        return False
    if facts.get("changes_security_or_payment_logic") == "yes":
        return False
    if facts.get("reviews_security_sensitive_code") == "yes":
        return False
    if facts.get("security_domain") not in ("none", ""):
        return False
    if facts.get("changes_public_api_contract") == "yes":
        return False
    if facts.get("changes_persisted_data") == "yes":
        return False
    if facts.get("irreversible_or_ledger_or_crypto") == "yes":
        return False
    if facts.get("changes_trust_boundary") == "yes":
        return False
    if facts.get("blast_radius") == "broad":
        return False
    if facts.get("silent_failure_material_harm") == "yes":
        return False
    return True
