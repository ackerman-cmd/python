from collections.abc import Callable
from typing import Self

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from school_lab.domain.errors import SubmissionError
from school_lab.domain.models import AIDeclaration, Assignment, Submission
from school_lab.domain.validation import (
    optional_string,
    require_string,
    validate_content,
    validate_declaration,
    validate_timestamp,
    validate_version,
)


def _checked[T, **P](check: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    try:
        return check(*args, **kwargs)
    except SubmissionError as exc:
        raise PydanticCustomError(
            exc.code, "{message}", {"message": exc.message, "field": exc.field}
        ) from exc


class StrictInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    @model_validator(mode="before")
    @classmethod
    def valid_unicode_keys(cls, raw: object) -> object:
        if isinstance(raw, dict):
            for key in raw:
                if isinstance(key, str):
                    _checked(require_string, key, key, nonempty=False)
        return raw


class DeclarationInput(StrictInput):
    used: bool
    tool: str | None
    purpose: str | None
    verified_by_student: bool

    @field_validator("tool", "purpose")
    @classmethod
    def nonempty_optional(cls, value: str | None) -> str | None:
        return _checked(lambda: optional_string(value, "ai_declaration"))

    @model_validator(mode="after")
    def consistent_usage(self) -> Self:
        _checked(lambda: validate_declaration(self.used, self.tool, self.purpose))
        return self

    def to_domain(self) -> AIDeclaration:
        return AIDeclaration(self.used, self.tool, self.purpose, self.verified_by_student)


class SubmissionInput(StrictInput):
    schema_version: int
    submission_id: str
    student_id: str
    assignment_id: str
    submitted_at: str
    text: str
    code: str
    template_id: str | None
    ai_declaration: DeclarationInput

    @field_validator("schema_version")
    @classmethod
    def supported_version(cls, value: int) -> int:
        return _checked(lambda: validate_version(value))

    @field_validator("submission_id", "student_id", "assignment_id")
    @classmethod
    def nonempty_id(cls, value: str) -> str:
        return _checked(lambda: require_string(value, ""))

    @field_validator("template_id")
    @classmethod
    def optional_id(cls, value: str | None) -> str | None:
        return _checked(lambda: optional_string(value, "template_id"))

    @field_validator("submitted_at")
    @classmethod
    def aware_timestamp(cls, value: str) -> str:
        return _checked(lambda: validate_timestamp(value))

    @field_validator("text", "code")
    @classmethod
    def valid_content_string(cls, value: str) -> str:
        return _checked(require_string, value, "", nonempty=False)

    @model_validator(mode="after")
    def has_content(self) -> Self:
        _checked(lambda: validate_content(self.text, self.code))
        return self

    def to_domain(self) -> Submission:
        return Submission(
            self.schema_version,
            self.submission_id,
            self.student_id,
            self.assignment_id,
            self.submitted_at,
            self.text,
            self.code,
            self.template_id,
            self.ai_declaration.to_domain(),
        )


class AssignmentInput(StrictInput):
    assignment_id: str
    allowed_template: str
    requirements: list[str]

    @field_validator("assignment_id")
    @classmethod
    def nonempty_id(cls, value: str) -> str:
        return _checked(lambda: require_string(value, "assignment_id"))

    @field_validator("allowed_template")
    @classmethod
    def valid_template(cls, value: str) -> str:
        return _checked(require_string, value, "allowed_template", nonempty=False)

    @field_validator("requirements")
    @classmethod
    def nonempty_requirements(cls, values: list[str]) -> list[str]:
        for value in values:
            _checked(require_string, value, "requirements")
        return values

    def to_domain(self) -> Assignment:
        return Assignment(self.assignment_id, self.allowed_template, tuple(self.requirements))


def submission_error(exc: ValidationError) -> SubmissionError:
    issue = exc.errors(include_url=False, include_input=False)[0]
    location = ".".join(str(part) for part in issue["loc"])
    context = issue.get("ctx", {})
    field = str(context.get("field") or location or "submission")

    if field == "ai_declaration" and location:
        field = location
    code = "unsupported_version" if issue["type"] == "unsupported_version" else "schema_error"
    standard_messages = {
        "missing": "Обязательное поле отсутствует",
        "extra_forbidden": "Неизвестное поле не допускается",
        "string_type": "Ожидается строка без преобразования типа",
        "int_type": "Ожидается int, bool и строки не допускаются",
        "bool_type": "Ожидается bool без преобразования типа",
        "model_type": "Ожидается JSON-объект",
        "list_type": "Ожидается список",
    }
    message = str(context.get("message") or standard_messages.get(issue["type"], issue["msg"]))
    return SubmissionError(code, field, message)


def parse_submission(raw: object) -> Submission:
    try:
        return SubmissionInput.model_validate(raw).to_domain()
    except ValidationError as exc:
        raise submission_error(exc) from exc


def parse_assignment(raw: object) -> Assignment:
    try:
        return AssignmentInput.model_validate(raw).to_domain()
    except ValidationError as exc:
        raise submission_error(exc) from exc
