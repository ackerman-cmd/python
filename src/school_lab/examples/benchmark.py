import platform
from copy import deepcopy
from pathlib import Path
from statistics import median
from time import perf_counter

import pydantic

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.sources import InMemorySource
from school_lab.bootstrap import build_application
from school_lab.examples.demo import example_payload


def benchmark_import(data_dir: Path, records: int, repeats: int) -> dict[str, object]:
    if records < 1 or repeats < 1:
        raise ValueError("records и repeats должны быть положительными")
    base = example_payload(data_dir)
    corpus = []
    for number in range(records):
        payload = deepcopy(base)
        payload["submission_id"] = f"benchmark-{number}"
        corpus.append(payload)
    durations = []
    for _ in range(repeats):
        app = build_application()
        start = perf_counter()
        summary = import_source(InMemorySource(corpus), app.acceptance_adapter)
        durations.append((perf_counter() - start) * 1000)
        assert len(summary.accepted) == records and not summary.errors and not summary.duplicate
    return {
        "python": platform.python_version(),
        "pydantic": pydantic.__version__,
        "platform": platform.platform(),
        "records": records,
        "repeats": repeats,
        "durations_ms": durations,
        "median_ms": median(durations),
        "min_ms": min(durations),
        "max_ms": max(durations),
        "scope": "Создание InMemorySource, копирование, DTO, домен, SHA-256 и приём; без анализа",
    }
