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

RISK_TIERS = ("standard", "elevated", "critical")

TIER_LEVEL = "L5"

EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")

TASK_TYPES = ("implementation", "design", "review", "inspect", "local_refactoring", "architectural_refactoring")

RISK_FLAGS = (
    "security_sensitive",
    "authentication",
    "authorization",
    "payment",
    "data_migration",
    "public_api_change",
)

SECURITY_FLOOR_FLAGS = ("security_sensitive", "authentication", "authorization", "payment")

CODE_CHANGE_TASK_TYPES = ("implementation", "local_refactoring", "architectural_refactoring")

YES_NO = ("yes", "no")

YES_NO_UNKNOWN = ("yes", "no", "unknown")

CRITICAL_SECURITY_DOMAINS = ("payment", "crypto", "auth", "permissions", "pii")

# security_domain_critical's bare-mention floor: auth is excluded. Naming the auth domain alone (no confirmed
# change, no reviewed sensitive code) is not itself a critical-impact signal -- a vague "fix the login problem"
# plausibly touches auth without being high-impact work. Payment, crypto, permissions and pii keep the floor: a
# wrong judgement there costs as much even when nothing is confirmed changed yet (see reviews_security_sensitive_code
# and changes_security_or_payment_logic below for how a confirmed auth change or review still reaches L4/elevated).
BARE_DOMAIN_FLOOR_DOMAINS = ("payment", "crypto", "permissions", "pii")

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
    # Never changes the level: it only picks the implementer rung inside L2 (see refinements in the config).
    "requires_code_understanding": YES_NO_UNKNOWN,
}

OPTIONAL_FACT_DEFAULTS = {"requires_code_understanding": "unknown"}

DIFFICULTY_RULES = (
    ("critical", "irreversible_or_ledger_or_crypto", {"irreversible_or_ledger_or_crypto": ("yes",)}),
    # The elevated tier follows the impact of a wrong judgement, never task_type.
    # needs_new_structure is a design-difficulty signal; it is elevated only across
    # services with an open result, or (through the trust-boundary rule) in a critical domain.
    ("elevated", "new_structure_across_services_with_open_result",
     {"needs_new_structure": ("yes",), "crosses_service_boundary": ("yes",), "fix_or_result_known": ("no",)}),
    ("elevated", "critical_domain_trust_boundary",
     {"security_domain": CRITICAL_SECURITY_DOMAINS, "changes_trust_boundary": ("yes",)}),
    ("elevated", "changes_security_or_payment_logic", {"changes_security_or_payment_logic": ("yes",)}),
    ("elevated", "intermittent_across_services", {"intermittent_or_concurrency": ("yes",), "crosses_service_boundary": ("yes",)}),
    # Both must be confirmed: a broad reach alone, or a silent failure alone, is not enough.
    ("elevated", "broad_blast_radius_with_silent_harm", {"blast_radius": ("broad",), "silent_failure_material_harm": ("yes",)}),
    # Security floors follow the impact of a wrong judgement, not whether code changes.
    ("L5", "security_domain_critical", {"security_domain": BARE_DOMAIN_FLOOR_DOMAINS}),
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

READ_ONLY_TASK_TYPES = ("design", "review", "inspect")


def normalise_level(level: str) -> str:
    value = level.upper()
    if value not in LEVELS:
        raise ValueError(f"level must be one of {', '.join(LEVELS)}; got {level!r}")
    return value

def normalise_task_type(task_type: str) -> str:
    if task_type not in TASK_TYPES:
        raise ValueError(f"task type must be one of {', '.join(TASK_TYPES)}; got {task_type!r}")
    return task_type

def higher_level(a: str, b: str) -> str:
    return a if int(a[1:]) >= int(b[1:]) else b

def higher_tier(a: str, b: str) -> str:
    return a if RISK_TIERS.index(a) >= RISK_TIERS.index(b) else b

def raise_effort(current: str | None, floor: str) -> str:
    """The higher of two efforts; an unset effort takes the floor."""
    if current not in EFFORT_ORDER:
        return floor
    return current if EFFORT_ORDER.index(current) >= EFFORT_ORDER.index(floor) else floor

def risk_flags_from_facts(facts: dict[str, str]) -> dict[str, bool]:
    flags = {flag: False for flag in RISK_FLAGS}
    flags["security_sensitive"] = facts["changes_security_or_payment_logic"] == "yes"
    flags["data_migration"] = facts["changes_persisted_data"] == "yes"
    flags["public_api_change"] = facts["changes_public_api_contract"] == "yes"
    return flags

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

def apply_risk_escalation(level: str, risk_tier: str, risk_flags: dict[str, bool]) -> tuple[str, str]:
    """Security flags force the elevated tier (L5); data migration and public API changes an L4 floor.

    Facts-based classifications already reach these floors through DIFFICULTY_RULES;
    this keeps them for manual and pinned classifications that carry flags."""
    if any(risk_flags.get(flag) for flag in SECURITY_FLOOR_FLAGS):
        risk_tier = higher_tier(risk_tier, "elevated")
    elif any(risk_flags.get(flag) for flag in RISK_FLAGS):
        level = higher_level(level, "L4")
    if risk_tier != "standard":
        level = higher_level(level, TIER_LEVEL)
    return level, risk_tier
