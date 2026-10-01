"""Independent review input/output (spec 16): git diff, prompt, verdict parsing."""
import json
import re
import subprocess

DIFF_CAP = 200_000  # bytes; larger diffs are replaced by a file list
FINDINGS_MAX = 6000  # chars of review text handed back to the implement session
_VERDICT = re.compile(r"^\s*VERDICT:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_FINDINGS = re.compile(r"^\s*FINDINGS:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE)
_VERDICTS = ("approved", "changes_requested")


def parse_verdict(text):
    """(verdict, findings): the last well-formed VERDICT line wins; anything else is 'unknown'."""
    found = [m.group(1).lower() for m in _VERDICT.finditer(text or "")]
    verdict = found[-1] if found and found[-1] in _VERDICTS else "unknown"
    counts = _FINDINGS.findall(text or "")
    return verdict, (int(counts[-1]) if counts and verdict != "unknown" else None)


def _git(args, cwd):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace",
                       stdin=subprocess.DEVNULL, timeout=60)
    return p.returncode, p.stdout


def git_diff(cwd):
    """{is_repo, diff, files, untracked}. Read-only: never initialises or stages anything."""
    try:
        if _git(["rev-parse", "--is-inside-work-tree"], cwd)[0] != 0:
            return {"is_repo": False}
        base = ["HEAD"] if _git(["rev-parse", "--verify", "-q", "HEAD"], cwd)[0] == 0 else []
        return {"is_repo": True, "diff": _git(["diff", *base], cwd)[1],
                "files": _git(["diff", "--name-only", *base], cwd)[1].split("\n")[:-1],
                "untracked": _git(["ls-files", "--others", "--exclude-standard"], cwd)[1].split("\n")[:-1]}
    except (OSError, subprocess.SubprocessError):
        return {"is_repo": False}


def _diff_section(d):
    untracked = "\n".join(d.get("untracked") or [])
    note = f"\nUntracked files (read them from the workspace):\n{untracked}\n" if untracked else ""
    if len(d["diff"].encode("utf-8", "replace")) > DIFF_CAP:
        files = "\n".join(d.get("files") or [])
        return f"The diff is too large to include. Changed files (inspect them yourself):\n{files}\n{note}"
    return f"git diff:\n{d['diff'] or '(no tracked changes)'}\n{note}"


def review_prompt(request, diff, gate):
    return (f"Independently review this change against the request. Check requirements met, omissions, logic "
            f"errors, regressions, edge cases, security, needless changes, missing tests. Do not edit files. Do the "
            f"review yourself in this session: do not spawn subagents or delegate to other agents.\n\n"
            f"Request:\n{request}\n\n{_diff_section(diff)}\nTest Gate result:\n{json.dumps(gate, indent=2)}\n\n"
            "End your answer with exactly these two lines:\nVERDICT: approved|changes_requested\nFINDINGS: <n>")
