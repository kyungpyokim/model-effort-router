from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "scripts" / "astra_adapter.py"


class AstraAdapterTests(unittest.TestCase):
    def init_repo(self, directory: Path) -> str:
        for command in (
            ("git", "init", "-q"),
            ("git", "config", "user.email", "test@example.com"),
            ("git", "config", "user.name", "Test"),
        ):
            subprocess.run(command, cwd=directory, check=True)
        (directory / "owned.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(("git", "add", "owned.txt"), cwd=directory, check=True)
        subprocess.run(("git", "commit", "-qm", "base"), cwd=directory, check=True)
        return subprocess.check_output(("git", "rev-parse", "HEAD"), cwd=directory, text=True).strip()

    def invoke(self, repo: Path, route: Path, manifest: Path, base_sha: str, artifacts: Path, worker: str, digest: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable, str(ADAPTER), "--repo", str(repo), "--route-file", str(route),
                "--route-sha256", digest or hashlib.sha256(route.read_bytes()).hexdigest(),
                "--manifest-file", str(manifest), "--manifest-sha256", hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "--base-sha", base_sha, "--artifact-dir", str(artifacts), "--worker-command",
                sys.executable, "-c", worker,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_runs_worker_once_in_an_isolated_fixed_base_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            worker = (
                "import json, os, pathlib; "
                "pathlib.Path('owned.txt').write_text('changed\\n')"
            )
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, worker)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            metadata = json.loads((artifacts / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["base_sha"], base_sha)
            self.assertEqual(metadata["route_sha256"], hashlib.sha256(route.read_bytes()).hexdigest())
            self.assertEqual(metadata["attempts"], 1)
            self.assertTrue((artifacts / "attempt-1.log").exists())
            self.assertEqual((artifacts / "manifest.json").read_text(encoding="utf-8"), manifest.read_text(encoding="utf-8"))
            self.assertEqual((repo / "owned.txt").read_text(encoding="utf-8"), "base\n")

    def test_rejects_route_digest_mismatch_before_creating_a_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, "raise SystemExit(0)", digest="0" * 64)
            self.assertEqual(proc.returncode, 2)
            self.assertIn("route digest mismatch", proc.stderr)
            self.assertFalse((artifacts / "attempt-1").exists())

    def test_rejects_duplicate_caller_manifest_before_creating_a_worktree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt","owned.txt"]}', encoding="utf-8")
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, "raise SystemExit(0)")
            self.assertEqual(proc.returncode, 2)
            self.assertIn("duplicate owned file", proc.stderr)
            self.assertFalse((artifacts / "attempt-1").exists())

    def test_worker_cannot_replace_caller_manifest_to_claim_unowned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            worker = (
                "import pathlib; "
                f"pathlib.Path({str(manifest)!r}).write_text('{{\\\"owned_files\\\":[\\\"other.txt\\\"]}}'); "
                "pathlib.Path('other.txt').write_text('changed\\n')"
            )
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, worker)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("outside manifest ownership", proc.stderr)

    def test_worker_receives_the_verified_route_snapshot_not_a_mutable_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"route":"original"}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            worker = (
                "import os, pathlib; "
                "pathlib.Path(os.environ['ASTRA_ROUTE_ORIGINAL_FILE']).write_text('{\\\"route\\\":\\\"replaced\\\"}'); "
                "assert pathlib.Path(os.environ['ASTRA_ROUTE_FILE']).read_text() == '{\\\"route\\\":\\\"original\\\"}'; "
                "pathlib.Path('owned.txt').write_text('changed\\n')"
            )
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, worker)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual((artifacts / "route.json").read_text(encoding="utf-8"), '{"route":"original"}')

    def test_retries_one_failed_worker_in_a_fresh_worktree_and_preserves_failure_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, "raise SystemExit(7)")
            self.assertEqual(proc.returncode, 1)
            metadata = json.loads((artifacts / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["attempts"], 2)
            self.assertEqual(metadata["base_sha"], base_sha)
            self.assertEqual(metadata["route_file"], str(route.resolve()))
            self.assertTrue((artifacts / "route.json").exists())
            attempts = [Path(entry["worktree"]) for entry in metadata["attempt_results"]]
            self.assertEqual(len(set(attempts)), 2)
            self.assertTrue(all(path.exists() for path in attempts))

    def test_cleans_the_first_failed_worktree_after_a_successful_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            worker = "import os, pathlib, sys; sys.exit(7) if os.environ['ASTRA_ATTEMPT'] == '1' else pathlib.Path('owned.txt').write_text('changed\\n')"
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, worker)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            metadata = json.loads((artifacts / "metadata.json").read_text(encoding="utf-8"))
            self.assertFalse(Path(metadata["attempt_results"][0]["worktree"]).exists())
            self.assertTrue((artifacts / "attempt-1.log").exists())

    def test_worktree_creation_failure_still_preserves_attempt_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo, route, manifest, artifacts = root / "repo", root / "route.json", root / "manifest.json", root / "artifacts"
            repo.mkdir()
            base_sha = self.init_repo(repo)
            route.write_text('{"schema_version": 3}', encoding="utf-8")
            manifest.write_text('{"owned_files":["owned.txt"]}', encoding="utf-8")
            artifacts.mkdir()
            (artifacts / "attempt-1").write_text("block worktree", encoding="utf-8")
            proc = self.invoke(repo, route, manifest, base_sha, artifacts, "raise SystemExit(7)")
            self.assertEqual(proc.returncode, 1)
            self.assertTrue((artifacts / "attempt-1.log").exists())
            self.assertTrue((artifacts / "attempt-2.log").exists())

    def test_plugin_adapter_copies_match_the_bundle_root(self):
        source = (ROOT / "scripts" / "astra_adapter.py").read_bytes()
        for plugin in ("codex", "claude", "antigravity"):
            with self.subTest(plugin=plugin):
                target = ROOT / "plugins" / f"{plugin}-model-effort-router" / "scripts" / "astra_adapter.py"
                self.assertEqual(target.read_bytes(), source)


if __name__ == "__main__":
    unittest.main()
