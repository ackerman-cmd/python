import io
import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.dto import SubmissionInput, parse_submission
from school_lab.adapters.json_codec import decode_json
from school_lab.adapters.sources import JsonlSource, StreamSource
from school_lab.application.ports import Analyzer
from school_lab.application.registry import AnalyzerRegistry
from school_lab.bootstrap import Application
from school_lab.domain.errors import AnalysisFailure, SubmissionError
from school_lab.domain.hashing import submission_hash
from school_lab.domain.models import AnalysisContext
from school_lab.interfaces.cli import main


@pytest.mark.parametrize("bad", ["9" * 5000, "[" * 20_000 + "0" + "]" * 20_000])
def test_parser_limits_are_record_errors_and_import_continues(
    payload: dict[str, object],
    app: Application,
    bad: str,
) -> None:
    source = StreamSource(io.StringIO(bad + "\n" + json.dumps(payload) + "\n"))
    result = import_source(source, app.acceptance_adapter)
    assert result.accepted == ["sub-001"]
    assert result.errors[0]["line_no"] == 1 and result.errors[0]["code"] == "invalid_json"
    assert len(app.repository) == 1


@pytest.mark.parametrize(
    "field",
    ["text", "code", "student_id", "submission_id", "assignment_id", "template_id"],
)
def test_surrogate_rejected_by_dto_and_domain_without_input_mutation(
    payload: dict[str, object],
    field: str,
) -> None:
    valid = parse_submission(payload)
    payload[field] = "\ud800"
    original = deepcopy(payload)
    with pytest.raises(ValidationError):
        SubmissionInput.model_validate(payload)
    with pytest.raises(SubmissionError) as caught:
        parse_submission(payload)
    assert caught.value.code == "schema_error" and caught.value.field == field
    with pytest.raises(SubmissionError):
        replace(valid, **{field: "\ud800"})
    assert payload == original


@pytest.mark.parametrize("field", ["tool", "purpose"])
def test_surrogate_rejected_in_nested_declaration(payload: dict[str, object], field: str) -> None:
    declaration = payload["ai_declaration"]
    assert isinstance(declaration, dict)
    declaration[field] = "\udfff"
    with pytest.raises(SubmissionError) as caught:
        parse_submission(payload)
    assert caught.value.field == f"ai_declaration.{field}"


def test_unicode_error_does_not_block_later_jsonl_record(
    payload: dict[str, object],
    app: Application,
    tmp_path: Path,
) -> None:
    bad = {**payload, "text": "\ud800"}
    path = tmp_path / "surrogate.jsonl"
    path.write_text(json.dumps(bad) + "\n" + json.dumps(payload) + "\n", encoding="utf-8")
    summary = import_source(JsonlSource(path), app.acceptance_adapter)
    assert summary.accepted == ["sub-001"] and len(app.repository) == 1
    assert summary.errors[0]["field"] == "text" and summary.errors[0]["line_no"] == 1


@pytest.mark.parametrize("bad_key", ["\ud800", "\udfff"])
def test_diagnostics_for_invalid_unicode_key_are_utf8_safe(
    payload: dict[str, object],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    bad_key: str,
) -> None:
    raw = {**payload, bad_key: "extra"}
    path = tmp_path / "bad-key.jsonl"
    path.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    assert main(["import", str(path)]) == 1
    output = capsys.readouterr().out
    output.encode("utf-8")
    issue = json.loads(output)["errors"][0]
    assert issue["code"] == "schema_error" and "\\ud" in issue["field"]


def test_emoji_and_non_ascii_source_preserved(payload: dict[str, object]) -> None:
    payload["text"] = "Пример 🐍\nКитайский: 汉字\n"
    source = parse_submission(payload)
    assert asdict(source)["text"] == payload["text"]
    assert len(submission_hash(source)) == 64
    escaped_json = json.dumps(payload, ensure_ascii=True)
    assert parse_submission(decode_json(escaped_json)) == source


def test_nonstring_mapping_key_rejected_without_mutation(
    payload: dict[str, object],
    app: Application,
) -> None:
    raw = {**payload, 3: "not a JSON key"}
    original = deepcopy(raw)
    with pytest.raises(SubmissionError) as caught:
        app.acceptance_adapter.accept_payload(raw)
    assert caught.value.code == "schema_error"
    assert raw == original and len(app.repository) == 0


@pytest.mark.parametrize("attribute", ["analyzer_id", "analyzer_version", "analyze"])
def test_property_failure_translated_and_keeps_saved_submission(
    payload: dict[str, object],
    app: Application,
    context: AnalysisContext,
    attribute: str,
) -> None:
    class BadProperty:
        analyzer_id = "bad-property"
        analyzer_version = "1"

        def analyze(self, submission: object, context: object) -> object:
            return None

    def fail(_: object) -> object:
        raise RuntimeError("Отказ свойства интерфейса")

    setattr(BadProperty, attribute, property(fail))
    accepted = app.acceptance_adapter.accept_payload(payload)
    app.registry.register("bad-property", cast(Callable[[], Analyzer], BadProperty))
    with pytest.raises(AnalysisFailure) as caught:
        app.analysis_service.run(accepted.submission_id, "bad-property", context)
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert app.repository.get(accepted.submission_id) is accepted.submission


def test_factory_exception_has_cause() -> None:
    def fail() -> object:
        raise RuntimeError("Отказ фабрики")

    registry = AnalyzerRegistry()
    registry.register("failed", cast(Callable[[], Analyzer], fail))
    with pytest.raises(AnalysisFailure) as caught:
        registry.create("failed")
    assert caught.value.field == "factory" and isinstance(caught.value.__cause__, RuntimeError)


@pytest.mark.parametrize(
    "attributes",
    [
        {"analyzer_id": "bad", "analyzer_version": ""},
        {"analyzer_id": "bad", "analyzer_version": "1"},
        {"analyzer_id": "bad", "analyzer_version": "1", "analyze": 123},
    ],
)
def test_incompatible_plugin_interface_is_rejected(attributes: dict[str, object]) -> None:
    registry = AnalyzerRegistry()
    plugin = type("BadInterface", (), attributes)
    registry.register("bad", cast(Callable[[], Analyzer], plugin))
    with pytest.raises(AnalysisFailure):
        registry.create("bad")
