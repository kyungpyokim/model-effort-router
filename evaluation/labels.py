"""Independent label files -> labeled corpus (guide §4). Labels live apart from the corpus so labelers never see
each other's work (or `proposed`) while labeling.

  python3 -m evaluation.labels sheet CORPUS OUT.tsv          blank sheet: id, task, paths + empty level/risk_flags/target
  python3 -m evaluation.labels merge CORPUS OUT LABELS...    add every label file (.jsonl or filled .tsv) to the cases

Label file rows: {id, labeler, level (L1..L5 or empty for no_route), risk_flags, target}. In a .tsv the labeler is
the file's `labeler` column and risk_flags are comma-separated. Merge validates through evaluation.cases.
"""
import csv
import json
import sys

from . import cases as corpus

TSV_FIELDS = ("id", "task", "paths", "labeler", "level", "risk_flags", "target", "note")


def write_sheet(corpus_path, out_path, labeler=""):
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(TSV_FIELDS)
        for c in corpus.load(corpus_path):
            w.writerow([c["id"], c["task"], ",".join(c["paths"]), labeler, "", "", "", ""])


def read_labels(path):
    if path.endswith(".tsv"):
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f, delimiter="\t"))
        return [{"id": r["id"], "labeler": (r.get("labeler") or "").strip(), "level": (r.get("level") or "").strip() or None,
                 "risk_flags": [x.strip() for x in (r.get("risk_flags") or "").split(",") if x.strip()],
                 "target": (r.get("target") or "").strip()} for r in rows]
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def merge(corpus_path, label_paths):
    """Cases with every given label added; a case reaching 2 labels becomes `labeled`. Raises CorpusError."""
    rows = corpus.load(corpus_path)
    by_id = {r["id"]: r for r in rows}
    for path in label_paths:
        for lab in read_labels(path):
            if lab["id"] not in by_id:
                raise corpus.CorpusError(f"{path}: unknown case id {lab['id']!r}")
            case = by_id[lab["id"]]
            case["labels"] = case["labels"] + [{k: lab[k] for k in ("labeler", "level", "risk_flags", "target")}]
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k != "proposed"} if r["labels"] else r  # proposed never leaks into labeled data
        if r["status"] == "draft" and len(r["labels"]) >= 2:
            r["status"] = "labeled"
        out.append(corpus.validate_case(r))
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if len(argv) == 3 and argv[0] == "sheet":
            write_sheet(argv[1], argv[2])
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
