from datetime import datetime

from school_lab.domain.errors import SubmissionError


def require_string(value: object, field: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise SubmissionError("schema_error", field, "Ожидается строка")
    if nonempty and not value.strip():
        raise SubmissionError("schema_error", field, "Ожидается непустая строка")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SubmissionError(
            "schema_error", field, "Строка содержит непарный Unicode-суррогат"
        ) from exc
    return value


def optional_string(value: object, field: str) -> str | None:
    return None if value is None else require_string(value, field)


def require_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise SubmissionError("schema_error", field, "Ожидается bool без преобразования типа")
    return value


def validate_version(value: object) -> int:
    if type(value) is not int:
        raise SubmissionError(
            "schema_error", "schema_version", "Ожидается int, bool не допускается"
        )
    if value != 1:
        raise SubmissionError("unsupported_version", "schema_version", "Поддерживается версия 1")
    return value


def validate_timestamp(value: object, field: str = "submitted_at") -> str:
    text = require_string(value, field)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SubmissionError("schema_error", field, "Ожидается дата и время ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SubmissionError("schema_error", field, "Часовой пояс обязателен")
    return text


def validate_content(text: str, code: str) -> None:
    if not text.strip() and not code.strip():
        raise SubmissionError("schema_error", "text/code", "Текст или код должны быть непустыми")


def validate_declaration(used: bool, tool: str | None, purpose: str | None) -> None:
    if used and (tool is None or purpose is None):
        missing = "tool" if tool is None else "purpose"
        raise SubmissionError(
            "schema_error",
            f"ai_declaration.{missing}",
            "При used=true обязательны инструмент и цель",
        )
