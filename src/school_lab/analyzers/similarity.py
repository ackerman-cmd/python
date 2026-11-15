"""Extract and compare source features without executing submitted code."""

import ast
import io
import tokenize
import warnings
from collections import deque

from school_lab.analyzers.basic import normalize_newlines, template_ranges
from school_lab.domain.similarity import CodeFeatures, Feature, LineRange, merged_ranges

TOKEN_VERSION = "token-jaccard-2"
AST_VERSION = "ast-jaccard-2"
_IGNORED = {
    tokenize.COMMENT,
    tokenize.DEDENT,
    tokenize.ENCODING,
    tokenize.ENDMARKER,
    tokenize.INDENT,
    tokenize.NEWLINE,
    tokenize.NL,
}


def _check_compilable(source: str | ast.Module) -> None:
    # Build a code object to check scope and control flow; never execute it.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        compile(source, "<submission>", "exec", dont_inherit=True)


def _invalid(
    exc: SyntaxError | tokenize.TokenError | RecursionError, ranges: tuple[LineRange, ...]
) -> CodeFeatures:
    line = getattr(exc, "lineno", None)
    where = f" (строка {line})" if line else ""
    detail = f": {exc.msg}" if isinstance(exc, SyntaxError) else ""
    return CodeFeatures({}, ranges, f"{type(exc).__name__}{where}{detail}")


def _node_span(node: ast.AST) -> LineRange | None:
    start = getattr(node, "lineno", None)
    return (start, getattr(node, "end_lineno", None) or start) if start is not None else None


def token_features(code: str, template: str) -> CodeFeatures:
    """Return unique 3-grams and their first spans, without bridging template blocks."""
    ranges = merged_ranges(template_ranges(code, template))
    normalized = normalize_newlines(code)
    spans: dict[Feature, LineRange] = {}
    window: deque[tuple[str, int, int]] = deque(maxlen=3)
    index = 0
    try:
        _check_compilable(normalized)
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
        return _invalid(exc, ranges)
    return CodeFeatures(spans, ranges)


def ast_features(code: str, template: str) -> CodeFeatures:
    """Collect AST node signatures using first-seen identifier normalization."""
    ranges = merged_ranges(template_ranges(code, template))
    spans: dict[Feature, LineRange] = {}
    names: dict[str, str] = {}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            root = ast.parse(normalize_newlines(code))
        _check_compilable(root)
    except (SyntaxError, RecursionError) as exc:
        return _invalid(exc, ranges)

    def allowed(node: ast.AST) -> bool:
        span = _node_span(node)
        if span is None:
            return True
        start, end = span
        return not any(a <= start <= end <= b for a, b in ranges)

    pending: list[tuple[ast.AST, int | None]] = [(root, None)]
    while pending:
        node, owner_line = pending.pop()
        span = _node_span(node)
        children = [child for child in ast.iter_child_nodes(node) if allowed(child)]
        pending.extend((child, span[0] if span else None) for child in reversed(children))
        if isinstance(node, ast.arguments) and owner_line is not None:
            # The node has no location; its owner and its children mark the header.
            located = [child_span for child in children if (child_span := _node_span(child))]
            span = (owner_line, max((end for _, end in located), default=owner_line))
        if span is None:
            continue
        parts = [type(node).__name__]
        for field, value in ast.iter_fields(node):
            if isinstance(value, ast.AST):
                if allowed(value):
                    parts.append(f"{field}:{type(value).__name__}")
            elif isinstance(value, list):
                kinds = [
                    "None" if item is None else type(item).__name__
                    for item in value
                    if (isinstance(item, ast.AST) and allowed(item))
                    or (isinstance(node, ast.arguments) and item is None)
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
        spans.setdefault(tuple(parts), span)
    return CodeFeatures(spans, ranges)
