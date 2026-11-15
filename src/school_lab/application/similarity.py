"""Pair comparison and ranked retrieval, independent of storage and CLI."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from heapq import nsmallest

from school_lab.domain.errors import AnalysisFailure
from school_lab.domain.hashing import stable_hash, submission_hash
from school_lab.domain.models import AnalysisContext, Assignment, Submission
from school_lab.domain.similarity import CodeFeatures, LineRange, jaccard, merged_ranges


@dataclass(frozen=True, slots=True)
class IndexedSubmission:
    submission_id: str
    student_id: str
    assignment_id: str
    submission_hash: str
    features: CodeFeatures


@dataclass(frozen=True, slots=True)
class PairEvidence:
    submission_id: str
    submission_hash: str
    matched_lines: tuple[LineRange, ...]
    template_lines: tuple[LineRange, ...]
    diagnostic: str | None


@dataclass(frozen=True, slots=True)
class PairResult:
    score: float | None
    review_required: bool
    left: PairEvidence
    right: PairEvidence


@dataclass(frozen=True, slots=True)
class SearchResult:
    assignment_id: str
    method: str
    config_hash: str
    comparisons: int
    same_student_versions: tuple[str, ...]
    candidates: tuple[PairResult, ...]


class ComparisonService:
    """Build a feature cache from any iterable and compare eligible submissions."""

    def __init__(
        self,
        submissions: Iterable[Submission],
        assignments: Mapping[str, Assignment],
        *,
        method: str,
        extractor: Callable[[str, str], CodeFeatures],
        config_version: str = "1",
    ) -> None:
        self.method = method
        self.config_hashes = {
            identifier: stable_hash(
                {"method": method, **AnalysisContext(assignment, config_version).config_payload()}
            )
            for identifier, assignment in assignments.items()
        }
        self._cache: dict[tuple[str, str], CodeFeatures] = {}
        self._entries: dict[str, IndexedSubmission] = {}
        self._groups: dict[str, list[IndexedSubmission]] = {}
        for submission in submissions:
            assignment = assignments.get(submission.assignment_id)
            if assignment is None:
                raise AnalysisFailure("Неизвестное задание сдачи", field="assignment_id")
            digest = submission_hash(submission)
            existing = self._entries.get(submission.submission_id)
            if existing is not None:
                if existing.submission_hash != digest:
                    raise AnalysisFailure("Конфликт версий сдачи", field="submission_id")
                continue
            key = (digest, self.config_hashes[submission.assignment_id])
            if key not in self._cache:
                self._cache[key] = extractor(submission.code, assignment.allowed_template)
            indexed = IndexedSubmission(
                submission.submission_id,
                submission.student_id,
                submission.assignment_id,
                digest,
                self._cache[key],
            )
            self._entries[indexed.submission_id] = indexed
            self._groups.setdefault(indexed.assignment_id, []).append(indexed)

    def _entry(self, submission_id: str) -> IndexedSubmission:
        try:
            return self._entries[submission_id]
        except KeyError as exc:
            raise AnalysisFailure("Сдача не найдена", field="submission_id") from exc

    @staticmethod
    def _validate_threshold(threshold: float) -> None:
        if not 0 < threshold <= 1:
            raise AnalysisFailure("Порог должен быть в интервале (0, 1]", field="threshold")

    @staticmethod
    def _result(
        left: IndexedSubmission,
        right: IndexedSubmission,
        score: float | None,
        threshold: float,
    ) -> PairResult:
        common = left.features.spans.keys() & right.features.spans.keys() if score else set()

        def evidence(entry: IndexedSubmission) -> PairEvidence:
            return PairEvidence(
                entry.submission_id,
                entry.submission_hash,
                merged_ranges(entry.features.spans[feature] for feature in common),
                entry.features.template,
                entry.features.diagnostic,
            )

        return PairResult(
            score, score is not None and score >= threshold, evidence(left), evidence(right)
        )

    def compare(self, left_id: str, right_id: str, *, threshold: float = 0.5) -> PairResult:
        """Compare two students' submissions for the same assignment."""
        self._validate_threshold(threshold)
        left, right = self._entry(left_id), self._entry(right_id)
        if left.assignment_id != right.assignment_id:
            raise AnalysisFailure("Сдачи относятся к разным заданиям", field="assignment_id")
        if left.student_id == right.student_id:
            raise AnalysisFailure("Нужны сдачи разных студентов", field="student_id")
        return self._result(left, right, jaccard(left.features, right.features), threshold)

    def top_k(self, submission_id: str, *, k: int = 5, threshold: float = 0.5) -> SearchResult:
        """Return highest scores first, breaking ties by submission ID."""
        self._validate_threshold(threshold)
        if type(k) is not int or k < 1:
            raise AnalysisFailure("k должно быть положительным целым числом", field="k")
        left = self._entry(submission_id)
        group = self._groups[left.assignment_id]
        same_student = tuple(
            sorted(
                item.submission_id
                for item in group
                if item.student_id == left.student_id and item.submission_id != submission_id
            )
        )
        comparisons = 0

        def score_items() -> Iterable[tuple[float, str, float | None, IndexedSubmission]]:
            nonlocal comparisons
            for item in group:
                if item.student_id == left.student_id:
                    continue
                comparisons += 1
                score = jaccard(left.features, item.features)
                yield (-score if score is not None else 1.0, item.submission_id, score, item)

        best = nsmallest(k, score_items(), key=lambda item: (item[0], item[1]))
        return SearchResult(
            left.assignment_id,
            self.method,
            self.config_hashes[left.assignment_id],
            comparisons,
            same_student,
            tuple(self._result(left, item, score, threshold) for _, _, score, item in best),
        )
