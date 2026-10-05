import unittest

from model_effort_router.difficulty.risk import detect_content_flags, detect_risk_flags


class RiskDetectionTest(unittest.TestCase):
    def test_text_flags(self):
        cases = {
            "security": "Fix the XSS vulnerability in the comment form",
            "auth": "Add OAuth login with JWT refresh",
            "payment": "Retry failed payment charges via Stripe",
            "data_migration": "Write a migration to split the users table",
            "data_loss": "Purge old rows; this could cause data loss",
            "concurrency": "Fix the race condition in the job queue",
        }
        for flag, text in cases.items():
            with self.subTest(flag=flag):
                self.assertIn(flag, detect_risk_flags(text))

    def test_korean_keywords(self):
        self.assertIn("payment", detect_risk_flags("결제 모듈 수정"))
        self.assertIn("auth", detect_risk_flags("로그인 오류 수정"))

    def test_path_flags(self):
        self.assertIn("auth", detect_risk_flags("tweak", ["src/auth/session.py"]))
        self.assertIn("auth", detect_risk_flags("tweak", ["src/user_auth.py"]))
        self.assertIn("data_migration", detect_risk_flags("tweak", ["db/migrations/0001.sql"]))
        self.assertIn("payment", detect_risk_flags("tweak", ["billing/checkout.ts"]))

    def test_benign_text_has_no_flags(self):
        self.assertEqual(detect_risk_flags("Fix typo in README"), ())

    def test_no_substring_false_positives(self):
        self.assertEqual(detect_risk_flags("Update the authors list"), ())
        self.assertEqual(detect_risk_flags("Unblock the build and style the blockquote"), ())

    def test_multiple_flags_in_canonical_order(self):
        flags = detect_risk_flags("Add payment auth and fix deadlock")
        self.assertEqual(flags, ("auth", "payment", "concurrency"))

    def test_empty_inputs(self):
        self.assertEqual(detect_risk_flags(""), ())
        self.assertEqual(detect_risk_flags(None), ())


class ContentRiskTest(unittest.TestCase):
    """Added code lines only: destructive SQL and shell, not the natural-language words the request rules use."""

    def test_destructive_statements(self):
        cases = {
            "data_loss": ["DROP TABLE users;", "alter table t drop column x", "TRUNCATE TABLE logs", "rm -rf /var/data"],
            "data_migration": ["ALTER TABLE users ADD COLUMN age int;"],
        }
        for flag, lines in cases.items():
            for line in lines:
                with self.subTest(line=line):
                    self.assertIn(flag, detect_content_flags(line))

    def test_both_flags_come_back_in_canonical_order(self):
        self.assertEqual(detect_content_flags("ALTER TABLE a ADD b int;\nDROP TABLE c;"), ("data_migration", "data_loss"))

    def test_words_that_flag_a_request_do_not_flag_content(self):
        for text in ("with self.lock:", "charge = price * qty", "thread = Thread()", "migrate_users()", "login(user)"):
            with self.subTest(text=text):
                self.assertEqual(detect_content_flags(text), ())


if __name__ == "__main__":
    unittest.main()
