import json

from school_lab.domain.errors import SubmissionError


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SubmissionError("invalid_json", key, "Повтор ключа в JSON не допускается")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise SubmissionError("invalid_json", "json", f"Нестандартная константа: {value}")


def decode_json(text: str) -> object:
    try:
        result: object = json.loads(
            text, object_pairs_hook=_unique_keys, parse_constant=_reject_constant
        )
        return result
    except json.JSONDecodeError as exc:
        raise SubmissionError(
            "invalid_json", "json", f"Ошибка JSON около столбца {exc.colno}"
        ) from exc
    except (ValueError, RecursionError) as exc:
        raise SubmissionError(
            "invalid_json", "json", "JSON превышает ограничения парсера по числу или вложенности"
        ) from exc
