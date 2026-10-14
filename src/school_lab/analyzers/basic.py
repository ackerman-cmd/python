from typing import Literal

from school_lab.application.reporting import make_report
from school_lab.domain.errors import AnalysisFailure
from school_lab.domain.models import AnalysisContext, AnalysisReport, Evidence, Finding, Submission


def nonempty_line_numbers(text: str) -> tuple[int, ...]:
    return tuple(number for number, line in enumerate(text.splitlines(), 1) if line.strip())


def template_ranges(code: str, template: str) -> tuple[tuple[int, int], ...]:
    if not template.strip():
        return ()
    source_lines, template_lines = code.splitlines(), template.splitlines()
    width = len(template_lines)
    return tuple(
        (index + 1, index + width)
        for index in range(len(source_lines) - width + 1)
        if source_lines[index : index + width] == template_lines
    )


def check_assignment(submission: Submission, context: AnalysisContext) -> None:
    if submission.assignment_id != context.assignment.assignment_id:
        raise AnalysisFailure("Контекст относится к другому заданию", field="assignment_id")


class LengthAnalyzer:
    analyzer_id = "length"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        check_assignment(submission, context)
        text_lines = nonempty_line_numbers(submission.text)
        code_lines = nonempty_line_numbers(submission.code)
        fields: tuple[tuple[Literal["text", "code"], tuple[int, ...]], ...] = (
            ("text", text_lines),
            ("code", code_lines),
        )
        evidence = tuple(
            Evidence(submission.submission_id, name, number, number)
            for name, numbers in fields
            for number in numbers
        )
        finding = Finding(
            "rubric_feedback",
            None,
            evidence,
            f"Непустые строки: text={len(text_lines)}, code={len(code_lines)}. "
            "Количество строк не оценивает корректность решения.",
        )
        return make_report(submission, context, self.analyzer_id, self.analyzer_version, (finding,))


class TemplateAnalyzer:
    analyzer_id = "template"
    analyzer_version = "1.0"

    def analyze(self, submission: Submission, context: AnalysisContext) -> AnalysisReport:
        check_assignment(submission, context)
        ranges = template_ranges(submission.code, context.assignment.allowed_template)
        evidence = tuple(
            Evidence(submission.submission_id, "code", start, end) for start, end in ranges
        )
        explanation = (
            f"Найдены разрешённые блоки шаблона: {len(ranges)}. "
            "Совпадение разрешено и не доказывает плагиат."
            if ranges
            else (
                "Точное совпадение с разрешённым шаблоном не найдено. "
                "Нечёткое сходство не проверялось."
            )
        )
        finding = Finding("similarity", None, evidence, explanation)
        return make_report(submission, context, self.analyzer_id, self.analyzer_version, (finding,))
