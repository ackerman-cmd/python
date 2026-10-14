import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace

import pytest

from school_lab.adapters.dto import SubmissionInput, parse_submission
from school_lab.bootstrap import Application
from school_lab.domain.errors import SubmissionError
from school_lab.domain.hashing import submission_hash
from school_lab.domain.models import AIDeclaration


def test_dto_to_domain_and_input_unchanged(payload: dict[str, object], app: Application) -> None:
    original = deepcopy(payload)
    dto = SubmissionInput.model_validate(payload)
    accepted = app.acceptance_adapter.accept_payload(payload)
    assert asdict(dto.to_domain()) == original == payload
    assert accepted.submission == dto.to_domain()
    assert accepted.status == "accepted"


@pytest.mark.parametrize(
    ("field", "value", "code", "error_field"),
    [
        ("student_id", "  ", "schema_error", "student_id"),
        ("student_id", 123, "schema_error", "student_id"),
        ("submission_id", "", "schema_error", "submission_id"),
        ("assignment_id", "", "schema_error", "assignment_id"),
        ("schema_version", True, "schema_error", "schema_version"),
        ("schema_version", "1", "schema_error", "schema_version"),
        ("schema_version", 2, "unsupported_version", "schema_version"),
        ("submitted_at", "2026-09-01T10:01:00", "schema_error", "submitted_at"),
        ("submitted_at", "yesterday", "schema_error", "submitted_at"),
        ("submitted_at", 42, "schema_error", "submitted_at"),
        ("template_id", " ", "schema_error", "template_id"),
        ("text", None, "schema_error", "text"),
        ("code", [], "schema_error", "code"),
        ("studnet_id", "typo", "schema_error", "studnet_id"),
    ],
)
def test_invalid_fields_do_not_change_input_or_repository(
    payload: dict[str, object],
    app: Application,
    field: str,
    value: object,
    code: str,
    error_field: str,
) -> None:
    payload[field] = value
    original = deepcopy(payload)
    with pytest.raises(SubmissionError) as caught:
        app.acceptance_adapter.accept_payload(payload)
    assert caught.value.code == code
    assert caught.value.field == error_field
    assert caught.value.message
    assert payload == original and len(app.repository) == 0


@pytest.mark.parametrize("field", ["text", "template_id", "ai_declaration", "schema_version"])
def test_missing_required_field(payload: dict[str, object], field: str) -> None:
    del payload[field]
    with pytest.raises(SubmissionError) as caught:
        parse_submission(payload)
    assert caught.value.field == field


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"used": "false"}, "ai_declaration.used"),
        ({"verified_by_student": 1}, "ai_declaration.verified_by_student"),
        ({"unknown": True}, "ai_declaration.unknown"),
        ({"tool": " "}, "ai_declaration.tool"),
        ({"used": True}, "ai_declaration.tool"),
        ({"used": True, "tool": "assistant"}, "ai_declaration.purpose"),
    ],
)
def test_declaration_validation(
    payload: dict[str, object],
    change: dict[str, object],
    field: str,
) -> None:
    declaration = payload["ai_declaration"]
    assert isinstance(declaration, dict)
    declaration.update(change)
    with pytest.raises(SubmissionError) as caught:
        parse_submission(payload)
    assert caught.value.field == field


def test_content_and_original_whitespace(payload: dict[str, object]) -> None:
    payload.update(text="\n  ", code="\t")
    with pytest.raises(SubmissionError, match="text/code"):
        parse_submission(payload)
    payload["code"] = "\n print('hello')  \n"
    assert parse_submission(payload).code == payload["code"]


def test_duplicate_returns_saved_object_and_conflict_preserves_it(
    payload: dict[str, object],
    app: Application,
) -> None:
    first = app.acceptance_adapter.accept_payload(payload)
    second = app.acceptance_adapter.accept_payload(payload)
    assert second.status == "duplicate"
    assert second.submission is first.submission and len(app.repository) == 1
    changed = {**payload, "code": str(payload["code"]) + "\n"}
    with pytest.raises(SubmissionError, match="conflict"):
        app.acceptance_adapter.accept_payload(changed)
    assert app.repository.get(first.submission_id) is first.submission
    assert submission_hash(first.submission) == first.submission_hash

    changed["submission_id"] = "new-version"
    assert app.acceptance_adapter.accept_payload(changed).status == "accepted"
    assert len(app.repository) == 2


def test_repository_itself_refuses_overwrite(payload: dict[str, object], app: Application) -> None:
    original = parse_submission(payload)
    app.repository.add(original)
    app.repository.add(original)
    with pytest.raises(SubmissionError, match="conflict"):
        app.repository.add(replace(original, text="Другое содержимое"))
    assert app.repository.get(original.submission_id) is original and len(app.repository) == 1


def test_nested_domain_is_immutable_and_has_invariants(payload: dict[str, object]) -> None:
    value = parse_submission(payload)
    with pytest.raises(FrozenInstanceError):
        value.code = "changed"
    with pytest.raises(FrozenInstanceError):
        value.ai_declaration.used = True
    with pytest.raises(SubmissionError):
        replace(value, student_id="")
    with pytest.raises(SubmissionError):
        AIDeclaration(True, None, None, True)


def test_hash_stable_across_order_and_processes(payload: dict[str, object]) -> None:
    value = parse_submission(payload)
    reordered = dict(reversed(list(payload.items())))
    assert submission_hash(value) == submission_hash(parse_submission(reordered))
    script = (
        "import json,sys; from school_lab.adapters.dto import parse_submission; "
        "from school_lab.domain.hashing import submission_hash; "
        "print(submission_hash(parse_submission(json.load(sys.stdin))))"
    )
    hashes = [
        subprocess.check_output(
            [sys.executable, "-c", script],
            input=json.dumps(payload),
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
        ).strip()
        for seed in ("1", "42")
    ]
    assert hashes == [submission_hash(value)] * 2
    assert submission_hash(replace(value, code=value.code + "\n")) != hashes[0]
