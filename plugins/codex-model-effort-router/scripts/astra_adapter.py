#!/usr/bin/env python3
"""Run one already-routed worker command in an isolated Git worktree."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


class ContractError(ValueError):
    pass


WORKER_INPUT_FILES = {".astra-route.json", ".astra-manifest.json"}


def git(repo: Path, *args: str, capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, capture_output=capture_output)


def owned_files(manifest_bytes: bytes) -> set[str]:
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ContractError("caller manifest is invalid") from exc
    files = manifest.get("owned_files") if isinstance(manifest, dict) else None
    if not isinstance(files, list) or not files or not all(isinstance(path, str) for path in files):
        raise ContractError("worker manifest must declare non-empty owned_files")
    normalised: list[str] = []
    for item in files:
        path = Path(item)
        if path.is_absolute() or ".." in path.parts:
            raise ContractError("worker manifest has invalid owned file")
        name = path.as_posix()
        if name in {"", "."}:
            raise ContractError("worker manifest has invalid owned file")
        normalised.append(name)
    if len(normalised) != len(set(normalised)):
        raise ContractError("duplicate owned file")
    return set(normalised)


def changed_files(worktree: Path, base_sha: str) -> set[str]:
    tracked = git(worktree, "diff", "--name-only", base_sha, capture_output=True).stdout.splitlines()
    untracked = git(worktree, "ls-files", "--others", "--exclude-standard", capture_output=True).stdout.splitlines()
    return {path for path in [*tracked, *untracked] if path and path not in WORKER_INPUT_FILES}


def validate_changes(worktree: Path, base_sha: str, ownership: set[str]) -> None:
    unowned = changed_files(worktree, base_sha) - ownership
    if unowned:
        raise ContractError(f"changed files outside manifest ownership: {', '.join(sorted(unowned))}")


def verify_worker_inputs(route_path: Path, route_sha256: str, manifest_path: Path, manifest_sha256: str) -> None:
    if hashlib.sha256(route_path.read_bytes()).hexdigest() != route_sha256 or hashlib.sha256(manifest_path.read_bytes()).hexdigest() != manifest_sha256:
        raise ContractError("worker input digest changed")


def preserve_inputs(artifact_dir: Path, route_bytes: bytes, manifest_bytes: bytes) -> None:
    (artifact_dir / "route.json").write_bytes(route_bytes)
    (artifact_dir / "manifest.json").write_bytes(manifest_bytes)


def write_metadata(path: Path, *, route_file: Path, route_sha256: str, manifest_file: Path, manifest_sha256: str, base_sha: str, attempt_results: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "route_file": str(route_file),
                "route_sha256": route_sha256,
                "manifest_file": str(manifest_file),
                "manifest_sha256": manifest_sha256,
                "base_sha": base_sha,
                "attempts": len(attempt_results),
                "attempt_results": attempt_results,
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def run(repo: Path, route_file: Path, route_sha256: str, manifest_file: Path, manifest_sha256: str, base_sha: str, artifact_dir: Path, worker_command: list[str]) -> int:
    route_file = route_file.resolve()
    manifest_file = manifest_file.resolve()
    repo = repo.resolve()
    artifact_dir = artifact_dir.resolve()
    route_bytes = route_file.read_bytes()
    manifest_bytes = manifest_file.read_bytes()
    if hashlib.sha256(route_bytes).hexdigest() != route_sha256:
        raise ContractError("route digest mismatch")
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise ContractError("manifest digest mismatch")
    ownership = owned_files(manifest_bytes)
    try:
        fixed_base = git(repo, "rev-parse", "--verify", f"{base_sha}^{{commit}}", capture_output=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ContractError("base SHA is not a commit in the repository") from exc

    artifact_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for attempt in (1, 2):
        worktree = artifact_dir / f"attempt-{attempt}"
        log_path = artifact_dir / f"attempt-{attempt}.log"
        result = {"attempt": attempt, "worktree": str(worktree), "status": "failed", "worktree_created": False}
        log_path.write_text("", encoding="utf-8")
        try:
            git(repo, "worktree", "add", "--detach", str(worktree), fixed_base)
            result["worktree_created"] = True
            route_snapshot = worktree / ".astra-route.json"
            manifest_snapshot = worktree / ".astra-manifest.json"
            route_snapshot.write_bytes(route_bytes)
            manifest_snapshot.write_bytes(manifest_bytes)
            completed = subprocess.run(
                worker_command,
                cwd=worktree,
                text=True,
                capture_output=True,
                check=False,
                env={
                    **os.environ,
                    "ASTRA_ROUTE_FILE": str(route_snapshot),
                    "ASTRA_ROUTE_ORIGINAL_FILE": str(route_file),
                    "ASTRA_ROUTE_SHA256": route_sha256,
                    "ASTRA_BASE_SHA": fixed_base,
                    "ASTRA_ATTEMPT": str(attempt),
                    "ASTRA_MANIFEST_FILE": str(manifest_snapshot),
                },
            )
            log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
            verify_worker_inputs(route_snapshot, route_sha256, manifest_snapshot, manifest_sha256)
            if completed.returncode:
                raise ContractError(f"worker exited {completed.returncode}")
            validate_changes(worktree, fixed_base, ownership)
        except (OSError, subprocess.CalledProcessError, ContractError) as exc:
            result["error"] = str(exc)
            results.append(result)
            preserve_inputs(artifact_dir, route_bytes, manifest_bytes)
            write_metadata(artifact_dir / "metadata.json", route_file=route_file, route_sha256=route_sha256, manifest_file=manifest_file, manifest_sha256=manifest_sha256, base_sha=fixed_base, attempt_results=results)
            if attempt == 2:
                print(f"astra adapter failed: {exc}", file=sys.stderr)
                return 1
            continue
        result["status"] = "succeeded"
        results.append(result)
        preserve_inputs(artifact_dir, route_bytes, manifest_bytes)
        write_metadata(artifact_dir / "metadata.json", route_file=route_file, route_sha256=route_sha256, manifest_file=manifest_file, manifest_sha256=manifest_sha256, base_sha=fixed_base, attempt_results=results)
        return 0
    return 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--route-file", type=Path, required=True)
    parser.add_argument("--route-sha256", required=True)
    parser.add_argument("--manifest-file", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--worker-command", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args(argv)
    if not args.worker_command:
        parser.error("--worker-command requires a command")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        return run(args.repo, args.route_file, args.route_sha256, args.manifest_file, args.manifest_sha256, args.base_sha, args.artifact_dir, args.worker_command)
    except (OSError, ContractError) as exc:
        print(f"astra adapter rejected request: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
