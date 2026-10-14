from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from typing import cast

from school_lab.adapters.acceptance import import_source
from school_lab.adapters.dto import parse_submission
from school_lab.adapters.sources import InMemorySource, JsonlSource
from school_lab.analyzers.extensions import DeclarationAnalyzer
from school_lab.bootstrap import build_application, load_assignments, load_config
from school_lab.domain.errors import ConfigurationError, SubmissionError
from school_lab.domain.hashing import submission_hash


def run_demo(data_dir: Path) -> dict[str, object]:
    config = load_config(data_dir / "config.json")
    assignments = load_assignments(data_dir / "assignments.json")
    app = build_application(config)
    first = import_source(JsonlSource(data_dir / "submissions.jsonl"), app.acceptance_adapter)
    if not first.accepted:
        raise ConfigurationError("В корпусе нет корректных сдач", field="submissions")
    for submission in app.repository.all():
        if submission.assignment_id not in assignments:
            raise ConfigurationError(
                f"Задание {submission.assignment_id} отсутствует", field="assignment_id"
            )
    second = import_source(JsonlSource(data_dir / "submissions.jsonl"), app.acceptance_adapter)
    reports = [
        asdict(
            app.analysis_service.run(
                submission.submission_id, name, app.context(assignments[submission.assignment_id])
            )
        )
        for submission in app.repository.all()
        for name in app.registry.names
    ]
    original = app.repository.get(first.accepted[0])
    assert original is not None
    previous_hash = submission_hash(original)
    changed = asdict(original)
    changed["text"] = original.text + "\nИзменение с тем же ID"
    try:
        app.acceptance_adapter.accept_payload(changed)
    except SubmissionError as exc:
        conflict = exc.to_dict()
    else:
        raise AssertionError("Ожидался conflict")
    original_preserved = (
        app.repository.get(original.submission_id) is original
        and submission_hash(original) == previous_hash
    )
    mixed_app = build_application(config)
    mixed = import_source(
        JsonlSource(data_dir / "invalid_submissions.jsonl"), mixed_app.acceptance_adapter
    )
    memory_app = build_application(config)
    memory = import_source(
        InMemorySource([asdict(value) for value in app.repository.all()]),
        memory_app.acceptance_adapter,
    )

    service_before = app.analysis_service
    app.registry.register("declaration", DeclarationAnalyzer)
    declared = next(
        (value for value in app.repository.all() if value.ai_declaration.used), original
    )
    extension_report = app.analysis_service.run(
        declared.submission_id, "declaration", app.context(assignments[declared.assignment_id])
    )
    return {
        "first_import": first.to_dict(),
        "repeat_import": second.to_dict(),
        "mixed_import": mixed.to_dict(),
        "in_memory_import": memory.to_dict(),
        "conflict": conflict,
        "original_preserved": original_preserved,
        "repository_size": len(app.repository),
        "report_count": len(reports),
        "reports": reports,
        "extension": {
            "same_service": service_before is app.analysis_service,
            "registered": app.registry.names,
            "report": asdict(extension_report),
        },
    }


def example_payload(data_dir: Path) -> dict[str, object]:
    with JsonlSource(data_dir / "submissions.jsonl").open() as records:
        first = next(records, None)
        if first is None:
            raise ConfigurationError("Учебный корпус пуст", field="submissions")
        if first.error is not None:
            raise first.error
        if not isinstance(first.raw, dict):
            raise SubmissionError(
                "schema_error", "submission", "Учебная запись должна быть объектом"
            )
        parse_submission(first.raw)
        return deepcopy(cast(dict[str, object], first.raw))
