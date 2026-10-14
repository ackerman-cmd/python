import pytest

from school_lab.bootstrap import Application
from school_lab.domain.errors import AnalysisFailure
from school_lab.domain.models import AnalysisContext, AnalysisReport, Submission


def test_expected_plugin_failure_preserves_error_and_submission(
    app: Application,
    payload: dict[str, object],
    context: AnalysisContext,
) -> None:
    refusal = AnalysisFailure("Задание не поддерживается", field="assignment_id")

    class RefusingAnalyzer:
        analyzer_id = "refusing"
        analyzer_version = "1.0"

        def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
            raise refusal

    accepted = app.acceptance_adapter.accept_payload(payload)
    app.registry.register("refusing", RefusingAnalyzer)
    with pytest.raises(AnalysisFailure) as caught:
        app.analysis_service.run(accepted.submission_id, "refusing", context)
    assert caught.value is refusal
    assert app.repository.get(accepted.submission_id) is accepted.submission
