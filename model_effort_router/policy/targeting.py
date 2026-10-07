"""Cheap hook eligibility gate. Explicit CLI/Main role requests bypass these heuristics."""
import re

ROUTE, NO_ROUTE = "route", "no_route"
_CODE = re.compile(r"\b(code|codebase|repo|repository|file|function|class|module|bug|test|api|diff|schema|database|"
                   r"migration|service|cache|server|client|auth|token|script|config|build|lint|"
                   r"query|serializer|scheduler|protocol|report|plugin|opencode)\b|"
                   r"\.(?:py|js|jsx|ts|tsx|go|rs|java|rb|php|swift|kt|c|cpp|sql|yaml|yml|json|toml|md)\b|"
                   r"코드|저장소|파일|함수|버그|테스트|리뷰|설계|분석|세션|플러그인", re.I)
_INTENT = re.compile(r"\b(implement|add|fix|refactor|rename|change|update|create|make|build|write|remove|delete|support|redesign|"
                     r"migrate|modify|rewrite|replace|patch|optimi[sz]e|lint|test|review|analy[sz]e|debug|"
                     r"inspect|design|plan|explain|why|how|investigate|audit)\b|"
                     r"구현|추가|수정|고쳐|리팩터|만들|삭제|변경|개선|검토|리뷰|분석|설계|설명|계획|왜|어떻게|옮겨", re.I)


def classify_target(text, paths=()):
    if not isinstance(text, str) or not text.strip():
        return NO_ROUTE
    return ROUTE if (paths or _CODE.search(text)) and _INTENT.search(text) else NO_ROUTE
