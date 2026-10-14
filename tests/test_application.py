import json
from pathlib import Path

import pytest

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.sources import InMemorySource
from school_lab.bootstrap import Application, build_application, load_config
from school_lab.domain.errors import ConfigurationError
from school_lab.examples.demo import run_demo
from school_lab.interfaces.cli import main


@pytest.mark.parametrize(
    "config",
    [
        {"analyzers": [{"name": "unknown"}]},
        {"analyzers": [{"name": "length", "params": {"threshold": 10}}]},
        {"analyzers": [{"name": "length"}, {"name": "length"}]},
        {"analyzers": []},
        {"config_version": " "},
        {"config_version": "\ud800"},
        {"config_version": 1},
        {"unknown": True},
        {"analyzers": [{"name": "length", "unknown": 1}]},
    ],
)
def test_bad_configuration_rejected_at_startup(config: object) -> None:
    with pytest.raises(ConfigurationError):
        build_application(config)


def test_valid_config_selects_analyzers() -> None:
    app = build_application({"config_version": "2", "analyzers": [{"name": "length"}]})
    assert app.registry.names == ("length",) and app.config_version == "2"


def test_unicode_config_version_is_valid_at_startup() -> None:
    app = build_application({"config_version": "версия-🐍"})
    assert app.config_version == "версия-🐍"


def test_invalid_json_config_has_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_config(path)


def test_apps_do_not_share_state(payload: dict[str, object]) -> None:
    first, second = build_application(), build_application()
    first.acceptance_adapter.accept_payload(payload)
    assert len(first.repository) == 1 and len(second.repository) == 0
    assert first.registry is not second.registry


def test_source_replaced_by_memory(payload: dict[str, object], app: Application) -> None:
    summary = import_source(InMemorySource([payload]), app.acceptance_adapter)
    assert summary.accepted == ["sub-001"] and not summary.errors


def test_end_to_end(data_dir: Path) -> None:
    result = run_demo(data_dir)
    assert result["repository_size"] == 12
    assert result["report_count"] == 24
    assert result["original_preserved"] is True
    first, second = result["first_import"], result["repeat_import"]
    assert isinstance(first, dict) and isinstance(second, dict)
    assert len(first["accepted"]) == 12 and not first["errors"]
    assert second["duplicate"] == first["accepted"] and not second["accepted"]
    extension = result["extension"]
    assert isinstance(extension, dict) and extension["same_service"] is True


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("submissions.jsonl", 0), ("invalid_submissions.jsonl", 1)],
)
def test_cli_import_json_and_exit_code(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
    filename: str,
    expected: int,
) -> None:
    assert main(["import", str(data_dir / filename)]) == expected
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert not captured.err
    assert set(result) == {"accepted", "duplicate", "errors"}


def test_cli_missing_file_is_diagnostic_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["import", str(tmp_path / "missing")]) == 2
    captured = capsys.readouterr()
    assert not captured.out and json.loads(captured.err)["code"] == "source_error"
