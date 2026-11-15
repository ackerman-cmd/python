"""Generate a small, deterministic synthetic corpus (no student data)."""

import json
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/lab2"
ASSIGNMENT = "lab2-aggregate"
TEMPLATE = "from typing import Iterable\n"
FAMILIES = (
    (
        "positive-squares",
        "sum(x*x for x in values if x > 0)",
        "sum(map(lambda z: z**2, filter(lambda z: z > 0, values)))",
    ),
    (
        "count-even",
        "sum(1 for x in values if x % 2 == 0)",
        "len(list(filter(lambda z: not z % 2, values)))",
    ),
    ("maximum", "max(values, default=0)", "next(iter(sorted(values, reverse=True)), 0)"),
    ("unique-sum", "sum(set(values))", "sum(dict.fromkeys(values))"),
    (
        "negative-count",
        "sum(1 for x in values if x < 0)",
        "len(list(filter(lambda z: z < 0, values)))",
    ),
    ("absolute-sum", "sum(abs(x) for x in values)", "sum(map(abs, values))"),
    (
        "negative-squares",
        "sum(x*x for x in values if x < 0)",
        "sum(map(lambda z: z**2, filter(lambda z: z < 0, values)))",
    ),
    (
        "count-odd",
        "sum(1 for x in values if x % 2 == 1)",
        "len(list(filter(lambda z: z % 2, values)))",
    ),
    ("minimum", "min(values, default=0)", "next(iter(sorted(values)), 0)"),
    ("unique-count", "len(set(values))", "len(dict.fromkeys(values))"),
    (
        "positive-count",
        "sum(1 for x in values if x > 0)",
        "len(list(filter(lambda z: z > 0, values)))",
    ),
    ("cube-sum", "sum(x**3 for x in values)", "sum(map(lambda z: z**3, values))"),
)


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8"
    )


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    submissions: list[dict[str, object]] = []
    provenance: list[dict[str, object]] = []
    pairs: list[dict[str, object]] = []

    def add(family: str, split: str, assignment_id: str, kind: str, code: str) -> str:
        identifier = f"{family}-{kind}"
        submissions.append(
            {
                "schema_version": 1,
                "submission_id": identifier,
                "student_id": f"synthetic-{len(submissions) + 1:03}",
                "assignment_id": assignment_id,
                "submitted_at": "2026-10-01T12:00:00+03:00",
                "text": "Синтетический пример для проверки методов сходства.",
                "code": code,
                "template_id": ("aggregate-template" if code.startswith(TEMPLATE) else None),
                "ai_declaration": {
                    "used": False,
                    "tool": None,
                    "purpose": None,
                    "verified_by_student": True,
                },
            }
        )
        provenance.append(
            {
                "submission_id": identifier,
                "assignment_id": assignment_id,
                "family_id": family,
                "split": split,
                "variant": kind,
                "origin": "synthetic-authored-for-lab2",
                "parent_id": f"{family}-original"
                if kind not in {"original", "template-only"}
                else None,
            }
        )
        return identifier

    def pair(
        left: str, right: str, split: str, assignment_id: str, derived: bool, template_only: bool
    ) -> None:
        pairs.append(
            {
                "left": left,
                "right": right,
                "assignment_id": assignment_id,
                "split": split,
                "derivation_relation": derived,
                "template_only": template_only,
            }
        )

    for split, group in (("tune", FAMILIES[:6]), ("eval", FAMILIES[6:])):
        originals = []
        for family, expression, rewrite in group:
            original = TEMPLATE + f"\ndef solve(values):\n    return {expression}\n"
            renamed = expression.replace("values", "items")
            entries = [
                add(family, split, ASSIGNMENT, "original", original),
                add(family, split, ASSIGNMENT, "copy", original),
                add(
                    family,
                    split,
                    ASSIGNMENT,
                    "format",
                    TEMPLATE
                    + f"\ndef solve( values ):\n    # aggregate\n    return {expression}\n",
                ),
                add(
                    family,
                    split,
                    ASSIGNMENT,
                    "rename",
                    TEMPLATE + f"\ndef compute(items):\n    return {renamed}\n",
                ),
                add(
                    family,
                    split,
                    ASSIGNMENT,
                    "rewrite",
                    f"def solve(values):\n    result = {rewrite}\n    return result\n",
                ),
            ]
            originals.append(entries[0])
            for other in entries[1:]:
                pair(entries[0], other, split, ASSIGNMENT, True, False)

        for left, right in combinations(originals, 2):
            pair(left, right, split, ASSIGNMENT, False, False)

        # Structurally unrelated snippets sharing only the scaffolding.
        template_ids = [
            add(f"{split}-template-{i}", split, "lab2-template", "template-only", TEMPLATE + body)
            for i, body in enumerate(("", "pass\n", "42\n", "# no implementation\n"))
        ]
        for left, right in combinations(template_ids, 2):
            pair(left, right, split, "lab2-template", False, True)

    write_jsonl(DATA / "submissions.jsonl", submissions)
    write_jsonl(DATA / "provenance.jsonl", provenance)
    write_jsonl(DATA / "pairs.jsonl", pairs)
    assignments = [
        {"assignment_id": identifier, "allowed_template": TEMPLATE, "requirements": []}
        for identifier in (ASSIGNMENT, "lab2-template")
    ]
    (DATA / "assignments.json").write_text(
        json.dumps(assignments, indent=2) + "\n", encoding="utf-8"
    )
    without_template = [{**assignment, "allowed_template": ""} for assignment in assignments]
    (DATA / "assignments-without-template.json").write_text(
        json.dumps(without_template, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
