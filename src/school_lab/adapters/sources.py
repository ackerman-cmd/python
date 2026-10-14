from collections.abc import Generator, Iterator, Sequence
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import TextIO

from school_lab.adapters.json_codec import decode_json
from school_lab.application.ports import SourceRecord
from school_lab.domain.errors import SubmissionError


def _records(handle: TextIO, limit: int) -> Generator[SourceRecord, None, None]:
    line_no = 0
    while line := handle.readline(limit + 1):
        line_no += 1
        if len(line) > limit:
            while not line.endswith("\n"):
                line = handle.readline(limit + 1)
                if not line:
                    break
            yield SourceRecord(
                line_no,
                error=SubmissionError("invalid_json", "json", "Превышен лимит длины строки"),
            )
            continue
        try:
            raw = decode_json(line)
        except SubmissionError as exc:
            yield SourceRecord(line_no, error=exc)
        else:
            yield SourceRecord(line_no, raw=raw)


class JsonlSource:
    def __init__(self, path: Path, *, max_line_chars: int = 1_000_000) -> None:
        if type(max_line_chars) is not int or max_line_chars < 1:
            raise ValueError("max_line_chars должен быть положительным int")
        self.path = path
        self.max_line_chars = max_line_chars

    @contextmanager
    def open(self) -> Iterator[Iterator[SourceRecord]]:
        with self.path.open("r", encoding="utf-8", newline="") as handle:
            records = _records(handle, self.max_line_chars)
            try:
                yield records
            finally:
                records.close()


class InMemorySource:
    def __init__(self, values: Sequence[object]) -> None:
        self._values = deepcopy(list(values))

    @contextmanager
    def open(self) -> Iterator[Iterator[SourceRecord]]:
        records = (
            SourceRecord(number, raw=deepcopy(value))
            for number, value in enumerate(self._values, 1)
        )
        try:
            yield records
        finally:
            records.close()


class StreamSource:
    def __init__(self, stream: TextIO) -> None:
        self.stream = stream

    @contextmanager
    def open(self) -> Iterator[Iterator[SourceRecord]]:
        records = _records(self.stream, 1_000_000)
        try:
            yield records
        finally:
            records.close()
