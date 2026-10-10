"""Bounded JSON encoding with lazy row projection and atomic emission."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator

from raften import resource_limits as limits


def encode_report(value: object) -> str:
    """Retain only bounded encoded fragments; callers emit after success."""

    return join_report(_with_newline(_fragments(value, 0, [0])))


def _with_newline(values: Iterable[str]) -> Iterator[str]:
    yield from values
    yield "\n"


def join_report(values: Iterable[str]) -> str:

    fragments: list[str] = []
    total = 0
    for fragment in values:
        total += len(fragment.encode("utf-8"))
        limits.require_resource("report_bytes", total, limits.MAX_REPORT_BYTES,
                                operation="render-report")
        fragments.append(fragment)
    return "".join(fragments)


def _fragments(value: object, depth: int, items: list[int]) -> Iterator[str]:
    items[0] += 1
    limits.require_resource("report_items", items[0], limits.MAX_REPORT_ITEMS,
                            operation="render-report")
    if isinstance(value, dict):
        yield "{"
        for index, (key, child) in enumerate(value.items()):
            yield ("," if index else "") + "\n" + "  " * (depth + 1)
            yield json.dumps(key, ensure_ascii=False) + ": "
            yield from _fragments(child, depth + 1, items)
        if value:
            yield "\n" + "  " * depth
        yield "}"
    elif isinstance(value, (list, tuple, Iterator)):
        yield "["
        present = False
        for child in value:
            yield ("," if present else "") + "\n" + "  " * (depth + 1)
            present = True
            yield from _fragments(child, depth + 1, items)
        if present:
            yield "\n" + "  " * depth
        yield "]"
    else:
        yield json.dumps(value, ensure_ascii=False)
