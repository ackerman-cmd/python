"""Similarity values and scoring over sets of source features."""

from collections.abc import Iterable
from dataclasses import dataclass

type LineRange = tuple[int, int]
type Feature = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CodeFeatures:
    """Feature keys with representative source spans and exact template matches."""

    spans: dict[Feature, LineRange]
    template: tuple[LineRange, ...]
    diagnostic: str | None = None


def merged_ranges(spans: Iterable[LineRange]) -> tuple[LineRange, ...]:
    """Combine overlapping or adjacent inclusive ranges."""
    result: list[LineRange] = []
    for start, end in sorted(spans):
        if result and start <= result[-1][1] + 1:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return tuple(result)


def jaccard(left: CodeFeatures, right: CodeFeatures) -> float | None:
    """Score valid inputs; invalid code or an empty union has no score."""
    if left.diagnostic or right.diagnostic:
        return None
    small, large = sorted((left.spans, right.spans), key=len)
    shared = sum(feature in large for feature in small)
    union = len(small) + len(large) - shared
    return shared / union if union else None
