"""Role/effort corpus loader and labeler agreement. Usage: python3 -m evaluation.cases FILE."""
import json
import sys

from model_effort_router.difficulty.decision import EFFORTS, ROLES

STATUSES = ("draft", "labeled", "adjudicated")
FIELDS = {"id", "task", "paths", "labels", "status", "final", "note"}


class CorpusError(ValueError):
    pass


def _check_verdict(obj, where, *, labeler=False):
    if not isinstance(obj, dict):
        raise CorpusError(f"{where}: must be an object")
    allowed = {"role", "effort"} | ({"labeler"} if labeler else set())
    unknown = set(obj) - allowed
    if unknown:
        raise CorpusError(f"{where}: unknown field(s) {sorted(unknown)}")
    if labeler and not (isinstance(obj.get("labeler"), str) and obj["labeler"].strip()):
        raise CorpusError(f"{where}: labeler must be a non-empty string")
    role, effort = obj.get("role"), obj.get("effort")
    if role not in ROLES:
        raise CorpusError(f"{where}: role must be one of {ROLES}, got {role!r}")
    if effort not in EFFORTS:
        raise CorpusError(f"{where}: effort must be one of {EFFORTS}, got {effort!r}")
    return {"role": role, "effort": effort,
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
    if status == "draft":
        if labels:
            raise CorpusError(f"{where}: a draft must not carry labels")
    elif len({line["labeler"] for line in out["labels"]}) != len(out["labels"]):
        raise CorpusError(f"{where}: labels need distinct labelers")
    elif len(labels) < 2:
        raise CorpusError(f"{where}: {status} needs labels from at least 2 labelers")
    if status == "adjudicated":
        if "final" not in row:
            raise CorpusError(f"{where}: {status} needs `final`")
        out["final"] = _check_verdict(row["final"], f"{where} final")
    elif "final" in row:
        raise CorpusError(f"{where}: `final` only allowed when adjudicated")
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


def agreement(rows):
    """Report unanimous exact agreement and cases with role or effort mismatches."""
    role_mismatches, effort_mismatches = [], []
    role_exact = effort_exact = joint_exact = compared = 0
    for r in rows:
        labels = r.get("labels", [])
        if len(labels) < 2:
            continue
        compared += 1
        role_ok = len({line["role"] for line in labels}) == 1
        effort_ok = len({line["effort"] for line in labels}) == 1
        role_exact += role_ok
        effort_exact += effort_ok
        joint_exact += role_ok and effort_ok
        if not role_ok:
            role_mismatches.append(r["id"])
        if not effort_ok:
            effort_mismatches.append(r["id"])
    return {"compared": compared, "role_exact": role_exact, "effort_exact": effort_exact,
            "joint_exact": joint_exact, "role_mismatches": role_mismatches,
            "effort_mismatches": effort_mismatches}


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
