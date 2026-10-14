from dataclasses import asdict, dataclass, field

from school_lab.adapters.dto import parse_submission
from school_lab.application.ports import SubmissionSource
from school_lab.application.services import SubmissionService
from school_lab.domain.errors import SubmissionError
from school_lab.domain.models import Acceptance


class AcceptanceAdapter:
    def __init__(self, service: SubmissionService) -> None:
        self.service = service

    def accept_payload(self, raw: object) -> Acceptance:
        return self.service.accept(parse_submission(raw))


@dataclass
class ImportSummary:
    accepted: list[str] = field(default_factory=list)
    duplicate: list[str] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def import_source(source: SubmissionSource, adapter: AcceptanceAdapter) -> ImportSummary:
    summary = ImportSummary()
    with source.open() as records:
        for record in records:
            if record.error is not None:
                summary.errors.append({"line_no": record.line_no, **record.error.to_dict()})
                continue
            try:
                result = adapter.accept_payload(record.raw)
            except SubmissionError as exc:
                summary.errors.append({"line_no": record.line_no, **exc.to_dict()})
            else:
                target = summary.accepted if result.status == "accepted" else summary.duplicate
                target.append(result.submission_id)
    return summary
