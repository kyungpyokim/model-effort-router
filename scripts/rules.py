"""Difficulty, risk tiers, and rule evaluation for the model-effort router."""

from __future__ import annotations

import json
import re

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


AMBIGUITY_GATES = ("clear", "partial", "ambiguous")

# The action vocabulary for the ambiguity gate. It is deliberately *wider* than
# route_reuse.operation()'s blocker vocabulary: that one decides whether a follow-up task changed
# the kind of work (where a false hit only costs one classification), while this one decides
# whether a request is too empty to act on (where a false miss would demand a clarification the
# user does not need). "handle", "support", "ensure", "harden" and their Korean equivalents name
# an operation here and would not count as a reuse-blocking modify verb there.
AMBIGUITY_ACTION_RE = re.compile(
    r"\b(?:"
    r"fix|implement|add|change|update|refactor|rename|remove|delete|create|write|build|patch"
    r"|handle|support|ensure|make|improve|optimi[sz]e|migrate|split|extract|consolidate|move"
    r"|clean|simplify|standardi[sz]e|replace|rewrite|extend|wire|hook|integrate|introduce"
    r"|apply|enforce|harden|secure|validate|test|debug|investigate|diagnose|analy[sz]e|cover"
    r"|reduce|increase|tune|adjust|align|document|configure|switch|drop|guard|isolate|bump"
    r"|upgrade|downgrade|port|decouple|deduplicate|abstract|general[is]+e|do|perform|purge|erase|wipe"
    r"|review|inspect|check|find|locate|trace|explain|design|plan"
    r")(?:e?s|e?d|ing)?\b"
    # Gerunds of the e-final verbs above: the base already carries the "e", so "investigating"
    # (never "investigateing") needs its own alternative, bounded so "immigrating" is not one.
    r"|\b(?:investigating|analy[sz]ing|optimi[sz]ing|migrating|isolating|configuring|deduplicating"
    r"|validating|securing|replacing|tracing|integrating|introducing|upgrading|downgrading|tuning)\b"
    r"|수정|구현|추가|변경|리팩터|리팩토링|삭제|만들|고치|고쳐|작성|개선|적용|교체|제거|바꿔|바꾸"
    r"|처리|지원|보완|강화|정리|이동|분리|추출|통합|검증|확인|분석|설계|리뷰|최적화|도입|대응|해결|업그레이드",
    re.IGNORECASE,
)

# Tokens that name a concrete target of the work: a backticked identifier, a path, a file with a
# code extension, a dotted module.symbol reference, or an identifier-shaped name (snake_case or
# camelCase). Deliberately generous: a false positive only keeps a request on the normal path,
# while a false negative can only reach `partial` (which annotates the plan) — never `ambiguous`,
# which is reserved for a request that names neither an operation nor a target.
TARGET_TOKEN_RE = re.compile(
    r"""
    `[^`\s][^`]*`                                  # `retry_policy`
    | \b[\w.-]+/[\w./-]+                           # path/to/thing
    | \b\w+\.(?:py|js|ts|tsx|jsx|java|go|rb|rs|cs|kt|swift|php|sql|json|ya?ml|toml|ini|md|sh|tf|proto)\b
    | \b\w+\.\w+                                   # module.symbol
    | \b[a-z][a-z0-9]*_[a-z0-9_]*\b                # snake_case
    | \b[A-Za-z][a-z0-9]*[A-Z]\w*\b                # camelCase or PascalCase
    """,
    re.VERBOSE,
)


def derive_ambiguity_gate(task: str, task_type: str, settled: bool = False) -> tuple[str, str]:
    """Whether the request text determines the work: ``(gate, reason)``, one of ``AMBIGUITY_GATES``.

    This gate reads the request text alone. Missing information has its own, older path --
    ``rules.unresolved_facts`` -> one bounded lookup -> a question to the user -- and is reported
    there, so an unresolved route is never also labelled ambiguous.

    The gate is an execution decision, never a difficulty one: it can annotate a plan or ask the
    user to restate the request, and it must never raise the level, the risk tier, the model, or
    the effort. Read-only routes are never gated on text shape, and a ``settled`` route is already
    clarified by its context: a human pinned the task type plus a level or ``--critical``, or chose
    the axes at the manual prompt. A reused session route is settled by its caller, and only when
    the stored record carries the ambiguity marker this phase added; a record written before it has
    no marker, so even its vague task is still asked to restate.

    ``partial`` means the request names one of the two things the work needs (an operation verb
    or a concrete target) and the planner must state its assumptions for the other. ``ambiguous``
    means it names neither, so there is nothing to assume from: the user is asked to restate.
    """
    if settled or task_type not in CODE_CHANGE_TASK_TYPES:
        return "clear", ""
    names_operation = bool(AMBIGUITY_ACTION_RE.search(task))
    names_target = bool(TARGET_TOKEN_RE.search(task))
    if names_operation and names_target:
        return "clear", ""
    if not names_operation and not names_target:
        return "ambiguous", "the request names neither an operation nor a concrete target"
    reason = "the request names no concrete target" if names_operation else "the request names no operation verb"
    return "partial", reason


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def extract_json_payload(raw: str) -> object:
    """Best-effort JSON extraction from an assessor reply.

    Tries, in order: the whole stripped reply; the last fenced ```json``` block; the
    last top-level {...} object found by scanning for '{' and decoding from there.
    Assessor replies sometimes lead with prose (occasionally containing stray '{' or
    inline backticks) before the real fenced JSON, so the last candidate of each kind
    wins over the first.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        first_error = exc
    fences = _FENCED_JSON_RE.findall(raw)
    if fences:
        try:
            return json.loads(fences[-1])
        except json.JSONDecodeError:
            pass
    decoder = json.JSONDecoder()
    last_object = None
    i = 0
    while i < len(raw):
        if raw[i] != "{":
            i += 1
            continue
        try:
            obj, end = decoder.raw_decode(raw, i)
        except json.JSONDecodeError:
            i += 1
            continue
        # Skip past this object instead of scanning inside it, so a nested dict
        # (e.g. the "facts" object) never shadows the outer, real payload.
        if isinstance(obj, dict):
            last_object = obj
        i = end
    if last_object is not None:
        return last_object
    raise first_error


_extract_json_payload = extract_json_payload

FILES_TOUCHED_CRITERIA: dict[str, str] = {
    "0": "Read-only design, review or inspect work that changes no file. An implementation that runs an operation or changes production data is never 0, even when no source file changes.",
    "1": "The task names or lists exactly one file, module, service, package, or component to change, or an actual diff or file list is available and shows exactly one.",
    "2-5": "The task names or lists 2 to 5 files, modules, services, packages, or components to change, or an actual diff or file list is available and shows that range.",
    "6+": "The task names or lists 6 or more files, modules, services, packages, or components to change, or an actual diff or file list is available and shows that many.",
    "unknown": "None of the above: the work is not read-only, and neither the task text nor an available diff or file list states how many files or which ones change. Files that are only read, checked, or named as callers are not changed files; a description of containment (in a single module, inside one component) is a scope statement, not a stated count; and a count that is only possible, candidate, potential, or proposed is not a stated count either. This is the default for a one-line task description with no file count, file list, or diff attached — pick this rather than a bucket inferred from the described scope, size, or complexity of the change.",
}

# The instructions Jev receives for files_touched. Deliberately does not ask it to estimate scope
# from complexity or wording: a bare one-line task description carries no evidence a probability
# answer can be calibrated against, and guessing from it is exactly the failure mode this contract
# exists to rule out. The CLI classifier's prompt now states the same evidence rule (a stated count,
# a named file list, a diff, or the repository reads its repo-aware pass allows), and the
# deterministic jev_provider.enforce_files_touched_contract guard backstops the escalating buckets
# on the Jev path.
FILES_TOUCHED_INSTRUCTIONS = (
    "How many files does the work change? Read-only work is 0. Otherwise, answer only from a stated "
    "count of the files, modules, services, packages, or components to change, a named file or module "
    "list, or an attached diff — never from how big, complex, or involved the described change sounds. "
    "Count only what the work changes: files that are only read, checked, or named as callers do not "
    "count, and a caution not to break them adds no files. A description of containment — in a single "
    "module, inside one component — is a scope statement, not a stated count. A count that is only "
    "possible, candidate, potential, or proposed is not a stated count either. If none of those is "
    "present, answer unknown."
)

SECURITY_DOMAIN_CRITERIA: dict[str, str] = {
    "none": "No security-sensitive area whose behaviour the work changes or whose correctness or safety it judges, or only mentioned/renamed without behaviour change. Also none when the work only judges or fixes how paths, files, URLs, network destinations, or redirects are validated or sanitized — that protects data without changing access control between principals; when the task only adds or names a user, customer, profile, or account entity, field, avatar, or similar feature without touching how personal data is accessed, exported, erased, or protected; renames, moves, extracts, or relocates code that is named after, or computes, billing, order, checkout, discount, tax, invoice, or payment amounts within one trust zone without changing the amount it computes (a move across a deployed service or trust boundary keeps its domain; extracting the same logic into another module inside the same service does not); diagnoses or fixes a rounding or precision defect in an amount calculation without moving money or rewriting the pricing, discount, or tax rule; inspects certificate expiry or lists SAN entries without designing or judging cryptography; or splits or reshapes a field such as a name without changing privacy or access handling.",
    "auth": "User authentication, login, credentials, session management.",
    "payment": "Monetary consequence, charges, refunds, ledger correctness, obligations. Not extracting, moving, or renaming such calculation logic without changing the amount charged.",
    "secrets": "API keys, tokens, secret management, encryption keys.",
    "crypto": "Cryptographic algorithms, protocols, key exchange, encryption/decryption.",
    "permissions": "Access control between principals or identities — users, roles, tenants, customers, credentials, or equivalent authorization boundaries (RBAC, tenant isolation, ACLs). Validating or sanitizing paths, files, URLs, network destinations, redirects, or other untrusted input is not a permissions change.",
    "pii": "Personal identifiable information, user data privacy.",
    "unknown": "Security area is plausibly involved but unsettled.",
}

BLAST_RADIUS_CRITERIA: dict[str, str] = {
    "narrow": "Stays within one component, feature, or a recoverable subset, as the task describes it. A single-file or single-component task is narrow even when the component matters; a hypothetical worst case is never broad.",
    "broad": "The task itself describes system-wide reach: many services, all users/tenants, production data at large, or money system-wide. Broad needs evidence in the text, not a worst case.",
    "unknown": "Cannot be settled from task text; the reach is plausibly system-wide but unsettled.",
}

# What counts as yes or no, for the facts a bare question leaves ambiguous. The wording follows
# the CLI classifier's own definitions so both providers answer the same question.
NOUL_CRITERIA: dict[str, dict[str, str]] = {
    "fix_or_result_known": {
        "true": "The expected result, or the place to change, is stated or evident, including a choice between explicitly named options. Yes means either the requested fix is already concretely identified (for example a typo, spelling, or link fix in a named file), or the inspection or search target is explicitly specified (for example inspect, check, or read a named metric, log, dashboard, or status). The observed value or root cause does not need to be known in advance. Also yes when the task names the change to make even though the exact edit is not spelled out: running a named tool or formatter; rewording or replacing user-visible text in a named place; adding tests or test coverage for a named function, file, or area; refactoring, renaming, moving, extracting, consolidating, or standardizing named code; or implementing, automating, or revamping named behaviour.",
        "false": "The goal or the candidate solutions must still be investigated or invented. A task that only names a search scope without a concrete fix or an explicitly specified check target — such as find why, track down, or locate the cause with no named place to change or check — is no. Still no when the task first has to find out what is wrong (investigate, determine, diagnose, track down, locate, or analyse an unexplained failure or an unknown root cause), when the failure is intermittent or timing-dependent, or when the task asks to design something new (a protocol, algorithm, mechanism, ledger, or architecture) rather than to make a named change.",
    },
    "crosses_module_boundary": {
        "true": "The work moves responsibilities or contracts between modules/packages, or creates/removes a module boundary. Extraction, consolidation, isolation, or split of a module boundary where the interface contract changes. NOT merely reading, using, or touching code in multiple modules. A diagnosis or investigation whose subject explicitly spans two or more independent modules, packages, or services is yes even though the work changes no code: the boundary is crossed by the defect under investigation.",
        "false": "The work stays inside one module boundary. Reading, using types from, or editing several files within the same module is false. A refactor whose boundary impact is merely uncertain is false. A single-module investigation, or an investigate, debug, or inspect task that names no second boundary, is no however unclear the cause is.",
    },
    "crosses_service_boundary": {
        "true": "The task changes behaviour, contracts, communication, or data flow across independently deployed services or processes — modifying an inter-service API, RPC or message contract, service-to-service dependency, or coordination semantics — or diagnoses a failure that spans more than one deployed process. Answer yes only when the deployed boundary itself is involved: what changes is the contract, dependency, or coordination between them, or the failure being diagnosed lies across them.",
        "false": "The task only changes modules, packages, components, or call sites within one service; merely mentions services, service files, repositories, or a build, release, or CI pipeline; changes one deployment's public API format or a name, type, or file that contains \"service\"; moves or renames code across files that ship in one deployment; or changes implementation behind an unchanged cross-service contract. A pipeline, build, or CI stage is not a deployed process, and neither is a repository.",
    },
    "requires_code_understanding": {
        "true": "Doing the work right depends on reading existing code beyond the edit site: callers or callees, existing behaviour, invariants, how state flows.",
        "false": "The edit is self-contained and evident from the task text: a new standalone helper, adding a field or parameter, a clear one-line change, a test for stated behaviour.",
    },
    "needs_new_structure": {
        "true": "A new architecture, subsystem, protocol, cross-module or cross-service boundary, or data-migration strategy must be designed or built, and the structure to decide is genuinely open: the task must decide structure it does not already name, or design and build new structure across a module or service boundary. A task that explicitly requires new structure (a new protocol, boundary, subsystem, or migration) is yes even when the direction is named.",
        "false": "The change fits inside the existing structure. Laying out files inside one new module, or moving code along a boundary the task already states, is false; so is a refactor whose boundary impact is merely uncertain. Refactoring, decoupling, isolating, extracting, splitting, or consolidating existing code into a named layer, module, or service is false even when the task introduces that layer. Revamping or rewriting an existing mechanism, implementing a mechanism whose design is already standard or specified, and diagnosing or investigating an existing failure are false. Automating an existing manual process or a named procedure — rotating or re-encrypting existing keys or data, or scripting a routine operation — is false: automating a known procedure decides no structure. An open-ended result is not enough on its own: the structure itself must be open, or new structure must be explicitly required.",
    },
    "mechanical_only": {
        "true": "Typos, formatting, comments, documentation, import sorting, a rename that stays inside one function or file, a version string or metadata edit, or deleting an unused private symbol, with no behaviour change, nothing to coordinate with other files, and no judgement.",
        "false": "A rename, move, or update that must be propagated beyond where the identifier lives: references, imports, call sites, or tests in more than one file or module, or a public, exported, or cross-file name that other code depends on. Anything needing a judgement about behaviour, including extracting or deduplicating logic, is false as well.",
    },
"silent_failure_material_harm": {
        "true": "Both are evident from the task: a mistake would go unnoticed (no error, alert, or failing test) AND it causes data loss or corruption, wrong money movement, security exposure, or cross-service inconsistency through a mechanism the task describes or necessarily implies (persisted-data write or delete, money movement, auth or access change, unchecked cross-service propagation). Code, PR, or plan review that only judges an artifact is no: the work must itself introduce, change, design, or fix behaviour — designing, implementing, fixing, or investigating is not review work.",
        "false": "A mistake produces an error, alert, or failing test, or no material-harm mechanism is described or necessarily implied. Mechanical work, refactorings, documentation, tests, cosmetic changes, and single-component fixes with visible failures are no even when touching sensitive code. Code, PR, or plan review that only judges an artifact is no even when the artifact is dangerous. A merely hypothetical worst case is no; unknown only when the area is plausibly involved but the text cannot settle it.",
    },
    "changes_public_api_contract": {
        "true": "The task explicitly changes, removes, or replaces a stable interface consumed outside the implementation boundary: a public HTTP/GraphQL request or response contract whose format, envelope, or fields are rewritten; an exported SDK/library API whose methods or parameters are renamed or removed; or a user-facing CLI command or flag whose meaning changes or that is removed (an existing flag that can no longer be passed, or now behaves differently, is a contract change, even when a security gate is the reason).",
        "false": "The task only changes internal functions, private/module interfaces, implementation details, internal call sites, refactoring structure, or behavior behind an unchanged external contract. Adding a field to a model, DTO, or dataclass is unknown, not yes, when the task does not state whether that model or its serialized shape is consumed outside the implementation boundary (dto.py or a User type does not settle it), even when the field is optional; adding a parameter, flag, option, or prompt that only adds new behavior, leaving every existing command, flag, output, and type unchanged, is additive and not a contract change; rewording user-visible text such as an error message or label is not a shape change; a database migration or column change is changes_persisted_data, not a contract change; rewriting or reviewing security logic (validation, token rotation, middleware, rate limiting) while the interface, its names, and which commands and flags exist all stay the same changes nothing external. Do not infer a public API change merely because the task mentions 'API', 'interface', 'endpoint implementation', function signatures, or a file path such as api/users.py, or because it designs or replaces an internal architecture, message bus, or service-to-service protocol.",
    },
    "changes_security_or_payment_logic": {
        "true": "The work itself changes authentication, authorization, secrets, cryptography, or payment behaviour: the task changes who may do what, or how credentials, keys, tokens, money, pricing, or settlement behave, including designing or implementing a signature, custody, settlement, or key-rotation mechanism. Answer yes only when the task itself changes that behaviour — judging or approving code that would change it is no.",
        "false": "The work itself changes nothing in that behaviour: the task only moves, splits, renames, extracts, documents, or reviews such code. This fact is about the work the task asks you to do, not about the code or change under review: review or audit work changes no behaviour itself, so reviewing or judging a security pull request — even one that alters authentication, cryptography, or payment behaviour, or that adds, removes, or retunes parameters, filters, or thresholds of such code — is no here, and is covered by reviews_security_sensitive_code and security_domain instead; extracting an auth module into its own service with the same behaviour is no here, since changes_trust_boundary judges that move separately. Purely additive tooling, or a new computational pipeline such as a key-derivation or proof-verification component or an audit log, that leaves existing credentials, keys, and payments behaving as before is no. A task that names a security area without saying what is wrong (for example \"fix the login problem\") is unknown, not yes.",
    },
    "changes_trust_boundary": {
        "true": "The work itself designs, changes, or decides where trust is established or delegated between components, services, tenants, or principals (service-to-service authentication, token propagation, permission delegation, isolation boundaries), including deciding whether to move such a boundary. Answer yes only when the task itself moves, adds, or removes such a boundary; changing behaviour inside an existing trust boundary is not deciding where trust lies.",
        "false": "The work only reviews, audits, tests, inspects, mentions, or judges such code without changing it itself: the artifact's sensitivity is not the work's. Reviewing existing boundary code — including a pull request that adds or changes a boundary, isolation, or allowlist rule — is no here and is covered by reviews_security_sensitive_code; moving code inside one trust zone is no, and so is a rename, extraction, or refactoring whose trust impact is unchanged.",
    },
    "intermittent_or_concurrency": {
        "true": "The task names a defect whose cause is concurrency or timing correctness: races, deadlocks, ordering, interleaved retries or distributed transactions, or shared-state correctness across threads, processes, or services. The defect is intermittent or timing-dependent and the task states or necessarily implies that concurrency or timing is why: an intermittent race, a deadlock, or a distributed transaction failure is yes. The concurrency cause is what makes it yes, not the word intermittent by itself.",
        "false": "Symptoms with no stated concurrency or timing cause are no: occasional slowness or a performance anomaly, an unexplained spike, a leak or inconsistency whose cause is not yet known, a test that fails intermittently in a test run, or a rate-limiting, backoff, idempotency, or retry policy. Designing or reviewing a concurrency mechanism, lock, detector, watchdog, or protocol is no even when it names deadlocks, races, or ordering: this fact is about a defect in existing behaviour, not about new machinery for handling timing.",
    },
}

# Facts the Jev SystemOne path asks as multiple-choice questions, each with its own criteria dict
# above; every other fact is asked as a noul probability that can answer only yes or no. A labelled
# "unknown" on a noul fact is unrepresentable on that path, so the live benchmark reports it as such
# instead of scoring it as a miss (see evaluate_classifier_benchmark).
CHOICE_FACTS: tuple[str, ...] = ("files_touched", "security_domain", "blast_radius")

NOUL_FACTS: tuple[str, ...] = tuple(name for name in FACTS if name not in CHOICE_FACTS)

FACT_QUESTIONS: dict[str, str] = {
    "mechanical_only": "Is this purely mechanical work with no behaviour change and nothing to coordinate — a typo, formatting, comment, documentation, or import fix, a rename that stays inside one function or file, a version string or metadata edit, or deleting an unused private symbol? A rename, move, or update that must be propagated beyond where the identifier lives is not mechanical: references, imports, call sites, or tests in more than one file or module, or a public, exported, or cross-file name that other code depends on. Anything needing a judgement about behaviour, including extracting or deduplicating logic, is no.",
    "files_touched": "How many files, modules, services, packages, or components will the work create or edit — counting new and test files, and not files only read for context: 1 only for one existing file with no separate test or new file; 2-5 for a separate test or new file or subsystem or protocol; 6+ if cross-cutting; unknown only with no scope signal (0 read-only)?",
    "crosses_module_boundary": "Does the work move responsibilities or contracts between modules, or create/remove a module boundary (extract, consolidate, isolate, split)? Answer no for merely reading, using, or editing code in multiple modules within one boundary.",
    "crosses_service_boundary": "Does the work change behaviour, contracts, communication, or data flow across independently deployed services or processes — an inter-service API, RPC or message contract, service-to-service dependency, or coordination semantics — or diagnose a failure that spans more than one deployed process? Naming services, service files, modules, repositories, or a build, release, or CI pipeline is not crossing a service boundary, and a rename, refactor, or public API format change across files that ship in one deployment stays inside one service.",
    "fix_or_result_known": "Is the fix or the expected result already known?",
    "intermittent_or_concurrency": "Is this a timing-dependent or concurrency defect (races, deadlocks, ordering)?",
    "needs_new_structure": "Does the work need a new design or structure rather than a change within the existing one?",
    "changes_security_or_payment_logic": "Does the work itself change authentication, authorization, secrets, cryptography, or payment behaviour? Reviewing or auditing such code is no; when the behaviour itself changes, name the part.",
    "reviews_security_sensitive_code": "Does the work review or judge the safety of security-sensitive code?",
    "security_domain": "Which security-sensitive area does the work touch (none, auth, payment, secrets, crypto, permissions, pii)?",
    "changes_public_api_contract": "Does the work change an API, CLI, schema, or response format that others consume?",
    "changes_persisted_data": "Does the work change what is stored — durable records, rows, or a database schema — or how persisted data is represented, migrated, or purged? Yes when the work creates, rewrites, migrates, or deletes persisted records or schema: a migration or backfill, a column, table, or storage-format change, stored-record creation or purge (users, PII, orders), re-encrypting stored data, or work that defines how financial, asset, or personal records are kept — a financial ledger, settlement, or custody pipeline, or ownership and asset records — including a design or architecture of how those records are written, settled, or kept. No when the work is about code structure, runtime behavior, or how components communicate rather than what is stored: refactors, renames, or module splits; in-memory caches and query implementations over unchanged data; infrastructure and control-plane work such as consensus, replication, synchronization, locking, scheduling, or messaging protocols; designs of data structures, protocols, or mechanisms rather than of stored records, including a design that only introduces a new data structure, event-log, or cryptographic format without changing existing records or schema; a feature that only spans files, layers, or services such as controllers, services, or templates, or that uploads, serves, or renders files or media, without a stated storage, schema, or record change; and reviews or investigations whose stored-state effect is not stated. A migration, schema, or repository/data-access file is strong evidence for yes but is not required, and a task that lists files and none of them is a migration, schema, or repository file is no only when the work itself changes no records or schema.",
    "irreversible_or_ledger_or_crypto": "Is the work any of: an irreversible production data change where data is destroyed or impossible to restore, financial ledger correctness, or a cryptographic operation — generating, deriving, rotating, or destroying keys, re-encrypting stored data, or designing or changing signing, encryption, or key-management schemes? A distributed consensus, synchronization, replication, coordination, or locking protocol is none of these by itself: answer yes only when the task itself destroys data, puts ledger correctness at stake, or designs or changes cryptography. Implementing, reviewing, or retuning signing, verification, hashing, or auth-token handling that uses an existing library (JWT, OAuth, TLS, bcrypt) — including hashing work factors and JWT signature validation — or diagnosing or fixing a rounding or precision defect in an amount calculation without moving money or rewriting the pricing, discount, or tax rule, are behaviour or correctness work on cryptography that already exists, covered by the security and payment facts: not key management, and not cryptographic operations. A migration that can be rolled back is not irreversible.",
    "changes_trust_boundary": "Does the work itself change where trust is established or delegated between components, services, tenants, or principals? Reviewing, auditing, testing, or inspecting such code is no: answer yes only when the task itself moves, adds, or removes such a boundary.",
    "blast_radius": "From the scope the task describes, would a wrong result stay within one component, feature, or recoverable subset (narrow) or reach many services, all users/tenants, production data at large, or money system-wide (broad)? Answer narrow for single-file or single-component work; a hypothetical worst case is never broad.",
    "silent_failure_material_harm": "Is there a concrete path in the described work where a mistake would go unnoticed (no error, alert, or failing test) AND cause data loss, wrong money movement, security exposure, or cross-service inconsistency? Code, PR, or plan review that only judges an artifact is no even when the artifact is dangerous; designing, implementing, fixing, or investigating behaviour is not review work. Answer no unless both the silence and the harm mechanism are evident from the task; a hypothetical worst case is no.",
    "requires_code_understanding": "Does the work depend on reading existing code beyond the edit site?",
}

# A probability answer becomes yes at or above the fact's decision point, and no below it.
# There is deliberately no "uncertain" band in between: a manufactured unknown leaves the route
# unresolved, which both blocks the route and asks the user about a fact the model did in fact
# answer. A model that cannot tell says so itself, through the "unknown" choice its question offers.
DEFAULT_DECISION_POINT = 0.5

# Facts whose "yes" escalates: answer yes on the lighter evidence, since under-escalating costs more.
SAFETY_DECISION_POINT = 0.4

# Facts whose "yes" *lowers* the floor need the opposite treatment: mechanical_only is the only
# answer that drops the base below L2, so it takes a high bar.
# ponytail: 0.8 is fitted to the golden corpus, where the model's own answers for the two
# cases either side of this line drift across 0.75 between runs; 0.8 keeps that drift on the
# safe side at the cost of one L1 case reading as L2. Re-fit from a fresh probability dump
# if the model changes.
DEESCALATING_DECISION_POINT = 0.8

SAFETY_FACTS: tuple[str, ...] = (
    "changes_security_or_payment_logic",
    "reviews_security_sensitive_code",
    "irreversible_or_ledger_or_crypto",
    "changes_trust_boundary",
    "changes_public_api_contract",
    "changes_persisted_data",
    "silent_failure_material_harm",
    "intermittent_or_concurrency",
)

DEESCALATING_FACTS: tuple[str, ...] = ("mechanical_only",)

FACT_DECISION_POINTS: dict[str, float] = {
    **{fact: SAFETY_DECISION_POINT for fact in SAFETY_FACTS},
    **{fact: DEESCALATING_DECISION_POINT for fact in DEESCALATING_FACTS},
}


def fact_decision_point(fact: str) -> float:
    """Return the probability at or above which this fact reads as yes."""
    return FACT_DECISION_POINTS.get(fact, DEFAULT_DECISION_POINT)


TASK_TYPE_CRITERIA: dict[str, str] = {
    "implementation": "Build or change code directly: features, APIs, UI work, bug fixes, tests. Finding the cause of a defect or anomaly in existing behaviour — find, determine, diagnose, investigate, or analyse why something fails, crashes, is slow, or is inconsistent — is implementation when that defect is the subject and no report-only deliverable is stated: the scope is unknown until it is diagnosed, and the fix is the expected outcome.",
    "design": "Decide structure or direction without editing code: architecture, API or data-model design, technology choice, implementation planning.",
    "review": "Analyse existing code or plans to find problems: code, PR, security, performance, or design review. The work itself changes no code.",
    "inspect": "Read-only lookup or explanation needing no judgement of correctness, safety or design: find where something is defined, explain what code does, check a setting. Inspecting a state, metric, log, or artifact stays inspect — including which errors a log or dashboard contains, whether something is wired up, or what a diff changed: the deliverable is what the artifact says, not why the behaviour is wrong.",
    "local_refactoring": "Clean up internals while preserving behaviour and module boundaries: extract functions, renames, deduplication within one module.",
    "architectural_refactoring": "Change module boundaries or system structure AND carry out the edits: module splits, dependency inversion, moving responsibilities between services.",
}

# A fact with no "unknown" option still has to resolve a probability that sits between the
# thresholds. Resolve it toward the answer that does not lower the level: "yes" on
# mechanical_only drops the base to L1 and "yes" on fix_or_result_known removes the L3 floor,
# so uncertainty on those two must read as "no".
STRICT_FACT_UNCERTAIN_DEFAULT: dict[str, str] = {
    "mechanical_only": "no",
    "fix_or_result_known": "no",
    "needs_new_structure": "yes",
}


def resolve_uncertain_fact(fact: str) -> str:
    """Return the safest answer for a fact whose probability landed between the thresholds."""
    allowed = FACTS[fact]
    if "unknown" in allowed:
        return "unknown"
    return STRICT_FACT_UNCERTAIN_DEFAULT[fact]
