import unittest

from model_effort_router.policy.targeting import (
    NO_ROUTE,
    PLAN_ONLY,
    REVIEW_ONLY,
    ROUTE,
    classify_target,
)


class TargetingTest(unittest.TestCase):
    def check(self, cases):
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(classify_target(text), expected)

    def test_route(self):
        self.check(
            [
                ("Add a login endpoint to the API and write tests", ROUTE),
                ("Fix the bug in parser.py", ROUTE),
                ("Rename the variable in src/app.py", ROUTE),
                ("Can you refactor this function?", ROUTE),
                ("결제 모듈 함수 수정해줘", ROUTE),
                ("Review and fix the code", ROUTE),
                ("Do the auth refactor in x.py", ROUTE),
                ("Plan and then implement the new API endpoint", ROUTE),
                # seed-corpus misses (2026-10-01): verbs/contexts the rules did not know
                ("Bump the retry count in the HTTP client wrapper from 3 to 5 and adjust its unit test", ROUTE),
                ("Support CSV export in the reports module; the query builder and serializer need changes", ROUTE),
                ("Make the job scheduler safe to run on multiple instances", ROUTE),
                ("Redesign the cache invalidation protocol; stale reads show up with two writers", ROUTE),
                ("세션 저장소를 Redis로 옮겨줘", ROUTE),
            ]
        )

    def test_plan_only(self):
        self.check(
            [
                ("Write an implementation plan for the new API endpoint", PLAN_ONLY),
                ("Make a plan to add caching to the API", PLAN_ONLY),
                ("Plan only: refactor the auth module", PLAN_ONLY),
                ("이 API 모듈 리팩터링 계획만 세워줘", PLAN_ONLY),
            ]
        )

    def test_review_only(self):
        self.check(
            [
                ("Review this diff for bugs in src/app.py", REVIEW_ONLY),
                ("Please review my code", REVIEW_ONLY),
                ("이 코드 리뷰해줘", REVIEW_ONLY),
            ]
        )

    def test_no_route(self):
        self.check(
            [
                ("", NO_ROUTE),
                ("   ", NO_ROUTE),
                ("hello", NO_ROUTE),
                ("Thanks!", NO_ROUTE),
                ("What does this function do?", NO_ROUTE),
                ("Explain the auth module", NO_ROUTE),
                ("How do I fix this bug?", NO_ROUTE),
                ("Show git status", NO_ROUTE),
                ("Show the code in foo.py", NO_ROUTE),
                ("Show a loading spinner in App.tsx", NO_ROUTE),  # ambiguous -> no_route
                # change verb but no code context -> ambiguous -> no_route
                ("Add 2 and 3", NO_ROUTE),
                ("Fix my essay", NO_ROUTE),
                ("Review my essay", NO_ROUTE),
            ]
        )

    def test_none_is_no_route(self):
        self.assertEqual(classify_target(None), NO_ROUTE)

    def test_paths_count_as_code_context(self):
        self.assertEqual(classify_target("Fix it", paths=["src/a.py"]), ROUTE)
        self.assertEqual(classify_target("Fix it"), NO_ROUTE)


if __name__ == "__main__":
    unittest.main()
