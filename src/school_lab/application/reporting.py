import math
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from school_lab.domain.errors import AnalysisFailure, SubmissionError
from school_lab.domain.hashing import config_hash, submission_hash
from school_lab.domain.models import AnalysisContext, AnalysisReport, Evidence, Finding, Submission
from school_lab.domain.validation import require_string, validate_timestamp


def _nonempty(value: object, field: str) -> None:
    try:
        require_string(value, field)
    except SubmissionError as exc:
        raise AnalysisFailure(exc.message, field=exc.field) from exc


def validate_report(
    report: object, submission: Submission, context: AnalysisContext
) -> AnalysisReport:
    if not isinstance(report, AnalysisReport):
        raise AnalysisFailure("Ожидается AnalysisReport")
    if (
        report.submission_id != submission.submission_id
        or report.submission_hash != submission_hash(submission)
    ):
        raise AnalysisFailure("Отчёт ссылается на другую версию сдачи", field="submission_hash")
    if report.config_hash != config_hash(context):
        raise AnalysisFailure("Отчёт использует другую конфигурацию", field="config_hash")
    for name in ("report_id", "analyzer_id", "analyzer_version"):
        _nonempty(getattr(report, name), name)
    if type(report.review_required) is not bool:
        raise AnalysisFailure("review_required должен быть bool", field="review_required")
    try:
        validate_timestamp(report.created_at, "created_at")
    except SubmissionError as exc:
        raise AnalysisFailure(exc.message, field=exc.field) from exc
    if not isinstance(report.findings, tuple) or not report.findings:
        raise AnalysisFailure("Ожидается непустой tuple наблюдений", field="findings")
    for finding in report.findings:
        if not isinstance(finding, Finding):
            raise AnalysisFailure("Ожидается Finding", field="findings")
        if finding.kind not in ("similarity", "rubric_feedback", "processing_error"):
            raise AnalysisFailure("Неизвестный вид наблюдения", field="kind")
        score = finding.score
        if score is not None and (
            type(score) not in (int, float) or not 0 <= score <= 1 or not math.isfinite(score)
        ):
            raise AnalysisFailure("score должен быть конечным числом 0–1 либо None", field="score")
        _nonempty(finding.explanation, "explanation")
        if not isinstance(finding.evidence, tuple):
            raise AnalysisFailure("Ожидается tuple свидетельств", field="evidence")
        for evidence in finding.evidence:
            if not isinstance(evidence, Evidence):
                raise AnalysisFailure("Ожидается Evidence", field="evidence")
            if evidence.submission_id != submission.submission_id:
                raise AnalysisFailure("Evidence относится к другой сдаче", field="evidence")
            if evidence.field not in ("text", "code"):
                raise AnalysisFailure("Неизвестное поле evidence", field="evidence.field")
            if type(evidence.start_line) is not int or type(evidence.end_line) is not int:
                raise AnalysisFailure("Номера строк должны быть int", field="evidence")
            count = len(getattr(submission, evidence.field).splitlines())
            if not 1 <= evidence.start_line <= evidence.end_line <= count:
                raise AnalysisFailure("Evidence выходит за пределы исходника", field="evidence")
    return report


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_report_id() -> str:
    return str(uuid4())


def make_report(
    submission: Submission,
    context: AnalysisContext,
    analyzer_id: str,
    analyzer_version: str,
    findings: tuple[Finding, ...],
    *,
    review_required: bool = False,
    clock: Callable[[], datetime] = utc_now,
    id_factory: Callable[[], str] = new_report_id,
) -> AnalysisReport:
    report = AnalysisReport(
        report_id=id_factory(),
        submission_id=submission.submission_id,
        submission_hash=submission_hash(submission),
        analyzer_id=analyzer_id,
        analyzer_version=analyzer_version,
        config_hash=config_hash(context),
        findings=findings,
        created_at=clock().isoformat(),
        review_required=review_required,
    )
    return validate_report(report, submission, context)
