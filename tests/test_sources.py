import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.json_codec import decode_json
from school_lab.adapters.sources import InMemorySource, JsonlSource, StreamSource
from school_lab.application.ports import SubmissionSource
from school_lab.bootstrap import Application
from school_lab.domain.errors import SubmissionError


@pytest.fixture(params=["memory", "jsonl"])
def source(request: pytest.FixtureRequest, tmp_path: Path) -> SubmissionSource:
    values: list[object] = [{"id": 1}, {"id": 2}]
    if request.param == "memory":
        return InMemorySource(values)
    path = tmp_path / "records.jsonl"
    path.write_text("\n".join(json.dumps(item) for item in values) + "\n", encoding="utf-8")
    return JsonlSource(path)


def test_source_contract_order_reopening_and_isolation(source: SubmissionSource) -> None:
    with source.open() as records:
        first = list(records)
    assert [record.line_no for record in first] == [1, 2]
    assert [record.raw for record in first] == [{"id": 1}, {"id": 2}]
    assert all(record.error is None for record in first)
    assert isinstance(first[0].raw, dict)
    first[0].raw["id"] = "mutation"
    with source.open() as records:
        assert [record.raw for record in records] == [{"id": 1}, {"id": 2}]


def test_memory_source_copies_original_collection() -> None:
    raw = [{"nested": {"used": False}}]
    source = InMemorySource(raw)
    raw[0]["nested"]["used"] = True
    with source.open() as records:
        assert next(records).raw == {"nested": {"used": False}}


@pytest.mark.parametrize("exit_mode", ["normal", "break", "exception"])
def test_file_closed_in_every_exit_path(tmp_path: Path, exit_mode: str) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text("{}\n{}\n", encoding="utf-8")
    handle = path.open(encoding="utf-8")
    source = JsonlSource(path)
    with patch("pathlib.Path.open", return_value=handle):
        if exit_mode == "exception":
            with pytest.raises(RuntimeError):
                with source.open() as records:
                    next(records)
                    raise RuntimeError("Ошибка потребителя")
        else:
            with source.open() as records:
                for _ in records:
                    if exit_mode == "break":
                        break
    assert handle.closed
    assert list(records) == []


@pytest.mark.parametrize("raw", ["{broken", "", '{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}'])
def test_strict_json_rejects_invalid_values(raw: str) -> None:
    with pytest.raises(SubmissionError) as caught:
        decode_json(raw)
    assert caught.value.code == "invalid_json"


def test_mixed_import_continues_after_errors(data_dir: Path, app: Application) -> None:
    summary = import_source(
        JsonlSource(data_dir / "invalid_submissions.jsonl"), app.acceptance_adapter
    )
    assert summary.accepted == ["sub-001", "sub-002"]
    assert summary.duplicate == ["sub-001"]
    assert [item["line_no"] for item in summary.errors] == [2, 4, 5]
    assert [item["code"] for item in summary.errors] == ["invalid_json", "conflict", "schema_error"]
    assert len(app.repository) == 2


def test_blank_line_and_length_limit_preserve_physical_line_numbers(tmp_path: Path) -> None:
    path = tmp_path / "long.jsonl"
    path.write_text("\n" + "x" * 30 + "\n{}\n", encoding="utf-8")
    with JsonlSource(path, max_line_chars=10).open() as records:
        values = list(records)
    assert [value.line_no for value in values] == [1, 2, 3]
    assert values[0].error is not None and values[1].error is not None
    assert values[2].raw == {}


def test_missing_file_is_source_error(tmp_path: Path, app: Application) -> None:
    with pytest.raises(FileNotFoundError):
        import_source(JsonlSource(tmp_path / "missing"), app.acceptance_adapter)


def test_caller_owns_stringio_stream() -> None:
    stream = io.StringIO("{}\n{}\n")
    with StreamSource(stream).open() as records:
        assert next(records).line_no == 1
    assert not stream.closed
    stream.close()
