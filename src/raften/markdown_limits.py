"""Fixed parsing envelope and indexes for untrusted Markdown."""

from bisect import bisect_left

from raften.diagnostics import DOC_RESOURCE_LIMIT
from raften.repository_errors import fail_repository


MAX_MARKDOWN_BYTES = 256 * 1024
MAX_MARKDOWN_WORK = 2 * 1024 * 1024


class ParseBudget:
    def __init__(self, path: str, text: str) -> None:
        self.path = path
        self.work = 0
        # Check characters first so even the UTF-8 size check is bounded.
        if len(text) > MAX_MARKDOWN_BYTES or len(text.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            self.fail("markdown_bytes", MAX_MARKDOWN_BYTES)

    def charge(self, count: int) -> None:
        self.work += count
        if self.work > MAX_MARKDOWN_WORK:
            self.fail("markdown_work", MAX_MARKDOWN_WORK)

    def fail(self, resource: str, limit: int) -> None:
        fail_repository(
            DOC_RESOURCE_LIMIT, "Markdown exceeds an operational parsing limit",
            path=self.path, details=(("resource", resource), ("limit", limit)),
        )


class DelimiterRuns:
    """Index maximal delimiter runs once, including escaped closing runs."""

    def __init__(self, text: str) -> None:
        self.runs: dict[tuple[str, int], list[int]] = {}
        index = 0
        while index < len(text):
            character = text[index]
            if character not in "`*_~":
                index += 1
                continue
            end = index + 1
            while end < len(text) and text[end] == character:
                end += 1
            self.runs.setdefault((character, end - index), []).append(index)
            index = end

    def closing(self, start: int, character: str, length: int) -> int | None:
        positions = self.runs.get((character, length), ())
        index = bisect_left(positions, start)
        return positions[index] if index < len(positions) else None
