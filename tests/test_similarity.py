import json
from dataclasses import replace
from pathlib import Path

import pytest

from school_lab.adapters.dto import parse_submission
from school_lab.analyzers.similarity import TOKEN_VERSION, token_features
from school_lab.application.similarity import ComparisonService
from school_lab.domain.errors import AnalysisFailure
from school_lab.domain.models import Assignment
from school_lab.domain.similarity import jaccard
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
