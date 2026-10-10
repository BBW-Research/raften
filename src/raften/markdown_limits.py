"""Fixed parsing envelope and indexes for untrusted Markdown."""

from bisect import bisect_left
from dataclasses import dataclass

from raften.diagnostics import DOC_RESOURCE_LIMIT
from raften.repository_errors import fail_repository


MAX_MARKDOWN_BYTES = 256 * 1024
MAX_MARKDOWN_WORK = 2 * 1024 * 1024
MAX_DOCUMENT_LINKS = 4096
MAX_DOCUMENT_ANCHORS = 4096
MAX_TOTAL_LINKS = 65_536
MAX_TOTAL_ANCHORS = 65_536
MAX_GRAPH_EDGES = 65_536
MAX_DIRECTORY_RECORDS = 65_536
MAX_DOCUMENT_LINK_BYTES = 2 * 1024 * 1024
MAX_TOTAL_LINK_BYTES = 16 * 1024 * 1024


def require_semantic(resource: str, actual: int, limit: int, path: str | None = None) -> None:
    if actual > limit:
        fail_repository(DOC_RESOURCE_LIMIT, "documentation exceeds an operational semantic limit",
                        path=path, details=(("resource", resource), ("limit", limit)))


@dataclass(slots=True)
class SemanticBudget:
    links: int = 0
    anchors: int = 0
    link_bytes: int = 0

    def link(self, path: str) -> None:
        require_semantic("total_links", self.links + 1, MAX_TOTAL_LINKS, path)
        self.links += 1

    def anchor(self, path: str) -> None:
        require_semantic("total_anchors", self.anchors + 1, MAX_TOTAL_ANCHORS, path)
        self.anchors += 1

    def retain_link(self, count: int, path: str) -> None:
        require_semantic("total_link_bytes", self.link_bytes + count, MAX_TOTAL_LINK_BYTES, path)
        self.link_bytes += count


class ParseBudget:
    def __init__(self, path: str, text: str, *, semantic: SemanticBudget | None = None) -> None:
        self.path = path
        self.work = 0
        self.links = self.anchors = self.link_bytes = 0
        self.semantic = semantic or SemanticBudget()
        # Check characters first so even the UTF-8 size check is bounded.
        if len(text) > MAX_MARKDOWN_BYTES or len(text.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            self.fail("markdown_bytes", MAX_MARKDOWN_BYTES)

    def charge(self, count: int) -> None:
        self.work += count
        if self.work > MAX_MARKDOWN_WORK:
            self.fail("markdown_work", MAX_MARKDOWN_WORK)

    def link(self, destination: str) -> None:
        require_semantic("document_links", self.links + 1, MAX_DOCUMENT_LINKS, self.path)
        self.semantic.link(self.path)
        self.links += 1
        self.charge(len(destination))

    def anchor(self) -> None:
        require_semantic("document_anchors", self.anchors + 1, MAX_DOCUMENT_ANCHORS, self.path)
        self.semantic.anchor(self.path)
        self.anchors += 1

    def retain_link(self, count: int) -> None:
        require_semantic("document_link_bytes", self.link_bytes + count,
                         MAX_DOCUMENT_LINK_BYTES, self.path)
        self.semantic.retain_link(count, self.path)
        self.link_bytes += count

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
