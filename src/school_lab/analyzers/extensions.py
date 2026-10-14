from school_lab.analyzers.basic import check_assignment
from school_lab.application.reporting import make_report
from school_lab.domain.models import AnalysisContext, AnalysisReport, Finding, Submission


class DeclarationAnalyzer:
    analyzer_id = "declaration"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        check_assignment(submission, context)
        declaration = submission.ai_declaration
        if declaration.used:
            explanation = (
                f"Использование ИИ заявлено. Инструмент: {declaration.tool}; "
                f"цель: {declaration.purpose}. Декларация не доказывает авторство."
            )
            review = not declaration.verified_by_student
        else:
            explanation = "Использование ИИ не заявлено. Авторство автоматически не определялось."
            review = False
        return make_report(
            submission,
            context,
            self.analyzer_id,
            self.analyzer_version,
            (Finding("rubric_feedback", None, (), explanation),),
            review_required=review,
        )


class MissingExplanationAnalyzer:
    analyzer_id = "missing-explanation"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        check_assignment(submission, context)
        missing = not submission.text.strip() and bool(submission.code.strip())
        explanation = (
            "Код сдан без текстового пояснения." if missing else "Текстовое пояснение есть."
        )
        return make_report(
            submission,
            context,
            self.analyzer_id,
            self.analyzer_version,
            (Finding("rubric_feedback", None, (), explanation),),
            review_required=missing,
        )
