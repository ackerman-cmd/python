from school_lab.domain.errors import SubmissionError
from school_lab.domain.hashing import submission_hash
from school_lab.domain.models import Submission


class InMemorySubmissionRepository:
    def __init__(self) -> None:
        self._submissions: dict[str, Submission] = {}

    def get(self, submission_id: str) -> Submission | None:
        return self._submissions.get(submission_id)

    def add(self, submission: Submission) -> None:
        previous = self.get(submission.submission_id)
        if previous is not None:
            if submission_hash(previous) != submission_hash(submission):
                raise SubmissionError("conflict", "submission_id", "ID уже связан с другой версией")
            return
        self._submissions[submission.submission_id] = submission

    def __len__(self) -> int:
        return len(self._submissions)

    def all(self) -> tuple[Submission, ...]:
        return tuple(self._submissions.values())
