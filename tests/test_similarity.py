import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from school_lab.adapters.dto import parse_submission
from school_lab.analyzers.similarity import TOKEN_VERSION, ast_features, token_features
from school_lab.application.similarity import INDEX_VERSION, ComparisonService
from school_lab.domain.errors import AnalysisFailure
from school_lab.domain.models import Assignment
from school_lab.domain.similarity import CodeFeatures, jaccard
from school_lab.interfaces.cli import main


@pytest.mark.parametrize(
    "other, expected",
    [
        ("total = 1 + 2\n", 1.0),
        ("total=1+2 # comment\n", 1.0),
        ("renamed = 1 + 2\n", 0.5),
        ("print('hello')\n", 0.0),
        ("print(\n", None),
        ("total total total\n", None),
    ],
)
def test_token_similarity_expected_scores(other: str, expected: float | None) -> None:
    result = jaccard(token_features("total = 1 + 2\n", ""), token_features(other, ""))
    assert result == expected


def test_exact_template_is_reported_separately_and_does_not_bridge_gaps() -> None:
    template = "from typing import Iterable\n"
    left = token_features("pass\n" + template + "pass\npass\n", template)
    right = token_features(template, template)
    assert left.template == ((2, 2),) and right.template == ((1, 1),)
    assert not left.spans and not right.spans
    assert jaccard(left, right) is None


def test_top_k_filters_students_and_assignments_and_reports_evidence(
    payload: dict[str, object],
) -> None:
    code = "from typing import Iterable\n\nvalue = 1 + 2\n"
    query = parse_submission({**payload, "code": code})
    version = replace(query, submission_id="other-version")
    copy = replace(query, submission_id="copy", student_id="different")
    extra = replace(copy, submission_id="z-copy")
    foreign = replace(copy, submission_id="foreign", assignment_id="foreign-assignment")
    blank = replace(copy, submission_id="blank", code="pass\n")
    kwargs = {
        query.assignment_id: Assignment(query.assignment_id, "from typing import Iterable\n", ()),
        foreign.assignment_id: Assignment(foreign.assignment_id, "", ()),
    }
    service = ComparisonService(
        iter([foreign, extra, blank, query, version, copy]),
        kwargs,
        method=TOKEN_VERSION,
        extractor=token_features,
    )
    result = service.top_k(query.submission_id, k=2)
    assert result.comparisons == 3 and result.same_student_versions == ("other-version",)
    assert [pair.right.submission_id for pair in result.candidates] == ["copy", "z-copy"]
    pair = result.candidates[0]
    assert pair.score == 1 and pair.review_required
    assert pair.left.matched_lines == pair.right.matched_lines == ((3, 3),)
    assert pair.left.template_lines == pair.right.template_lines == ((1, 1),)
    with pytest.raises(AnalysisFailure, match="разных студентов"):
        service.compare(query.submission_id, version.submission_id)
    with pytest.raises(AnalysisFailure, match="разным заданиям"):
        service.compare(query.submission_id, foreign.submission_id)


def test_cli_similarity_runs_streaming_import(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "similarity",
                str(data_dir / "invalid_submissions.jsonl"),
                "sub-001",
                "--assignments",
                str(data_dir / "assignments.json"),
            ]
        )
        == 1
    )
    result = json.loads(capsys.readouterr().out)
    assert result["comparisons"] == 1
    assert result["candidates"][0]["right"]["submission_id"] == "sub-002"
    assert len(result["import"]["errors"]) == 3


def test_ast_normalizes_names_preserves_evidence_and_rejects_invalid_code() -> None:
    template = "from typing import Iterable\n"
    a = ast_features(template + "def solve(values):\n    return values[0]\n", template)
    b = ast_features("def renamed(items):\n    return items[0]\n", template)
    invalid = ast_features("def (\n", template)
    assert jaccard(a, b) == 1
    assert a.template == ((1, 1),)
    assert all(2 <= lo <= hi <= 3 for lo, hi in a.spans.values())
    assert jaccard(a, invalid) is None
    assert invalid.diagnostic and invalid.diagnostic.startswith("SyntaxError (строка 1)")


@pytest.mark.parametrize("extract", [token_features, ast_features])
@pytest.mark.parametrize(
    "code, error",
    [
        ("return 1 + 2\n", "'return' outside function"),
        ("break\nprint(1)\n", "'break' outside loop"),
        ("def f(x, x):\n    return x\n", "duplicate argument"),
    ],
)
def test_methods_reject_code_that_parses_but_does_not_compile(
    extract: Callable[[str, str], CodeFeatures], code: str, error: str
) -> None:
    invalid = extract(code, "")
    assert invalid.diagnostic and error in invalid.diagnostic
    assert "строка 1" in invalid.diagnostic
    assert not invalid.spans
    assert jaccard(invalid, invalid) is None


@pytest.mark.parametrize("extract", [token_features, ast_features])
@pytest.mark.parametrize("eol", ["\n", "\r\n", "\r"], ids=["lf", "crlf", "cr"])
def test_template_and_features_use_python_physical_lines(
    extract: Callable[[str, str], CodeFeatures], eol: str
) -> None:
    template = "from typing import Iterable"
    code = eol.join(('s = """before\u2028after"""', template, "x = 1 + 2", ""))
    result = extract(code, template + "\r\n")
    assert result.template == ((2, 2),)
    assert result.diagnostic is None
    assert {start for start, _ in result.spans.values()} == {1, 3}
    assert all(not lo <= 2 <= hi for lo, hi in result.spans.values())


@pytest.mark.parametrize("left_args, right_args", [("x, /", "*, x"), ("*, x=1, y", "*, x, y=1")])
def test_ast_preserves_argument_roles_and_default_positions(
    left_args: str, right_args: str
) -> None:
    a = ast_features(f"def f(\n    {left_args}\n):\n    return x\n", "")
    b = ast_features(f"def f(\n    {right_args}\n):\n    return x\n", "")
    score = jaccard(a, b)
    assert score is not None and 0 < score < 1
    assert a.diagnostic is None and b.diagnostic is None
    assert [span for feature, span in a.spans.items() if feature[0] == "arguments"] == [(1, 2)]


@pytest.mark.parametrize(
    "code, status, has_diagnostic",
    [
        ("return 1 + 2\n", "invalid_code", True),
        ("# comment only\n", "insufficient_features", False),
        ("x = 1 + 2\n", "ready", False),
    ],
)
def test_indexed_cli_reports_query_status_even_when_no_candidates(
    payload: dict[str, object],
    tmp_path: Path,
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    code: str,
    status: str,
    has_diagnostic: bool,
) -> None:
    path = tmp_path / "submissions.jsonl"
    rows = [
        {**payload, "code": code},
        {**payload, "submission_id": "independent", "student_id": "other", "code": "print(5)"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    assert (
        main(
            [
                "similarity",
                str(path),
                str(payload["submission_id"]),
                "--assignments",
                str(data_dir / "assignments.json"),
                "--indexed",
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["schema_version"] == 2
    assert result["comparisons"] == 0 and result["candidates"] == []
    assert result["query"]["submission_id"] == payload["submission_id"]
    assert result["query"]["status"] == status
    assert bool(result["query"]["diagnostic"]) is has_diagnostic


def test_candidate_index_omits_zeros_but_keeps_positive_results(
    payload: dict[str, object],
) -> None:
    a = parse_submission({**payload, "code": "number = 5 * 2\n"})
    b = replace(a, submission_id="copy", student_id="b")
    c = replace(a, submission_id="unrelated", student_id="c", code="print('hi')\n")
    specs = {a.assignment_id: Assignment(a.assignment_id, "", ())}
    full = ComparisonService([a, b, c], specs, method=TOKEN_VERSION, extractor=token_features)
    indexed = ComparisonService(
        [a, b, c], specs, method=TOKEN_VERSION, extractor=token_features, indexed=True
    )
    scan, filtered = full.top_k(a.submission_id), indexed.top_k(a.submission_id)
    assert scan.comparisons == 2 and filtered.comparisons == 1
    assert filtered.index_version == INDEX_VERSION
    assert filtered.candidates == scan.candidates[:1]
    assert scan.candidates[1].score == 0


def test_added_template_changes_config_hash_and_removes_template_only_score(
    payload: dict[str, object],
) -> None:
    code = "from typing import Iterable\n"
    a = parse_submission({**payload, "code": code})
    b = replace(a, submission_id="student-b", student_id="b")
    assignment = Assignment(a.assignment_id, "", ())
    before = ComparisonService(
        [a, b], {a.assignment_id: assignment}, method=TOKEN_VERSION, extractor=token_features
    )
    after = ComparisonService(
        [a, b],
        {a.assignment_id: replace(assignment, allowed_template=code)},
        method=TOKEN_VERSION,
        extractor=token_features,
        config_version="2",
    )
    old, new = before.top_k(a.submission_id), after.top_k(a.submission_id)
    assert old.config_hash != new.config_hash
    assert old.candidates[0].score == 1 and new.candidates[0].score is None
    assert new.candidates[0].right.template_lines == ((1, 1),)


def test_similarity_service_rejects_unknown_submissions_and_conflicting_ids(
    payload: dict[str, object],
) -> None:
    a = parse_submission(payload)
    specs = {a.assignment_id: Assignment(a.assignment_id, "", ())}
    service = ComparisonService([a, a], specs, method=TOKEN_VERSION, extractor=token_features)
    with pytest.raises(AnalysisFailure, match="не найдена"):
        service.top_k("missing")
    with pytest.raises(AnalysisFailure, match="положительным"):
        service.top_k(a.submission_id, k=0)
    with pytest.raises(AnalysisFailure, match="Порог"):
        service.top_k(a.submission_id, threshold=float("nan"))
    with pytest.raises(AnalysisFailure, match="Конфликт"):
        ComparisonService(
            [a, replace(a, code="pass")], specs, method=TOKEN_VERSION, extractor=token_features
        )
    with pytest.raises(AnalysisFailure, match="Неизвестное задание"):
        ComparisonService([a], {}, method=TOKEN_VERSION, extractor=token_features)
