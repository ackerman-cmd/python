from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Literal, cast

import pytest

from school_lab.adapters.dto import parse_submission
from school_lab.analyzers.basic import LengthAnalyzer, TemplateAnalyzer, template_ranges
from school_lab.analyzers.extensions import DeclarationAnalyzer, MissingExplanationAnalyzer
from school_lab.application.ports import Analyzer
from school_lab.application.registry import AnalyzerRegistry
from school_lab.application.reporting import make_report, validate_report
from school_lab.bootstrap import Application
from school_lab.domain.errors import AnalysisFailure
from school_lab.domain.hashing import config_hash
from school_lab.domain.models import AnalysisContext, AnalysisReport, Assignment, Evidence, Finding


@pytest.fixture(
    params=[LengthAnalyzer, TemplateAnalyzer, DeclarationAnalyzer, MissingExplanationAnalyzer]
)
def analyzer(request: pytest.FixtureRequest) -> Analyzer:
    result: Analyzer = request.param()
    return result


def test_common_analyzer_contract_and_semantic_repeatability(
    analyzer: Analyzer,
    payload: dict[str, object],
    context: AnalysisContext,
) -> None:
    submission = parse_submission(payload)
    original = asdict(submission)
    first = analyzer.analyze(submission, context)
    second = analyzer.analyze(submission, context)
    assert validate_report(first, submission, context) is first
    assert first.analyzer_id == analyzer.analyzer_id
    assert first.analyzer_version == analyzer.analyzer_version
    assert first.findings == second.findings
    assert first.submission_hash == second.submission_hash
    assert first.config_hash == second.config_hash
    assert first.report_id != second.report_id
    assert asdict(submission) == original


def test_length_counts_nonempty_original_lines(
    payload: dict[str, object], context: AnalysisContext
) -> None:
    payload.update(text="\n a \n\n b\n", code="\n# comment\n\npass\n")
    submission = parse_submission(payload)
    finding = LengthAnalyzer().analyze(submission, context).findings[0]
    assert finding.score is None and finding.kind == "rubric_feedback"
    assert "text=2, code=2" in finding.explanation
    assert [(e.field, e.start_line, e.end_line) for e in finding.evidence] == [
        ("text", 2, 2),
        ("text", 4, 4),
        ("code", 2, 2),
        ("code", 4, 4),
    ]
    assert submission.code == payload["code"]


@pytest.mark.parametrize(
    ("code", "template", "expected"),
    [
        ("header\na\nb\n", "a\nb\n", ((2, 3),)),
        ("a\nb\na\nb\n", "a\nb\n", ((1, 2), (3, 4))),
        ("a \nb\n", "a\nb\n", ()),
        ("a\nx\nb\n", "a\nb\n", ()),
        ("a\na\na\n", "a\na\n", ((1, 2), (2, 3))),
        ("a\n", " \n", ()),
        ("a\n", "", ()),
    ],
)
def test_exact_template_blocks(
    code: str,
    template: str,
    expected: tuple[tuple[int, int], ...],
) -> None:
    assert template_ranges(code, template) == expected


def test_template_explains_allowed_match(
    payload: dict[str, object], context: AnalysisContext
) -> None:
    finding = TemplateAnalyzer().analyze(parse_submission(payload), context).findings[0]
    assert finding.kind == "similarity" and finding.score is None
    assert "разрешено" in finding.explanation and "не доказывает плагиат" in finding.explanation
    assert [(e.start_line, e.end_line) for e in finding.evidence] == [(1, 1)]


def test_third_analyzer_only_needs_registration(
    payload: dict[str, object],
    context: AnalysisContext,
    app: Application,
) -> None:
    payload["ai_declaration"] = {
        "used": True,
        "tool": "assistant",
        "purpose": "Обсуждение тестов",
        "verified_by_student": False,
    }
    accepted = app.acceptance_adapter.accept_payload(payload)
    service = app.analysis_service
    app.registry.register("declaration", DeclarationAnalyzer)
    report = service.run(accepted.submission_id, "declaration", context)
    assert app.analysis_service is service and report.review_required
    assert "assistant" in report.findings[0].explanation


def test_missing_explanation_extension(
    payload: dict[str, object], context: AnalysisContext
) -> None:
    payload["text"] = "  "
    report = MissingExplanationAnalyzer().analyze(parse_submission(payload), context)
    assert report.review_required and report.findings[0].score is None
    assert "без текстового пояснения" in report.findings[0].explanation


@pytest.fixture
def valid_report(payload: dict[str, object], context: AnalysisContext) -> AnalysisReport:
    return LengthAnalyzer().analyze(parse_submission(payload), context)


@pytest.mark.parametrize("score", [True, float("nan"), float("inf"), -0.1, 1.5, "0.5"])
def test_report_rejects_invalid_scores(
    payload: dict[str, object],
    context: AnalysisContext,
    valid_report: AnalysisReport,
    score: object,
) -> None:
    finding = replace(valid_report.findings[0], score=cast(float, score))
    with pytest.raises(AnalysisFailure, match="score"):
        validate_report(
            replace(valid_report, findings=(finding,)), parse_submission(payload), context
        )


@pytest.mark.parametrize(
    ("field", "start", "end", "submission_id"),
    [
        ("code", 0, 1, "sub-001"),
        ("code", 2, 1, "sub-001"),
        ("code", 1, 999, "sub-001"),
        ("absent", 1, 1, "sub-001"),
        ("code", True, 1, "sub-001"),
        ("code", 1, 1, "other"),
    ],
)
def test_report_rejects_invalid_evidence(
    payload: dict[str, object],
    context: AnalysisContext,
    valid_report: AnalysisReport,
    field: str,
    start: int,
    end: int,
    submission_id: str,
) -> None:
    evidence = Evidence(submission_id, cast(Literal["text", "code"], field), start, end)
    finding = replace(valid_report.findings[0], evidence=(evidence,))
    with pytest.raises(AnalysisFailure):
        validate_report(
            replace(valid_report, findings=(finding,)), parse_submission(payload), context
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"submission_hash": "wrong"},
        {"submission_id": "other"},
        {"config_hash": "wrong"},
        {"report_id": " "},
        {"analyzer_version": ""},
        {"review_required": "false"},
        {"created_at": "2026-09-01T10:00:00"},
        {"created_at": None},
        {"findings": ()},
        {"findings": ("wrong",)},
        {"findings": (Finding("rubric_feedback", None, (), " "),)},
    ],
)
def test_report_rejects_wrong_shape_and_links(
    payload: dict[str, object],
    context: AnalysisContext,
    valid_report: AnalysisReport,
    changes: dict[str, object],
) -> None:
    with pytest.raises(AnalysisFailure):
        validate_report(replace(valid_report, **changes), parse_submission(payload), context)


def test_changed_context_produces_new_hash(
    payload: dict[str, object],
    context: AnalysisContext,
    valid_report: AnalysisReport,
) -> None:
    new_version = replace(context, config_version="2")
    new_template = replace(
        context, assignment=replace(context.assignment, allowed_template="other")
    )
    assert len({config_hash(context), config_hash(new_version), config_hash(new_template)}) == 3
    with pytest.raises(AnalysisFailure, match="конфигурацию"):
        validate_report(valid_report, parse_submission(payload), new_version)


def test_analysis_failure_preserves_submission(
    payload: dict[str, object],
    context: AnalysisContext,
    app: Application,
) -> None:
    class BrokenAnalyzer:
        analyzer_id = "broken"
        analyzer_version = "1.0"

        def analyze(self, submission: object, context: object) -> AnalysisReport:
            raise RuntimeError("Плагин сломан")

    accepted = app.acceptance_adapter.accept_payload(payload)
    app.registry.register("broken", BrokenAnalyzer)
    with pytest.raises(AnalysisFailure) as caught:
        app.analysis_service.run(accepted.submission_id, "broken", context)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert app.repository.get(accepted.submission_id) is accepted.submission


def test_invalid_plugin_result_is_rejected(
    payload: dict[str, object],
    context: AnalysisContext,
    app: Application,
) -> None:
    class LyingAnalyzer(LengthAnalyzer):
        analyzer_id = "lying"

        def analyze(self, submission: object, context: object) -> AnalysisReport:
            return cast(AnalysisReport, {"result": "not a report"})

    accepted = app.acceptance_adapter.accept_payload(payload)
    app.registry.register("lying", LyingAnalyzer)
    with pytest.raises(AnalysisFailure, match="AnalysisReport"):
        app.analysis_service.run(accepted.submission_id, "lying", context)


def test_wrong_analyzer_metadata_is_rejected(
    payload: dict[str, object],
    context: AnalysisContext,
    app: Application,
) -> None:
    class WrongVersion(LengthAnalyzer):
        analyzer_id = "wrong-version"

        def analyze(self, submission: object, ctx: object) -> AnalysisReport:
            from school_lab.domain.models import Submission

            result = super().analyze(cast(Submission, submission), cast(AnalysisContext, ctx))
            return replace(result, analyzer_version="999")

    accepted = app.acceptance_adapter.accept_payload(payload)
    app.registry.register("wrong-version", WrongVersion)
    with pytest.raises(AnalysisFailure, match="не соответствует"):
        app.analysis_service.run(accepted.submission_id, "wrong-version", context)


def test_unknown_submission_and_wrong_assignment(
    payload: dict[str, object],
    context: AnalysisContext,
    app: Application,
) -> None:
    with pytest.raises(AnalysisFailure, match="ещё не принята"):
        app.analysis_service.run("missing", "length", context)
    accepted = app.acceptance_adapter.accept_payload(payload)
    wrong = replace(context, assignment=Assignment("other", "", ()))
    with pytest.raises(AnalysisFailure, match="другому заданию"):
        app.analysis_service.run(accepted.submission_id, "length", wrong)


def test_registry_errors() -> None:
    registry = AnalyzerRegistry()
    registry.register("length", LengthAnalyzer)
    with pytest.raises(AnalysisFailure):
        registry.register("length", LengthAnalyzer)
    with pytest.raises(AnalysisFailure):
        registry.register(" ", LengthAnalyzer)
    with pytest.raises(AnalysisFailure):
        registry.create("unknown")
    registry.register("wrong-name", LengthAnalyzer)
    with pytest.raises(AnalysisFailure, match="Имя регистрации"):
        registry.create("wrong-name")


def test_report_clock_and_id_are_injectable(
    payload: dict[str, object], context: AnalysisContext
) -> None:
    report = make_report(
        parse_submission(payload),
        context,
        "test",
        "1",
        (Finding("rubric_feedback", None, (), "Проверка"),),
        clock=lambda: datetime(2026, 9, 1, tzinfo=UTC),
        id_factory=lambda: "fixed-id",
    )
    assert report.report_id == "fixed-id" and report.created_at == "2026-09-01T00:00:00+00:00"
