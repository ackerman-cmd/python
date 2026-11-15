"""Extract and compare source features without executing submitted code."""

import ast
import io
import tokenize
from collections import deque

from school_lab.analyzers.basic import template_ranges
from school_lab.domain.similarity import CodeFeatures, Feature, LineRange, merged_ranges

TOKEN_VERSION = "token-jaccard-1"
_IGNORED = {
    tokenize.COMMENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.NEWLINE,
    tokenize.NL,
}


def token_features(code: str, template: str) -> CodeFeatures:
    """Return unique 3-grams and their first spans, without bridging template blocks."""
    ranges = merged_ranges(template_ranges(code, template))
    normalized = code.replace("\r\n", "\n").replace("\r", "\n")
    spans: dict[Feature, LineRange] = {}
    window: deque[tuple[str, int, int]] = deque(maxlen=3)
    index = 0
    try:
        # tokenize alone also accepts some syntactically invalid sequences.
        ast.parse(normalized)
        for item in tokenize.generate_tokens(io.StringIO(normalized).readline):
            if item.type in _IGNORED:
                continue
            start, end = item.start[0], item.end[0]
            while index < len(ranges) and ranges[index][1] < start:
                index += 1
                window.clear()
            if index < len(ranges) and ranges[index][0] <= end:
                window.clear()
                continue
            window.append((item.string, start, end))
            if len(window) == 3:
                spans.setdefault(tuple(value[0] for value in window), (window[0][1], end))
    except (SyntaxError, tokenize.TokenError, RecursionError) as exc:
        line = getattr(exc, "lineno", None)
        where = f" (строка {line})" if line else ""
        return CodeFeatures({}, ranges, f"{type(exc).__name__}{where}")
    return CodeFeatures(spans, ranges)
