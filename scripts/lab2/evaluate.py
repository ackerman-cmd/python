"""Fit review thresholds on tune families and report held-out quality."""

import argparse
import json
from collections.abc import Iterable
from itertools import combinations
from pathlib import Path
from typing import TypedDict, cast

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.sources import JsonlSource
from school_lab.analyzers.basic import normalize_newlines
from school_lab.analyzers.similarity import AST_VERSION, TOKEN_VERSION, ast_features, token_features
from school_lab.application.similarity import ComparisonService
from school_lab.bootstrap import build_application, load_assignments
from school_lab.domain.hashing import stable_hash
from school_lab.domain.models import Submission

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/lab2"


class Provenance(TypedDict):
    submission_id: str
    assignment_id: str
    family_id: str
    split: str
    parent_id: str | None


class Label(TypedDict):
    left: str
    right: str
    assignment_id: str
    split: str
    derivation_relation: bool
    template_only: bool


type Observation = tuple[Label, float | None]


def load_rows(path: Path) -> Iterable[object]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def validate_labels(
    provenance: list[Provenance], labels: list[Label], accepted: tuple[Submission, ...]
) -> None:
    by_id = {item["submission_id"]: item for item in provenance}
    submissions = {item.submission_id: item for item in accepted}
    if len(by_id) != len(provenance) or submissions.keys() != by_id.keys():
        raise ValueError("Divergent provenance and submissions")
    splits: dict[str, set[str]] = {name: set() for name in ("tune", "eval")}
    for identifier, row in by_id.items():
        if (
            row["split"] not in splits
            or submissions[identifier].assignment_id != row["assignment_id"]
        ):
            raise ValueError("Invalid provenance")
        splits[row["split"]].add(row["family_id"])
        if parent_id := row["parent_id"]:
            parent = by_id[parent_id]
            if any(row[key] != parent[key] for key in ("family_id", "split", "assignment_id")):
                raise ValueError("Provenance parent outside its family, split or assignment")
    if any(left & right for left, right in combinations(splits.values(), 2)):
        raise ValueError("Family leakage between tune and eval")
    code_splits: dict[str, tuple[str, str]] = {}
    for identifier, item in submissions.items():
        code = normalize_newlines(item.code)
        if not code.strip():
            continue
        split = by_id[identifier]["split"]
        earlier_id, earlier_split = code_splits.setdefault(stable_hash(code), (identifier, split))
        if split != earlier_split:
            raise ValueError(f"Code leakage between tune and eval: {earlier_id}, {identifier}")
    seen: set[frozenset[str]] = set()
    for label in labels:
        key = frozenset((label["left"], label["right"]))
        if len(key) != 2 or key in seen:
            raise ValueError("Duplicate or self pair")
        seen.add(key)
        a, b = by_id[label["left"]], by_id[label["right"]]
        if any(a[key] != label[key] or b[key] != label[key] for key in ("split", "assignment_id")):
            raise ValueError("Pair crosses split or assignment")
        if label["derivation_relation"] != (a["family_id"] == b["family_id"]):
            raise ValueError("Label disagrees with provenance")
        if label["template_only"] and label["derivation_relation"]:
            raise ValueError("Template-only pair cannot be derived in this corpus")


def metrics(rows: list[Observation], threshold: float) -> dict[str, float | int]:
    tp = tn = fp = fn = undefined = undefined_positive = 0
    for label, score in rows:
        actual = label["derivation_relation"]
        if score is None:
            undefined += 1
            undefined_positive += actual
        predicted = score is not None and score >= threshold
        tp += actual and predicted
        fp += not actual and predicted
        fn += actual and not predicted
        tn += not actual and not predicted
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "undefined": undefined,
        "undefined_positive": undefined_positive,
        "undefined_rate": undefined / len(rows),
    }


def tune_threshold(rows: list[Observation]) -> float:
    observed = {score for _, score in rows if score is not None and score > 0}
    return max(observed | {1.0}, key=lambda x: (metrics(rows, x)["f1"], x))


def evaluate(data: Path) -> dict[str, object]:
    application = build_application()
    summary = import_source(JsonlSource(data / "submissions.jsonl"), application.acceptance_adapter)
    if summary.errors or summary.duplicate:
        raise ValueError(f"Invalid corpus: {summary.to_dict()}")
    submissions = application.repository.all()
    assignments = load_assignments(data / "assignments.json")
    provenance = [cast(Provenance, row) for row in load_rows(data / "provenance.jsonl")]
    labels = [cast(Label, row) for row in load_rows(data / "pairs.jsonl")]
    validate_labels(provenance, labels, submissions)
    results = {}
    for method, extract in ((TOKEN_VERSION, token_features), (AST_VERSION, ast_features)):
        service = ComparisonService(submissions, assignments, method=method, extractor=extract)
        rows: dict[str, list[Observation]] = {"tune": [], "eval": []}
        for label in labels:
            pair = service.compare(label["left"], label["right"])
            rows[label["split"]].append((label, pair.score))
        threshold = tune_threshold(rows["tune"])
        details = []
        for label, score in rows["eval"]:
            predicted = score is not None and score >= threshold
            details.append({**label, "score": score, "review_required": predicted})
        results[method] = {
            "threshold": threshold,
            "tune": metrics(rows["tune"], threshold),
            "eval": metrics(rows["eval"], threshold),
            "eval_pairs": details,
        }
    return {
        "corpus_hash": stable_hash(
            {
                name: (data / name).read_text(encoding="utf-8")
                for name in (
                    "submissions.jsonl",
                    "provenance.jsonl",
                    "pairs.jsonl",
                    "assignments.json",
                )
            }
        ),
        "submissions": len(submissions),
        "pairs": len(labels),
        "template_only_pairs": sum(label["template_only"] for label in labels),
        "families": {
            split: sorted({row["family_id"] for row in provenance if row["split"] == split})
            for split in ("tune", "eval")
        },
        "undefined_policy": "No review flag; counted as negative and reported separately.",
        "split_policy": "Disjoint families and no identical nonblank code across splits.",
        "threshold_policy": (
            "Maximize tune F1 over positive observed scores and 1; ties prefer higher."
        ),
        "methods": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/lab2/quality.json")
    args = parser.parse_args()
    data = json.dumps(evaluate(args.data), ensure_ascii=False, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(data, encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
