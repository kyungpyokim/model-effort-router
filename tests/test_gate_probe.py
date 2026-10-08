import io
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from model_effort_router.gate import probe
from model_effort_router.gate.discovery import Check

CHECK = Check("test", "python3 -m unittest", "AGENTS.md", False)
PASSED, FAILED = {"status": "passed"}, {"status": "failed", "exit_code": 1}
BUGGY = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"
FIXED = BUGGY.replace("return a - b\n\n\ndef sub", "return a + b\n\n\ndef sub")
OLD_TEST = (
    "import unittest\nfrom calc import sub\n\n\nclass T(unittest.TestCase):\n"
    "    def test_sub(self):\n        self.assertEqual(sub(3, 1), 2)\n"
)
ADD_TEST = (
    "import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n"
    "    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n"
)


class IsTestPathTest(unittest.TestCase):
    def test_test_files_by_language(self):
        for path in (
            "test_calc.py",
            "pkg/calc_test.py",
            "tests/helpers.py",
            "a/tests/b/c.py",
            "app.test.ts",
            "web/app.spec.jsx",
            "x.test.mjs",
            "src/__tests__/a.ts",
            "pkg/calc_test.go",
            "calc_spec.rb",
            "spec/calc.rb",
            "test/calc.rb",
        ):
            self.assertTrue(probe.is_test_path(path), path)

    def test_everything_else_is_not_a_test(self):
        for path in (
            "conftest.py",
            "tests/conftest.py",
            "src/app.py",
            "docs/test_notes.md",
            "calc.go",
            "tests/fixtures/data.py",
            "pkg/testdata/a_test.go",
            "tests/data.json",
            "app.ts",
            "",
        ):
            self.assertFalse(probe.is_test_path(path), path)


class IsTestSideTest(unittest.TestCase):
    """Everything a run changes on the test side goes over the snapshot; only product source stays at HEAD."""

    def test_test_side_paths(self):
        for path in (
            "tests/test_a.py",
            "conftest.py",
            "tests/conftest.py",
            "tests/data/case.txt",
            "test/x.yml",
            "spec/support/y.json",
            "web/__tests__/z.snap",
            "web/__snapshots__/a.snap",
            "pkg/testdata/in.json",
            "tests/fixtures/data.py",
            "tests/helpers.py",
            "web/__tests__/util.ts",
            "spec/support/h.rb",
        ):
            self.assertTrue(probe.is_test_side(path), path)

    def test_product_source_is_not_test_side(self):
        for path in ("src/app.py", "calc.py", "docs/test_notes.md", "data/case.txt", "README.md"):
            self.assertFalse(probe.is_test_side(path), path)

    def test_code_under_a_bare_spec_test_or_fixtures_dir_is_product_source(self):
        for path in (
            "app/spec/schema.py",
            "test/util.py",
            "fixtures/helper.py",
            "pkg/testdata/gen.go",
            "app/spec/types.ts",
        ):
            self.assertFalse(probe.is_test_side(path), path)


def git(cwd, *args):
    env = {**os.environ, "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1"}
    cmd = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args]
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout


def write(root, rel, text):
    path = Path(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def tree_state(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


class RepoCase(unittest.TestCase):
    """A repo with one commit (buggy add, passing sub test); then 'the run' fixes add and adds a test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        write(self.repo, "calc.py", BUGGY)
        write(self.repo, "tests/__init__.py", "")
        write(self.repo, "tests/test_old.py", OLD_TEST)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def apply_run(self, test_text=ADD_TEST):
        write(self.repo, "calc.py", FIXED + "\n\ndef mul(a, b):\n    return a * b\n")
        write(self.repo, "tests/test_new.py", test_text)
        write(self.repo, "newmod.py", "X = 1\n")
        return ["calc.py", "tests/test_new.py", "newmod.py"]

    def probe(self, paths, run, check=CHECK):
        return probe.probe_without_change(str(self.repo), paths, check, 30, run=run)


class SpyRun:
    """Fake run_check: records the snapshot's files at call time instead of running anything."""

    def __init__(self, *results):
        self.results, self.seen = list(results), []

    def __call__(self, check, cwd, timeout_s):
        self.seen.append((cwd, tree_state(cwd)))
        return self.results.pop(0)


class SnapshotTest(RepoCase):
    def test_snapshot_is_head_plus_this_runs_test_files(self):
        paths = self.apply_run()
        run = SpyRun(PASSED)
        self.probe(paths, run)
        _, files = run.seen[0]
        self.assertEqual(files["calc.py"].decode(), BUGGY)  # modified source: HEAD content
        self.assertEqual(files["tests/test_new.py"].decode(), ADD_TEST)  # new test: working tree content
        self.assertNotIn("newmod.py", files)  # new source file: absent
        self.assertIn("tests/test_old.py", files)
        self.assertFalse(any(name.startswith(".git/") for name in files))

    def test_a_modified_test_gets_the_new_content_and_a_deleted_one_disappears(self):
        write(self.repo, "tests/test_extra.py", "OLD = 1\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "extra")
        write(self.repo, "tests/test_old.py", OLD_TEST + "# edited\n")
        (self.repo / "tests/test_extra.py").unlink()
        run = SpyRun(PASSED)
        self.probe(["calc.py", "tests/test_old.py", "tests/test_extra.py"], run)
        files = run.seen[0][1]
        self.assertTrue(files["tests/test_old.py"].decode().endswith("# edited\n"))
        self.assertNotIn("tests/test_extra.py", files)

    def test_a_symlink_in_head_is_replaced_not_written_through(self):
        write(self.repo, "real.py", "REAL = 1\n")
        (self.repo / "tests/test_s.py").symlink_to("../real.py")  # relative, inside the repo
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "link")
        (self.repo / "tests/test_s.py").unlink()
        write(self.repo, "tests/test_s.py", "NEW = 2\n")  # the run replaced the link with a regular file
        run = SpyRun(PASSED)
        r = self.probe(["calc.py", "tests/test_s.py"], run)
        files = run.seen[0][1]
        self.assertEqual(len(run.seen), 1)
        self.assertEqual((files["real.py"].decode(), files["tests/test_s.py"].decode()), ("REAL = 1\n", "NEW = 2\n"))
        self.assertEqual(r["verdict"], "passes_without_change")

    def test_test_side_data_and_conftest_are_overlaid_but_source_stays_at_head(self):
        write(self.repo, "tests/data/case.txt", "5\n")
        write(self.repo, "tests/conftest.py", "# helper\n")
        write(self.repo, "tests/test_new.py", ADD_TEST)
        write(self.repo, "calc.py", FIXED)
        run = SpyRun(PASSED)
        r = self.probe(["calc.py", "tests/data/case.txt", "tests/conftest.py", "tests/test_new.py"], run)
        files = run.seen[0][1]
        self.assertEqual((files["tests/data/case.txt"], files["tests/conftest.py"]), (b"5\n", b"# helper\n"))
        self.assertEqual(files["calc.py"].decode(), BUGGY)
        self.assertEqual(r["overlay"], ["tests/conftest.py", "tests/data/case.txt", "tests/test_new.py"])
        self.assertEqual(r["tests"], ["tests/test_new.py"])  # tests: the test files among them

    def test_a_symlinked_test_file_in_the_working_tree_is_inconclusive(self):
        write(self.repo, "elsewhere.py", "E = 1\n")
        (self.repo / "tests/test_link.py").symlink_to("../elsewhere.py")
        run = SpyRun(PASSED)
        r = self.probe(["calc.py", "tests/test_link.py"], run)
        self.assertEqual((r["verdict"], run.seen), ("inconclusive", []))
        self.assertIn("symlink", r["reason"])

    def test_a_path_escaping_the_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as dest:
            with self.assertRaises(ValueError):
                probe._overlay_tests(str(self.repo), dest, ["../x"])


class VerdictTest(RepoCase):
    def test_passing_run_on_the_snapshot_is_passes_without_change(self):
        paths = self.apply_run()
        run = SpyRun(PASSED)
        r = self.probe(paths, run)
        self.assertEqual(
            (r["verdict"], r["reason"], r["tests"], len(run.seen)),
            ("passes_without_change", None, ["tests/test_new.py"], 1),
        )

    def test_failure_then_clean_control_is_fails_without_change(self):
        paths = self.apply_run()
        run = SpyRun(FAILED, PASSED)
        r = self.probe(paths, run)
        self.assertEqual((r["verdict"], r["reason"], len(run.seen)), ("fails_without_change", None, 2))
        self.assertNotIn("output_tail", r)
        self.assertNotIn("tests/test_new.py", run.seen[1][1])  # the control is HEAD as it is
        self.assertEqual(run.seen[1][1]["calc.py"].decode(), BUGGY)

    def test_the_first_runs_truncated_output_tail_is_kept_for_a_human(self):
        tail = "ImportError: no module named newmod\n" * 40
        r = self.probe(self.apply_run(), SpyRun({**FAILED, "output_tail": tail}, PASSED))
        self.assertEqual(r["verdict"], "fails_without_change")
        self.assertTrue(0 < len(r["output_tail"]) <= probe.OUTPUT_TAIL_CHARS)
        self.assertTrue(tail.endswith(r["output_tail"]))
        r = self.probe(self.apply_run(), SpyRun({**FAILED, "output_tail": tail}, FAILED))
        self.assertEqual((r["verdict"], r["output_tail"] == tail[-probe.OUTPUT_TAIL_CHARS :]), ("inconclusive", True))

    def test_failure_that_also_fails_the_control_is_inconclusive(self):
        r = self.probe(self.apply_run(), SpyRun(FAILED, FAILED))
        self.assertEqual(r["verdict"], "inconclusive")
        self.assertIn("also fails", r["reason"])

    def test_a_timeout_or_unstartable_command_is_inconclusive_without_a_control(self):
        run = SpyRun({"status": "failed", "reason": "timeout after 30s"})
        r = self.probe(self.apply_run(), run)
        self.assertEqual((r["verdict"], len(run.seen)), ("inconclusive", 1))
        self.assertIn("timeout", r["reason"])

    def test_run_exceptions_are_inconclusive_and_the_snapshot_is_removed(self):
        paths = self.apply_run()
        scratch = self.root / "scratch"
        scratch.mkdir()
        seen = []

        def boom(check, cwd, timeout_s):
            seen.append(cwd)
            raise RuntimeError("kaboom")

        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            r = self.probe(paths, boom)
        self.assertEqual(r["verdict"], "inconclusive")
        self.assertIn("kaboom", r["reason"])
        self.assertEqual((len(seen), os.listdir(scratch)), (1, []))
        self.assertEqual((r["tests"], r["overlay"]), (["tests/test_new.py"], ["tests/test_new.py"]))  # kept where known

    def test_snapshots_are_removed_after_success_too(self):
        paths = self.apply_run()
        scratch = self.root / "scratch"
        scratch.mkdir()
        with mock.patch.object(tempfile, "tempdir", str(scratch)):
            self.probe(paths, SpyRun(FAILED, PASSED))
        self.assertEqual(os.listdir(scratch), [])

    def test_the_user_tree_and_git_dir_are_untouched(self):
        paths = self.apply_run()
        before, status = tree_state(self.repo), git(self.repo, "status", "--porcelain")
        self.probe(paths, SpyRun(FAILED, PASSED))
        self.probe(paths, SpyRun(PASSED))
        self.assertEqual(tree_state(self.repo), before)
        self.assertEqual(git(self.repo, "status", "--porcelain"), status)
        self.assertEqual(git(self.repo, "stash", "list"), "")
        self.assertEqual(len(git(self.repo, "worktree", "list").splitlines()), 1)


class SkipTest(RepoCase):
    def test_no_test_file_among_the_changes_is_skipped_without_running(self):
        run = SpyRun()
        r = self.probe(["calc.py", "docs/test_notes.md"], run)
        self.assertEqual((r["verdict"], r["reason"], run.seen), ("skipped", "no test files changed", []))

    def test_only_test_side_changes_is_skipped_without_running(self):
        write(self.repo, "tests/test_new.py", ADD_TEST)
        write(self.repo, "tests/data/case.txt", "5\n")
        run = SpyRun()
        r = self.probe(["tests/test_new.py", "tests/data/case.txt"], run)
        self.assertEqual((r["verdict"], r["reason"], run.seen), ("skipped", "only tests changed", []))

    def test_markdown_beside_test_side_changes_is_still_only_tests(self):
        write(self.repo, "tests/test_new.py", ADD_TEST)
        run = SpyRun()
        r = self.probe(["tests/test_new.py", "README.md", "docs/notes.md"], run)
        self.assertEqual((r["verdict"], r["reason"], run.seen), ("skipped", "only tests changed", []))

    def test_product_code_under_spec_with_a_test_change_is_not_only_tests(self):
        write(self.repo, "app/spec/schema.py", "X = 1\n")
        write(self.repo, "tests/test_new.py", ADD_TEST)
        run = SpyRun(PASSED)
        r = self.probe(["app/spec/schema.py", "tests/test_new.py"], run)
        self.assertEqual((r["verdict"], len(run.seen)), ("passes_without_change", 1))
        self.assertNotIn("app/spec/schema.py", r["overlay"])

    def test_markdown_alone_is_no_test_change(self):
        r = self.probe(["README.md"], SpyRun())
        self.assertEqual((r["verdict"], r["reason"]), ("skipped", "no test files changed"))

    def test_no_test_command_is_skipped(self):
        run = SpyRun()
        r = self.probe(self.apply_run(), run, check=None)
        self.assertEqual((r["verdict"], run.seen), ("skipped", []))

    def test_not_a_repository_and_no_head_are_skipped(self):
        plain = self.root / "plain"
        write(plain, "tests/test_a.py", "A = 1\n")
        run = SpyRun()
        r = probe.probe_without_change(str(plain), ["calc.py", "tests/test_a.py"], CHECK, 30, run=run)
        self.assertEqual((r["verdict"], r["reason"]), ("skipped", "not a git repository"))
        empty = self.root / "empty"
        empty.mkdir()
        git(empty, "init", "-q")
        write(empty, "tests/test_a.py", "A = 1\n")
        r = probe.probe_without_change(str(empty), ["calc.py", "tests/test_a.py"], CHECK, 30, run=run)
        self.assertEqual((r["verdict"], r["reason"], run.seen), ("skipped", "no HEAD commit", []))

    def test_a_subdirectory_of_a_repository_is_skipped(self):
        write(self.repo, "sub/tests/test_a.py", "A = 1\n")
        run = SpyRun()
        r = probe.probe_without_change(
            str(self.repo / "sub"), ["sub/calc.py", "sub/tests/test_a.py"], CHECK, 30, run=run
        )
        self.assertEqual((r["verdict"], r["reason"], run.seen), ("skipped", "cwd is not the repository root", []))


class TarSafetyTest(unittest.TestCase):
    def archive(self, *names):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for name in names:
                info = tarfile.TarInfo(name)
                info.size = 2
                tar.addfile(info, io.BytesIO(b"x\n"))
        return io.BytesIO(buf.getvalue())

    def test_absolute_and_parent_members_are_rejected(self):
        for name in ("/abs/evil.txt", "../evil.txt", "a/../../evil.txt"):
            with tempfile.TemporaryDirectory() as dest:
                with self.assertRaises(ValueError, msg=name):
                    probe._extract_tar(self.archive("ok.txt", name), dest)
                self.assertFalse(os.path.exists(os.path.join(dest, "..", "evil.txt")))

    def test_old_python_fallback_extracts_files_and_refuses_links(self):
        link = io.BytesIO()
        with tarfile.open(fileobj=link, mode="w") as tar:
            info = tarfile.TarInfo("evil")
            info.type, info.linkname = tarfile.SYMTYPE, "/etc/passwd"
            tar.addfile(info)
        with mock.patch.object(probe, "_HAS_DATA_FILTER", False):
            with tempfile.TemporaryDirectory() as dest:
                probe._extract_tar(self.archive("a/b.txt"), dest)
                self.assertEqual(Path(dest, "a/b.txt").read_text(), "x\n")
                with self.assertRaises(ValueError):
                    probe._extract_tar(io.BytesIO(link.getvalue()), dest)
                self.assertFalse(os.path.lexists(os.path.join(dest, "evil")))

    def test_plain_members_are_extracted(self):
        with tempfile.TemporaryDirectory() as dest:
            probe._extract_tar(self.archive("a/b.txt"), dest)
            self.assertEqual(Path(dest, "a/b.txt").read_text(), "x\n")


class RealCommandTest(RepoCase):
    """The probe against a real `python3 -m unittest` run, no fakes."""

    def check(self):
        return Check("test", shlex.join([sys.executable, "-m", "unittest"]), "AGENTS.md", False)

    def real(self, paths):
        return probe.probe_without_change(str(self.repo), paths, self.check(), 60)

    def test_a_test_that_passes_without_the_change_is_flagged(self):
        write(self.repo, "calc.py", BUGGY + "\n\ndef mul(a, b):\n    return a * b\n")
        write(self.repo, "tests/test_sub2.py", OLD_TEST.replace("test_sub", "test_sub_again"))
        r = self.real(["calc.py", "tests/test_sub2.py"])
        self.assertEqual((r["verdict"], r["tests"]), ("passes_without_change", ["tests/test_sub2.py"]))

    def test_a_test_that_catches_the_old_code_is_confirmed(self):
        r = self.real(self.apply_run())
        self.assertEqual((r["verdict"], r["tests"]), ("fails_without_change", ["tests/test_new.py"]))

    def test_renamed_symbol_across_product_files_under_spec_is_not_a_false_catch(self):
        """app/main.py imports from app/spec/schema.py; the run renames the symbol in both and adds a test that old code passes."""
        write(self.repo, "app/__init__.py", "")
        write(self.repo, "app/spec/__init__.py", "")
        write(self.repo, "app/spec/schema.py", "def fields():\n    return ['a']\n")
        write(self.repo, "app/main.py", "from app.spec.schema import fields\n\n\ndef names():\n    return fields()\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "app")
        write(self.repo, "app/spec/schema.py", "def field_names():\n    return ['a']\n")
        write(
            self.repo,
            "app/main.py",
            "from app.spec.schema import field_names\n\n\ndef names():\n    return field_names()\n",
        )
        write(
            self.repo,
            "tests/test_more.py",
            "import unittest\nfrom app.main import names\n\n\nclass T(unittest.TestCase):\n    def test_names(self):\n"
            "        self.assertEqual(names(), ['a'])\n",
        )
        r = self.real(["app/main.py", "app/spec/schema.py", "tests/test_more.py"])
        self.assertEqual((r["verdict"], r["overlay"]), ("passes_without_change", ["tests/test_more.py"]))

    def test_new_test_data_is_part_of_the_snapshot(self):
        """A new test reading a new data file: with the data overlaid it passes, so it must not look like a catch."""
        write(self.repo, "tests/data/case.txt", "5\n")
        write(
            self.repo,
            "tests/test_data.py",
            "import os\nimport unittest\n\n\nclass T(unittest.TestCase):\n    def test_data(self):\n"
            "        path = os.path.join(os.path.dirname(__file__), 'data', 'case.txt')\n"
            "        self.assertEqual(open(path).read(), '5\\n')\n",
        )
        write(self.repo, "calc.py", BUGGY + "# touched\n")
        r = self.real(["calc.py", "tests/data/case.txt", "tests/test_data.py"])
        self.assertEqual(r["verdict"], "passes_without_change")

    def test_an_environment_failure_is_inconclusive_not_a_catch(self):
        # HEAD already cannot run (a dependency the snapshot lacks): a failing probe proves nothing
        write(self.repo, "tests/test_env.py", "import not_installed_anywhere\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "needs a dependency")
        write(self.repo, "tests/test_env.py", "import not_installed_anywhere\nX = 1\n")
        self.assertEqual(self.real(["calc.py", "tests/test_env.py"])["verdict"], "inconclusive")


class GitDiffPathsTest(RepoCase):
    """review.git_diff paths feed the probe: they must be literal and must name both sides of a rename."""

    def test_non_ascii_paths_are_not_quoted(self):
        from model_effort_router import review as rv

        write(self.repo, "tests/test_é.py", "A = 1\n")
        write(self.repo, "calc.py", FIXED)
        d = rv.git_diff(str(self.repo))
        self.assertEqual(d["untracked"], ["tests/test_é.py"])
        git(self.repo, "add", "-A")
        self.assertEqual(rv.git_diff(str(self.repo))["files"], ["calc.py", "tests/test_é.py"])
        self.assertTrue(probe.is_test_path(d["untracked"][0]))

    def test_a_staged_rename_lists_the_old_and_the_new_path(self):
        from model_effort_router import review as rv

        git(self.repo, "mv", "tests/test_old.py", "tests/test_renamed.py")
        self.assertEqual(rv.git_diff(str(self.repo))["files"], ["tests/test_old.py", "tests/test_renamed.py"])


if __name__ == "__main__":
    unittest.main()
