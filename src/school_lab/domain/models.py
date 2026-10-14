from dataclasses import asdict, dataclass
from typing import Literal

from school_lab.domain.errors import SubmissionError
from school_lab.domain.validation import (
    optional_string,
    require_bool,
    require_string,
    validate_content,
    validate_declaration,
    validate_timestamp,
    validate_version,
)


@dataclass(frozen=True, slots=True)
class AIDeclaration:
    used: bool
    tool: str | None
    purpose: str | None
    verified_by_student: bool

    def __post_init__(self) -> None:
        require_bool(self.used, "ai_declaration.used")
        require_bool(self.verified_by_student, "ai_declaration.verified_by_student")
        optional_string(self.tool, "ai_declaration.tool")
        optional_string(self.purpose, "ai_declaration.purpose")
        validate_declaration(self.used, self.tool, self.purpose)


@dataclass(frozen=True, slots=True)
class Submission:
    schema_version: int
    submission_id: str
    student_id: str
    assignment_id: str
    submitted_at: str
    text: str
    code: str
    template_id: str | None
    ai_declaration: AIDeclaration

    def __post_init__(self) -> None:
        validate_version(self.schema_version)
        for name in ("submission_id", "student_id", "assignment_id"):
            require_string(getattr(self, name), name)
        validate_timestamp(self.submitted_at)
        require_string(self.text, "text", nonempty=False)
        require_string(self.code, "code", nonempty=False)
        validate_content(self.text, self.code)
        optional_string(self.template_id, "template_id")
        if not isinstance(self.ai_declaration, AIDeclaration):
            raise SubmissionError("schema_error", "ai_declaration", "Ожидается AIDeclaration")


@dataclass(frozen=True, slots=True)
class Assignment:
    assignment_id: str
    allowed_template: str
    requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        require_string(self.assignment_id, "assignment_id")
        require_string(self.allowed_template, "allowed_template", nonempty=False)
        if not isinstance(self.requirements, tuple):
            raise SubmissionError("schema_error", "requirements", "Ожидается tuple")
        for requirement in self.requirements:
            require_string(requirement, "requirements")


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    assignment: Assignment
    config_version: str = "1"

    def __post_init__(self) -> None:
        if not isinstance(self.assignment, Assignment):
            raise SubmissionError("schema_error", "assignment", "Ожидается Assignment")
        require_string(self.config_version, "config_version")

    def config_payload(self) -> dict[str, object]:
        return {"assignment": asdict(self.assignment), "config_version": self.config_version}


@dataclass(frozen=True, slots=True)
class Evidence:
    submission_id: str
    field: Literal["text", "code"]
    start_line: int
    end_line: int


@dataclass(frozen=True, slots=True)
class Finding:
    kind: Literal["similarity", "rubric_feedback", "processing_error"]
    score: float | None
    evidence: tuple[Evidence, ...]
    explanation: str


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    report_id: str
    submission_id: str
    submission_hash: str
    analyzer_id: str
    analyzer_version: str
    config_hash: str
    findings: tuple[Finding, ...]
    created_at: str
    review_required: bool


@dataclass(frozen=True, slots=True)
class Acceptance:
    status: Literal["accepted", "duplicate"]
    submission: Submission
    submission_hash: str

    @property
    def submission_id(self) -> str:
        return self.submission.submission_id
