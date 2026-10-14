from school_lab.application.ports import SubmissionRepository
from school_lab.application.registry import AnalyzerRegistry
from school_lab.application.reporting import validate_report
from school_lab.domain.errors import AnalysisFailure, SubmissionError
from school_lab.domain.hashing import submission_hash
from school_lab.domain.models import Acceptance, AnalysisContext, AnalysisReport, Submission


class SubmissionService:
    def __init__(self, repository: SubmissionRepository) -> None:
        self.repository = repository

    def accept(self, submission: Submission) -> Acceptance:
        digest = submission_hash(submission)
        previous = self.repository.get(submission.submission_id)
        if previous is not None:
            if submission_hash(previous) != digest:
                raise SubmissionError("conflict", "submission_id", "ID уже связан с другой версией")
            return Acceptance("duplicate", previous, digest)
        self.repository.add(submission)
        return Acceptance("accepted", submission, digest)


class AnalysisService:
    def __init__(self, repository: SubmissionRepository, registry: AnalyzerRegistry) -> None:
        self.repository = repository
        self.registry = registry

    def run(
        self, submission_id: str, analyzer_name: str, context: AnalysisContext
    ) -> AnalysisReport:
        submission = self.repository.get(submission_id)
        if submission is None:
            raise AnalysisFailure("Сдача ещё не принята", field="submission_id")
        if submission.assignment_id != context.assignment.assignment_id:
            raise AnalysisFailure("Контекст относится к другому заданию", field="assignment_id")
        analyzer = self.registry.create(analyzer_name)
        try:
            analyzer_id = analyzer.analyzer_id
            analyzer_version = analyzer.analyzer_version
            report = analyzer.analyze(submission, context)
        except AnalysisFailure:
            raise
        except Exception as exc:
            raise AnalysisFailure("Анализатор завершился с ошибкой") from exc
        validate_report(report, submission, context)
        if report.analyzer_id != analyzer_id or report.analyzer_version != analyzer_version:
            raise AnalysisFailure("Отчёт не соответствует вызванному анализатору")
        return report
