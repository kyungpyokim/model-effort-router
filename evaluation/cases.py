"""Routing Corpus format, loader and labeler agreement (spec 22.1). JSONL, one case per line.

case: {id, task, paths?, labels?, status, final?, proposed?, note?}
label/final/proposed: {level, risk_flags, target}; labels also carry `labeler`.
Drafts carry only `proposed` (the author's suggestion) and are NOT ground truth.
Usage: python3 -m evaluation.cases FILE   (validate + agreement report)
"""
import json
import sys

from model_effort_router.difficulty.decision import RISK_FLAGS

# Retained solely to read the frozen historical L1-L5 corpus; the active router has no level API.
LEVELS = ("L1", "L2", "L3", "L4", "L5")
NO_ROUTE, ROUTE, PLAN_ONLY, REVIEW_ONLY = "no_route", "route", "plan_only", "review_only"

TARGETS = (ROUTE, PLAN_ONLY, REVIEW_ONLY, NO_ROUTE)
STATUSES = ("draft", "labeled", "adjudicated", "pilot")  # pilot: author-set `final`, run-only, never scored as corpus
FIELDS = {"id", "task", "paths", "labels", "status", "final", "proposed", "note"}


class CorpusError(ValueError):
    pass


def _check_verdict(obj, where, *, labeler=False):
    if not isinstance(obj, dict):
        raise CorpusError(f"{where}: must be an object")
    if labeler and not (isinstance(obj.get("labeler"), str) and obj["labeler"].strip()):
        raise CorpusError(f"{where}: labeler must be a non-empty string")
    target, level, flags = obj.get("target"), obj.get("level"), obj.get("risk_flags", [])
    if target not in TARGETS:
        raise CorpusError(f"{where}: target must be one of {TARGETS}, got {target!r}")
    if target == NO_ROUTE and level is not None:
        raise CorpusError(f"{where}: level must be null when target is no_route")
    if target != NO_ROUTE and level not in LEVELS:
        raise CorpusError(f"{where}: level must be one of {LEVELS}, got {level!r}")
    if not isinstance(flags, list) or any(f not in RISK_FLAGS for f in flags):
        raise CorpusError(f"{where}: unknown risk flag in {flags!r} (allowed: {RISK_FLAGS})")
    return {"level": level, "risk_flags": list(flags), "target": target,
            **({"labeler": obj["labeler"]} if labeler else {})}


def validate_case(row):
    """Returns a normalized copy or raises CorpusError."""
    if not isinstance(row, dict):
        raise CorpusError("case must be an object")
    where = f"case {row.get('id')!r}"
    unknown = set(row) - FIELDS
    if unknown:
        raise CorpusError(f"{where}: unknown field(s) {sorted(unknown)}")
    if not (isinstance(row.get("id"), str) and row["id"].strip()):
        raise CorpusError("id must be a non-empty string")
    if not (isinstance(row.get("task"), str) and row["task"].strip()):
        raise CorpusError(f"{where}: task must be a non-empty string")
    paths = row.get("paths", [])
    if not isinstance(paths, list) or any(not isinstance(p, str) for p in paths):
        raise CorpusError(f"{where}: paths must be a list of strings")
    status = row.get("status")
    if status not in STATUSES:
        raise CorpusError(f"{where}: status must be one of {STATUSES}, got {status!r}")
    labels = row.get("labels", [])
    if not isinstance(labels, list):
        raise CorpusError(f"{where}: labels must be a list")
    out = {**row, "paths": list(paths), "labels": [_check_verdict(line, f"{where} label", labeler=True) for line in labels]}
    if "proposed" in row:
        out["proposed"] = _check_verdict(row["proposed"], f"{where} proposed")
    if status == "draft":
        if labels:
            raise CorpusError(f"{where}: a draft must not carry labels (use `proposed`)")
    elif status == "pilot":
        pass
    elif len({line["labeler"] for line in out["labels"]}) != len(out["labels"]):
        raise CorpusError(f"{where}: labels need distinct labelers")
    elif len(labels) < 2:
        raise CorpusError(f"{where}: {status} needs labels from at least 2 labelers")
    if status in ("adjudicated", "pilot"):
        if "final" not in row:
            raise CorpusError(f"{where}: {status} needs `final`")
        out["final"] = _check_verdict(row["final"], f"{where} final")
    elif "final" in row:
        raise CorpusError(f"{where}: `final` only allowed when adjudicated or pilot")
    return out


def load(path):
    rows, seen = [], set()
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = validate_case(json.loads(line))
            except (ValueError, CorpusError) as exc:  # CorpusError is a ValueError
                raise CorpusError(f"{path} line {n}: {exc}") from None
            if row["id"] in seen:
                raise CorpusError(f"{path} line {n}: duplicate id {row['id']!r}")
            seen.add(row["id"])
            rows.append(row)
    return rows


def adjudicated(rows):
    return [r for r in rows if r["status"] == "adjudicated"]


def runnable(rows):
    """Cases the live runner may execute: adjudicated corpus cases plus pilot cases."""
    return [r for r in rows if r["status"] in ("adjudicated", "pilot")]


def _distance(labels):
    levels = [line["level"] for line in labels]
    if None in levels:
        return 0 if all(v is None for v in levels) else 1  # no_route vs route is a discussion item
    idx = [LEVELS.index(v) for v in levels]
    return max(idx) - min(idx)


def agreement(rows):
    """1-level diff (or differing flags/target) -> discuss; >=2 levels -> revise the guide, then relabel."""
    discuss, revise, exact, compared = [], [], 0, 0
    for r in rows:
        labels = r.get("labels", [])
        if len(labels) < 2:
            continue
        compared += 1
        dist = _distance(labels)
        same_meta = len({(tuple(sorted(line["risk_flags"])), line["target"]) for line in labels}) == 1
        if dist >= 2:
            revise.append(r["id"])
        elif dist == 1 or not same_meta:
            discuss.append(r["id"])
        else:
            exact += 1
    return {"compared": compared, "exact_agree": exact, "discuss": discuss, "revise_guide": revise}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        rows = load(argv[0])
    except (CorpusError, OSError) as exc:
        print(f"invalid corpus: {exc}", file=sys.stderr)
        return 1
    by_status = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    print(json.dumps({"cases": len(rows), "by_status": by_status, "agreement": agreement(rows)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
