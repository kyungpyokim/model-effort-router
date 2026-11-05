"""Independent label files -> labeled corpus (guide §4). Labels live apart so labelers never see each other's work.

  python3 -m evaluation.labels sheet [--tier] CORPUS OUT.tsv blank sheet: id, task, paths + empty role/effort
                                                             (--tier adds an empty `tier` column after effort)
  python3 -m evaluation.labels merge CORPUS OUT LABELS...    add every label file (.jsonl or filled .tsv) to the cases

Label file rows: {id, labeler, role, effort} or, with the optional tier axis, {id, labeler, role, effort, tier}.
In a .tsv the labeler is the file's `labeler` column; the header is either the base columns or the base columns
with `tier` after `effort`, and an empty tier cell means no tier.
Merge validates through evaluation.cases.
"""

import csv
import json
import sys

from . import cases as corpus

TSV_FIELDS = ("id", "task", "paths", "labeler", "role", "effort", "note")
TSV_FIELDS_TIER = ("id", "task", "paths", "labeler", "role", "effort", "tier", "note")


def write_sheet(corpus_path, out_path, labeler="", tier=False):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(TSV_FIELDS_TIER if tier else TSV_FIELDS)
        for c in corpus.load(corpus_path):
            w.writerow([c["id"], c["task"], ",".join(c["paths"]), labeler, "", "", *([""] if tier else []), ""])


def read_labels(path):
    if path.endswith(".tsv"):
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            has_tier = reader.fieldnames == list(TSV_FIELDS_TIER)
            if not has_tier and reader.fieldnames != list(TSV_FIELDS):
                expected = [list(TSV_FIELDS), list(TSV_FIELDS_TIER)]
                raise corpus.CorpusError(f"{path}: expected TSV columns {expected}, got {reader.fieldnames}")
            rows = list(reader)
        out = []
        for r in rows:
            lab = {
                "id": r["id"],
                "labeler": (r.get("labeler") or "").strip(),
                "role": (r.get("role") or "").strip(),
                "effort": (r.get("effort") or "").strip(),
            }
            if has_tier and (r.get("tier") or "").strip():
                lab["tier"] = r["tier"].strip()
            out.append(lab)
        return out
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def merge(corpus_path, label_paths):
    """Cases with every given label added; a case reaching 2 labels becomes `labeled`. Raises CorpusError."""
    rows = corpus.load(corpus_path)
    by_id = {r["id"]: r for r in rows}
    for path in label_paths:
        for lab in read_labels(path):
            allowed = {"id", "labeler", "role", "effort"}
            if not isinstance(lab, dict) or set(lab) not in (allowed, allowed | {"tier"}):
                fields = sorted(lab) if isinstance(lab, dict) else type(lab).__name__
                raise corpus.CorpusError(
                    f"{path}: label must contain exactly {sorted(allowed)} (+ optional tier), got {fields}"
                )
            if lab["id"] not in by_id:
                raise corpus.CorpusError(f"{path}: unknown case id {lab['id']!r}")
            case = by_id[lab["id"]]
            case["labels"] = case["labels"] + [{k: lab[k] for k in ("labeler", "role", "effort", "tier") if k in lab}]
    out = []
    for r in rows:
        if r["status"] == "draft" and len(r["labels"]) >= 2:
            r["status"] = "labeled"
        out.append(corpus.validate_case(r))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) in (3, 4) and argv[0] == "sheet" and (len(argv) == 3 or argv[1] == "--tier"):
            write_sheet(argv[-2], argv[-1], tier=len(argv) == 4)
        elif len(argv) >= 4 and argv[0] == "merge":
            rows = merge(argv[1], argv[3:])
            with open(argv[2], "w", encoding="utf-8") as f:
                f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
            print(json.dumps(corpus.agreement(rows), ensure_ascii=False, indent=2))
        else:
            print(__doc__)
            return 2
    except (corpus.CorpusError, OSError, KeyError, ValueError) as exc:
        print(f"labels: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
