import importlib
import json
import runpy
import sys
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Literal, cast
from unittest.mock import patch

import pytest

import school_lab.interfaces.cli
from school_lab.adapters.acceptance import import_source
from school_lab.adapters.dto import parse_assignment, parse_submission
from school_lab.adapters.sources import InMemorySource, JsonlSource
from school_lab.analyzers.basic import LengthAnalyzer, TemplateAnalyzer
from school_lab.analyzers.extensions import DeclarationAnalyzer, MissingExplanationAnalyzer
from school_lab.application.ports import Analyzer, SubmissionSource
from school_lab.application.registry import AnalyzerRegistry
from school_lab.application.reporting import validate_report
from school_lab.bootstrap import Application, load_assignments
from school_lab.domain.errors import AnalysisFailure, ConfigurationError, SubmissionError
from school_lab.domain.models import AnalysisContext, Assignment, Evidence, Finding
from school_lab.examples.benchmark import benchmark_import
from school_lab.examples.demo import example_payload, run_demo
from school_lab.interfaces.cli import main


@pytest.mark.parametrize("kind", ["memory", "jsonl"])
def test_common_import_contract_continues_after_schema_error(
    payload: dict[str, object],
    app: Application,
    tmp_path: Path,
    kind: str,
) -> None:
    values = [{**payload, "student_id": ""}, payload]
    source: SubmissionSource
    if kind == "memory":
        source = InMemorySource(values)
    else:
        path = tmp_path / "schema-error.jsonl"
        path.write_text("\n".join(json.dumps(item) for item in values), encoding="utf-8")
        source = JsonlSource(path)
    result = import_source(source, app.acceptance_adapter)
    assert result.accepted == ["sub-001"] and len(app.repository) == 1
    assert result.errors[0]["field"] == "student_id" and result.errors[0]["line_no"] == 1


@pytest.mark.parametrize("limit", [0, -1, True, "10"])
def test_source_invalid_limit_rejected(tmp_path: Path, limit: object) -> None:
    with pytest.raises(ValueError):
        JsonlSource(tmp_path / "unused", max_line_chars=cast(int, limit))


def test_long_final_record_without_newline(tmp_path: Path) -> None:
    path = tmp_path / "truncated.jsonl"
    path.write_text("{}\n" + "x" * 30, encoding="utf-8")
    with JsonlSource(path, max_line_chars=10).open() as records:
        values = list(records)
    assert values[0].raw == {} and values[1].error is not None
    assert values[1].line_no == 2 and len(values) == 2


def test_crlf_source_preserves_embedded_original_newlines(
    payload: dict[str, object],
    tmp_path: Path,
    app: Application,
) -> None:
    payload["code"] = "# heading\r\n\r\npass\r\n"
    path = tmp_path / "windows.jsonl"
    path.write_bytes((json.dumps(payload) + "\r\n").encode("utf-8"))
    result = import_source(JsonlSource(path), app.acceptance_adapter)
    assert result.accepted == ["sub-001"]
    saved = app.repository.get("sub-001")
    assert saved is not None and saved.code == payload["code"]


def test_decode_failure_closes_file_and_cli_returns_source_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "bad-utf8.jsonl"
    path.write_bytes(b"\xff\n")
    handle = path.open(encoding="utf-8")
    with patch("pathlib.Path.open", return_value=handle):
        with pytest.raises(UnicodeDecodeError):
            with JsonlSource(path).open() as records:
                list(records)
    assert handle.closed
    assert main(["import", str(path)]) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["code"] == "source_error"


@pytest.mark.parametrize(
    "factory",
    [LengthAnalyzer, TemplateAnalyzer, DeclarationAnalyzer, MissingExplanationAnalyzer],
)
def test_common_analyzer_contract_rejects_foreign_assignment(
    payload: dict[str, object],
    context: AnalysisContext,
    factory: Callable[[], Analyzer],
) -> None:
    wrong = replace(context, assignment=Assignment("other", "", ()))
    with pytest.raises(AnalysisFailure) as caught:
        factory().analyze(parse_submission(payload), wrong)
    assert caught.value.field == "assignment_id"


@pytest.mark.parametrize(
    "finding",
    [
        Finding(cast(Literal["similarity"], "unknown"), None, (), "Пояснение"),
        Finding("similarity", None, cast(tuple[Evidence, ...], []), "Пояснение"),
        Finding("similarity", None, cast(tuple[Evidence, ...], ("wrong",)), "Пояснение"),
        Finding("rubric_feedback", None, (), "\ud800"),
    ],
)
def test_report_rejects_bad_observation_structure(
    payload: dict[str, object],
    context: AnalysisContext,
    finding: Finding,
) -> None:
    submission = parse_submission(payload)
    report = LengthAnalyzer().analyze(submission, context)
    with pytest.raises(AnalysisFailure):
        validate_report(replace(report, findings=(finding,)), submission, context)


@pytest.mark.parametrize("score", [0, 1, 0.5])
def test_valid_score_boundaries(
    payload: dict[str, object], context: AnalysisContext, score: float
) -> None:
    submission = parse_submission(payload)
    report = LengthAnalyzer().analyze(submission, context)
    changed = replace(report, findings=(replace(report.findings[0], score=score),))
    assert validate_report(changed, submission, context) is changed


@pytest.mark.parametrize("bad", [{}, [], None, True])
def test_submission_rejects_nonconforming_root(bad: object, app: Application) -> None:
    with pytest.raises(SubmissionError):
        app.acceptance_adapter.accept_payload(bad)
    assert len(app.repository) == 0


@pytest.mark.parametrize(
    "changes",
    [{"ai_declaration": {}}, {"text": 12}, {"schema_version": True}],
)
def test_direct_domain_constructor_checks_types(
    payload: dict[str, object], changes: dict[str, object]
) -> None:
    with pytest.raises(SubmissionError):
        replace(parse_submission(payload), **changes)


def test_direct_declaration_bool_and_immutable_assignment_requirements(
    payload: dict[str, object],
    context: AnalysisContext,
) -> None:
    value = parse_submission(payload)
    with pytest.raises(SubmissionError):
        replace(value.ai_declaration, used=cast(bool, "false"))
    with pytest.raises(SubmissionError):
        replace(context.assignment, requirements=cast(tuple[str, ...], []))
    with pytest.raises(SubmissionError):
        replace(context, assignment=cast(Assignment, {}))


@pytest.mark.parametrize(
    "raw",
    [
        {},
        [],
        "{broken",
        [{"assignment_id": "a", "allowed_template": "", "requirements": [" "]}],
        [{"assignment_id": "a", "allowed_template": "", "requirements": [], "extra": True}],
        [{"assignment_id": "a", "allowed_template": "\ud800", "requirements": []}],
        [
            {"assignment_id": "a", "allowed_template": "", "requirements": []},
            {"assignment_id": "a", "allowed_template": "", "requirements": []},
        ],
    ],
)
def test_invalid_assignment_configuration_fails_before_analysis(
    tmp_path: Path, raw: object
) -> None:
    path = tmp_path / "assignments.json"
    path.write_text(raw if raw == "{broken" else json.dumps(raw), encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_assignments(path)


def test_assignment_conversion_isolates_mutable_dto_input() -> None:
    raw = {"assignment_id": "a", "allowed_template": "", "requirements": ["solve"]}
    assignment = parse_assignment(raw)
    requirements = raw["requirements"]
    assert isinstance(requirements, list)
    requirements.append("changed")
    assert assignment.requirements == ("solve",)


@pytest.mark.parametrize("submissions", ["", "{}\n", "[]\n", "{broken\n"])
def test_invalid_example_corpus_is_structured_error(tmp_path: Path, submissions: str) -> None:
    (tmp_path / "submissions.jsonl").write_text(submissions, encoding="utf-8")
    with pytest.raises((ConfigurationError, SubmissionError)):
        example_payload(tmp_path)


def test_demo_empty_corpus_is_structured_error(data_dir: Path, tmp_path: Path) -> None:
    for name in ("config.json", "assignments.json"):
        (tmp_path / name).write_bytes((data_dir / name).read_bytes())
    (tmp_path / "submissions.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        run_demo(tmp_path)
    assert caught.value.field == "submissions"


def test_demo_missing_assignment_is_structured_error(
    data_dir: Path,
    tmp_path: Path,
    payload: dict[str, object],
) -> None:
    for name in ("config.json", "assignments.json"):
        (tmp_path / name).write_bytes((data_dir / name).read_bytes())
    payload["assignment_id"] = "unknown"
    (tmp_path / "submissions.jsonl").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        run_demo(tmp_path)
    assert caught.value.field == "assignment_id"


def test_cli_demo_and_benchmark(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["demo", "--data-dir", str(data_dir)]) == 0
    demo = json.loads(capsys.readouterr().out)
    assert demo["repository_size"] == 12 and demo["report_count"] == 24
    assert main(["benchmark", "--data-dir", str(data_dir), "--records", "3", "--repeats", "2"]) == 0
    timing = json.loads(capsys.readouterr().out)
    assert timing["records"] == 3 and len(timing["durations_ms"]) == 2
    assert all(value >= 0 for value in timing["durations_ms"])


@pytest.mark.parametrize(
    "option,value", [("--records", "0"), ("--records", "abc"), ("--repeats", "-1")]
)
def test_cli_invalid_benchmark_argument(option: str, value: str) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["benchmark", option, value])
    assert caught.value.code == 2


@pytest.mark.parametrize("records,repeats", [(0, 1), (1, 0)])
def test_benchmark_api_rejects_empty_measurement(
    data_dir: Path, records: int, repeats: int
) -> None:
    with pytest.raises(ValueError):
        benchmark_import(data_dir, records, repeats)


def test_cli_bad_config_prints_structured_diagnostic(
    tmp_path: Path,
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config.json"
    config.write_text('{"analyzers":[{"name":"unknown"}]}', encoding="utf-8")
    assert main(["import", str(data_dir / "submissions.jsonl"), "--config", str(config)]) == 2
    output = capsys.readouterr()
    assert not output.out and json.loads(output.err)["code"] == "configuration_error"


def test_module_entrypoint(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["school_lab.interfaces.cli", "import", str(data_dir / "submissions.jsonl")]
    )
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(school_lab.interfaces.cli.__file__), run_name="__main__")
    assert caught.value.code == 0
    assert len(json.loads(capsys.readouterr().out)["accepted"]) == 12


def test_registry_rejects_noncallable_factory() -> None:
    with pytest.raises(AnalysisFailure):
        AnalyzerRegistry().register("bad", cast(Callable[[], Analyzer], 123))


def test_package_entrypoint(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["school_lab", "import", str(data_dir / "submissions.jsonl")])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("school_lab", run_name="__main__")
    assert caught.value.code == 0
    assert len(json.loads(capsys.readouterr().out)["accepted"]) == 12


def test_submitted_code_never_executes(
    payload: dict[str, object],
    app: Application,
    context: AnalysisContext,
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "executed.txt"
    payload["code"] = f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('executed')\n"
    accepted = app.acceptance_adapter.accept_payload(payload)
    for name in app.registry.names:
        app.analysis_service.run(accepted.submission_id, name, context)
    assert not sentinel.exists()


def test_main_module_import_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(sys, "argv", ["unrelated-program", "unrecognized-argument"])
    module = importlib.import_module("school_lab.__main__")
    output = capsys.readouterr()
    assert callable(module.main)
    assert not output.out and not output.err
