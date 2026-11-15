"""Extract and compare source features without executing submitted code."""

import ast
import io
import tokenize
from collections import deque

from school_lab.analyzers.basic import template_ranges
from school_lab.domain.similarity import CodeFeatures, Feature, LineRange, merged_ranges

TOKEN_VERSION = "token-jaccard-1"
AST_VERSION = "ast-jaccard-1"
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


def ast_features(code: str, template: str) -> CodeFeatures:
    """Collect AST node signatures using first-seen identifier normalization."""
    ranges = merged_ranges(template_ranges(code, template))
    spans: dict[Feature, LineRange] = {}
    names: dict[str, str] = {}
    pending: list[ast.AST]
    try:
        pending = [ast.parse(code)]
    except (SyntaxError, RecursionError) as exc:
        line = getattr(exc, "lineno", None)
        where = f" (строка {line})" if line else ""
        return CodeFeatures({}, ranges, f"{type(exc).__name__}{where}")

    def allowed(node: ast.AST) -> bool:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None) or start
        if start is None or end is None:
            return True
        return not any(a <= start <= end <= b for a, b in ranges)

    while pending:
        node = pending.pop()
        first = getattr(node, "lineno", None)
        last = getattr(node, "end_lineno", None) or first
        children = [child for child in ast.iter_child_nodes(node) if allowed(child)]
        pending.extend(reversed(children))
        if first is None or last is None:
            continue
        parts = [type(node).__name__]
        for field, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                if allowed(value):
                    parts.append(f"{field}:{type(value).__name__}")
            elif isinstance(value, list):
                kinds = [
                    type(item).__name__
                    for item in value
                    if isinstance(item, ast.AST) and allowed(item)
                ]
                parts.append(f"{field}:[{','.join(kinds)}]")
            elif isinstance(value, str) and (
                field in {"id", "arg"}
                or (
                    field == "name"
                    and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                )
            ):
                parts.append(f"{field}={names.setdefault(value, str(len(names)))}")
            else:
                parts.append(f"{field}={value!r}")
        spans.setdefault(tuple(parts), (first, last))
    return CodeFeatures(spans, ranges)
