from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, ValidationError, field_validator

from school_lab.adapters.acceptance import AcceptanceAdapter
from school_lab.adapters.dto import StrictInput, parse_assignment
from school_lab.adapters.json_codec import decode_json
from school_lab.adapters.repositories import InMemorySubmissionRepository
from school_lab.analyzers.basic import LengthAnalyzer, TemplateAnalyzer
from school_lab.application.ports import Analyzer
from school_lab.application.registry import AnalyzerRegistry
from school_lab.application.services import AnalysisService, SubmissionService
from school_lab.domain.errors import ApplicationError, ConfigurationError, SubmissionError
from school_lab.domain.models import AnalysisContext, Assignment
from school_lab.domain.validation import require_string


class AnalyzerConfig(StrictInput):
    name: str
    params: dict[str, object] = Field(default_factory=dict)


class AppConfig(StrictInput):
    config_version: str = "1"
    analyzers: list[AnalyzerConfig] = Field(
        default_factory=lambda: [AnalyzerConfig(name="length"), AnalyzerConfig(name="template")]
    )

    @field_validator("config_version")
    @classmethod
    def nonempty_version(cls, value: str) -> str:
        try:
            return require_string(value, "config_version")
        except SubmissionError as exc:
            raise ValueError(exc.message) from exc


@dataclass(frozen=True, slots=True)
class Application:
    repository: InMemorySubmissionRepository
    submission_service: SubmissionService
    acceptance_adapter: AcceptanceAdapter
    registry: AnalyzerRegistry
    analysis_service: AnalysisService
    config_version: str

    def context(self, assignment: Assignment) -> AnalysisContext:
        return AnalysisContext(assignment, self.config_version)


def build_application(config: object = None) -> Application:
    try:
        settings = AppConfig.model_validate({} if config is None else config)
    except ValidationError as exc:
        issue = exc.errors(include_url=False, include_input=False)[0]
        field = ".".join(str(part) for part in issue["loc"]) or "config"
        raise ConfigurationError(str(issue["msg"]), field=field) from exc
    if not settings.analyzers:
        raise ConfigurationError("Нужен хотя бы один анализатор", field="analyzers")
    available: dict[str, Callable[[], Analyzer]] = {
        "length": LengthAnalyzer,
        "template": TemplateAnalyzer,
    }
    registry = AnalyzerRegistry()
    for entry in settings.analyzers:
        if entry.name not in available:
            raise ConfigurationError(f"Неизвестный анализатор: {entry.name}", field="analyzers")
        if entry.params:
            raise ConfigurationError(
                f"Анализатор {entry.name} не принимает параметры", field="analyzers.params"
            )
        try:
            registry.register(entry.name, available[entry.name])
            registry.create(entry.name)
        except ApplicationError as exc:
            raise ConfigurationError(exc.message, field="analyzers") from exc
    repository = InMemorySubmissionRepository()
    acceptance = SubmissionService(repository)
    return Application(
        repository,
        acceptance,
        AcceptanceAdapter(acceptance),
        registry,
        AnalysisService(repository, registry),
        settings.config_version,
    )


def load_config(path: Path) -> object:
    try:
        return decode_json(path.read_text(encoding="utf-8"))
    except ApplicationError as exc:
        raise ConfigurationError(exc.message, field=exc.field) from exc


def load_assignments(path: Path) -> dict[str, Assignment]:
    try:
        raw = decode_json(path.read_text(encoding="utf-8"))
    except ApplicationError as exc:
        raise ConfigurationError(exc.message, field="assignments") from exc
    if not isinstance(raw, list):
        raise ConfigurationError(
            "assignments.json должен содержать список заданий", field="assignments"
        )
    if not raw:
        raise ConfigurationError("Нужен хотя бы один Assignment", field="assignments")
    assignments: dict[str, Assignment] = {}
    for index, item in enumerate(raw):
        try:
            assignment = parse_assignment(item)
        except ApplicationError as exc:
            raise ConfigurationError(exc.message, field=f"assignments.{index}.{exc.field}") from exc
        if assignment.assignment_id in assignments:
            raise ConfigurationError("Повтор assignment_id", field="assignment_id")
        assignments[assignment.assignment_id] = assignment
    return assignments
