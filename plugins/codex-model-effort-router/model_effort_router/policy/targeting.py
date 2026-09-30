"""Cheap routing-target rules (spec 3.3). Anything ambiguous -> no_route."""
import re

ROUTE, PLAN_ONLY, REVIEW_ONLY, NO_ROUTE = "route", "plan_only", "review_only", "no_route"


def _rx(pattern):
    return re.compile(pattern, re.IGNORECASE)


_QUESTION_START = _rx(
    r"^\W*(what|why|how|explain|describe|tell|which|where|who|when|is|are|does|"
    r"설명|왜|무엇|뭐|어떻게|알려)\b"
    r"|^\W*(설명|왜|무엇|뭐|어떻게|알려)"
)
_CODE_CONTEXT = _rx(
    r"\b(code|codebase|files?|functions?|methods?|class(?:es)?|modules?|bugs?|tests?|apis?|endpoints?|"
    r"repo|repository|config|components?|variables?|diff|commits?|branch|script|schema)\b"
    r"|\.(py|js|jsx|ts|tsx|go|rs|java|rb|php|swift|kt|c|cpp|h|sql|ya?ml|json|toml|md)\b|`"
    r"|코드|함수|파일|버그|테스트|모듈|클래스|컴포넌트|엔드포인트|커밋"
)
_CHANGE_VERB = _rx(
    r"\b(implement|add|fix|refactor|rename|change|update|create|build|write|remove|delete|"
    r"migrate|modify|rewrite|replace|patch|extract|move|optimi[sz]e|port)\b"
    r"|구현|추가|수정|고쳐|리팩터|만들|삭제|변경|바꿔"
)
# "write/make/draft a plan" is the deliverable, not a code change.
_PLAN_PHRASE = _rx(
    r"\b(?:write|make|draft|create|give me|come up with)\s+(?:an?\s+|the\s+)?(?:\w+\s+)?(?:plan|outline)\b"
)
_PLAN_WORD = _rx(r"\b(plan|outline|roadmap)\b|계획")
_PLAN_ONLY = _rx(r"\bplan only\b|\bonly (?:a )?plan\b|\bjust (?:a )?plan\b|계획만")
_THEN_EXECUTE = _rx(r"\b(?:and|then)\s+(?:then\s+)?(?:implement|build|execute|do it)\b|구현까지")
_REVIEW_WORD = _rx(r"\breview\b|리뷰|검토")
_REVIEW_ONLY = _rx(r"\breview only\b|\bonly review\b|\bjust review\b|리뷰만")


def classify_target(text, paths=()) -> str:
    if not isinstance(text, str) or not text.strip():
        return NO_ROUTE
    if _QUESTION_START.search(text):
        return NO_ROUTE
    if not (paths or _CODE_CONTEXT.search(text)):
        return NO_ROUTE

    plan_directive = bool(_PLAN_PHRASE.search(text))
    body = _PLAN_PHRASE.sub(" ", text)
    has_change = bool(_CHANGE_VERB.search(body))
    has_plan = plan_directive or bool(_PLAN_WORD.search(text))
    has_review = bool(_REVIEW_WORD.search(text))

    if has_plan and not _THEN_EXECUTE.search(text):
        if _PLAN_ONLY.search(text) or plan_directive or not has_change:
            return PLAN_ONLY
    if has_review and (_REVIEW_ONLY.search(text) or not has_change):
        return REVIEW_ONLY
    if has_change:
        return ROUTE
    return NO_ROUTE
