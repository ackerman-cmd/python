"""Measure cold build, warm top-k, candidate recall, and Python allocation peaks."""

import argparse
import cProfile
import json
import platform
import random
import tracemalloc
from collections.abc import Iterator
from pathlib import Path
from statistics import median
from time import perf_counter

import pydantic

from school_lab.adapters.dto import parse_submission
from school_lab.adapters.sources import JsonlSource
from school_lab.analyzers.similarity import TOKEN_VERSION, token_features
from school_lab.application.similarity import INDEX_VERSION, ComparisonService, SearchResult
from school_lab.domain.models import Assignment, Submission

ROOT = Path(__file__).resolve().parents[2]
SIZES = (100, 1000, 5000)
K = 5
QUERIES = 16
REPEATS = 3
SEED = 20261115
ASSIGNMENT = Assignment("load", "", ())


def generate(path: Path, size: int, seed: int) -> None:
    rng = random.Random(seed)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for i in range(size):
            lane = 64 + i if i < 4 else rng.randrange(64)
            numbers = [lane * 37 + j for j in range(8)]
            code = (
                f"start{lane} = {numbers[0]} + {numbers[1]} * {numbers[2]}\n"
                f"finish{lane} = start{lane} - {numbers[3]} ** {numbers[4]} + {numbers[5]}\n"
            )
            row = {
                "schema_version": 1,
                "submission_id": f"load-{i:05d}",
                "student_id": f"student-{i:05d}",
                "assignment_id": ASSIGNMENT.assignment_id,
                "submitted_at": "2026-10-01T12:00:00+03:00",
                "text": "",
                "code": code,
                "template_id": None,
                "ai_declaration": {
                    "used": False,
                    "tool": None,
                    "purpose": None,
                    "verified_by_student": True,
                },
            }
            handle.write(json.dumps(row) + "\n")


def validated(path: Path) -> Iterator[Submission]:
    with JsonlSource(path).open() as records:
        for record in records:
            if record.error:
                raise record.error
            yield parse_submission(record.raw)


def run(path: Path, indexed: bool) -> tuple[float, float, tuple[SearchResult, ...]]:
    start = perf_counter()
    service = ComparisonService(
        validated(path),
        {ASSIGNMENT.assignment_id: ASSIGNMENT},
        method=TOKEN_VERSION,
        extractor=token_features,
        indexed=indexed,
    )
    middle = perf_counter()
    answers = tuple(service.top_k(f"load-{i:05d}", k=K) for i in range(QUERIES))
    return (middle - start) * 1000, (perf_counter() - middle) * 1000, answers


def recalls(
    reference: tuple[SearchResult, ...], indexed: tuple[SearchResult, ...]
) -> dict[str, float | int | None]:
    all_found = all_total = positive_found = positive_total = 0
    for full, filtered in zip(reference, indexed, strict=True):
        all_ids = {row.right.submission_id for row in full.candidates}
        positive = {row.right.submission_id for row in full.candidates if row.score}
        found = {row.right.submission_id for row in filtered.candidates}
        all_found += len(found & all_ids)
        all_total += len(all_ids)
        positive_found += len(found & positive)
        positive_total += len(positive)
    return {
        "all_top_k_recall": all_found / all_total,
        "all_top_k_found": all_found,
        "all_top_k_total": all_total,
        "positive_top_k_recall": positive_found / positive_total if positive_total else None,
        "positive_top_k_found": positive_found,
        "positive_top_k_total": positive_total,
    }


def measure(path: Path, size: int) -> dict[str, object]:
    samples: dict[bool, list[dict[str, float | int]]] = {False: [], True: []}
    answers: dict[bool, tuple[SearchResult, ...]] = {}
    for rep in range(REPEATS):
        for indexed in (False, True) if rep % 2 == 0 else (True, False):
            build_ms, query_ms, answers[indexed] = run(path, indexed)
            tracemalloc.start()
            try:
                run(path, indexed)
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            samples[indexed].append(
                {
                    "build_ms": build_ms,
                    "query_ms": query_ms,
                    "total_ms": build_ms + query_ms,
                    "peak_bytes": peak,
                    "comparisons": sum(answer.comparisons for answer in answers[indexed]),
                }
            )
    full, filtered = samples[False], samples[True]
    return {
        "records": size,
        "full_pairs_if_all_queried": size * (size - 1) // 2,
        "full": {
            "samples": full,
            "median": {key: median(row[key] for row in full) for key in full[0]},
        },
        "indexed": {
            "samples": filtered,
            "median": {key: median(row[key] for row in filtered) for key in filtered[0]},
        },
        "query_speedup": median(row["query_ms"] for row in full)
        / median(row["query_ms"] for row in filtered),
        "candidate_recall": recalls(answers[False], answers[True]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/lab2/benchmark.json")
    parser.add_argument("--work-dir", type=Path, default=ROOT / "artifacts/lab2")
    parser.add_argument("--profile", action="store_true", help="Profile a separate full run")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    measured = []
    for size in SIZES:
        path = args.work_dir / f"load-{size}.jsonl"
        generate(path, size, SEED)
        measured.append(measure(path, size))
        print(f"Measured {size} submissions", flush=True)
    if args.profile:
        profiler = cProfile.Profile()
        profiler.runcall(run, path, False)
        profiler.dump_stats(str(args.work_dir / "full-5000.prof"))
    result = {
        "python": platform.python_version(),
        "pydantic": pydantic.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "seed": SEED,
        "repeats": REPEATS,
        "queries_per_run": QUERIES,
        "top_k": K,
        "method": TOKEN_VERSION,
        "index_version": INDEX_VERSION,
        "load": "64 shared lanes and four unique probes; synthetic short code, single assignment",
        "peak": "Python allocations via tracemalloc in separate runs; not process RSS",
        "runs": measured,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
