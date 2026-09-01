"""Deterministic extraction of local Markdown links and anchors."""

from __future__ import annotations

import re
import unicodedata
from bisect import bisect_right
from html.parser import HTMLParser

from repo_context.markdown_lines import is_line_start, line_bounds, line_starts, physical_lines
from repo_context.markdown_links import extract_links, heading_display_text, inline_html_tag_end
from repo_context.model import Anchor, AnchorKind, MarkdownDocument, SourceLocation


def parse_markdown(
    source_path: str,
    text: str,
    *,
    known_directories: frozenset[str] = frozenset(),
) -> MarkdownDocument:
    """Extract supported links and anchors without repository access."""

    source_line_starts = line_starts(text)
    block_visible, inline_visible = _mask_ignored_regions(text)
    extraction = extract_links(
        source_path,
        inline_visible,
        known_directories,
        source_line_starts,
    )
    heading_visible = _mask_ranges(block_visible, extraction.definition_ranges)
    html_visible = _mask_ranges(
        inline_visible,
        extraction.definition_ranges + extraction.html_mask_ranges,
    )
    html_visible = _mask_escaped_html_openers(html_visible)
    anchors = _extract_anchors(
        source_path,
        heading_visible,
        html_visible,
        source_line_starts,
        extraction.defined_reference_labels,
    )
    return MarkdownDocument(source_path, extraction.links, anchors)


def _mask_ignored_regions(text: str) -> tuple[str, str]:
    block_visible = list(text)
    inline_visible = list(text)
    fence: tuple[str, int] | None = None
    index = 0
    while index < len(text):
        if is_line_start(text, index):
            content_end, line_end = line_bounds(text, index)
            content = text[index:content_end]
            if fence is not None:
                _blank(block_visible, index, line_end)
                _blank(inline_visible, index, line_end)
                if _closes_fence(content, fence):
                    fence = None
                index = line_end
                continue
            marker = _fence_marker(content)
            if marker is not None:
                fence = marker
                _blank(block_visible, index, line_end)
                _blank(inline_visible, index, line_end)
                index = line_end
                continue
        if text.startswith("<!--", index) and not _is_escaped(text, index):
            closing = text.find("-->", index + 4)
            end = len(text) if closing < 0 else closing + 3
            _blank(block_visible, index, end)
            _blank(inline_visible, index, end)
            index = end
            continue
        if text[index] == "`" and not _is_escaped(text, index):
            run = _run_length(text, index, "`")
            closing = _find_equal_run(text, index + run, "`", run)
            if closing is not None:
                end = closing + run
                _blank(inline_visible, index, end)
                if "\r" in text[index:end] or "\n" in text[index:end]:
                    _blank(block_visible, index, end)
                index = end
                continue
            index += run
            continue
        index += 1
    return "".join(block_visible), "".join(inline_visible)


def _fence_marker(line: str) -> tuple[str, int] | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3 or indent == len(line):
        return None
    character = line[indent]
    if character not in {"`", "~"}:
        return None
    run = _run_length(line, indent, character)
    if run < 3:
        return None
    if character == "`" and "`" in line[indent + run :]:
        return None
    return character, run


def _closes_fence(line: str, fence: tuple[str, int]) -> bool:
    character, minimum = fence
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3 or indent == len(line) or line[indent] != character:
        return False
    run = _run_length(line, indent, character)
    return run >= minimum and not line[indent + run :].strip(" \t")


def _find_equal_run(
    text: str,
    start: int,
    character: str,
    length: int,
) -> int | None:
    index = start
    while index < len(text):
        found = text.find(character, index)
        if found < 0:
            return None
        run = _run_length(text, found, character)
        if run == length:
            return found
        index = found + run
    return None


def _extract_anchors(
    source_path: str,
    heading_text: str,
    html_text: str,
    line_starts: tuple[int, ...],
    defined_reference_labels: frozenset[str],
) -> tuple[Anchor, ...]:
    candidates: list[tuple[int, AnchorKind, str]] = []
    lines = tuple((offset, line) for offset, line, _end in physical_lines(heading_text))
    for line_index, (offset, line) in enumerate(lines):
        atx = _atx_heading(line)
        if atx is not None:
            candidates.append((offset, AnchorKind.HEADING, atx))
        if line_index > 0 and _is_setext_underline(line):
            previous_offset, previous = lines[line_index - 1]
            if previous.strip() and _atx_heading(previous) is None:
                candidates.append((previous_offset, AnchorKind.HEADING, previous.strip()))

    parser = _ExplicitIdParser(line_starts)
    parser.feed(html_text)
    parser.close()
    candidates.extend(parser.candidates)
    candidates.sort(key=lambda item: (item[0], item[1].value, item[2]))

    occupied: set[str] = set()
    next_suffix: dict[str, int] = {}
    anchors: list[Anchor] = []
    for offset, kind, value in candidates:
        if kind is AnchorKind.HEADING:
            base = _slug(
                heading_display_text(
                    value,
                    defined_reference_labels=defined_reference_labels,
                )
            )
            if not base:
                continue
            identifier = base
            if identifier in occupied:
                suffix = next_suffix.get(base, 1)
                identifier = f"{base}-{suffix}"
                while identifier in occupied:
                    suffix += 1
                    identifier = f"{base}-{suffix}"
                next_suffix[base] = suffix + 1
            else:
                next_suffix.setdefault(base, 1)
        else:
            identifier = value
            if not identifier:
                continue
        occupied.add(identifier)
        anchors.append(
            Anchor(
                _source_location(source_path, offset, line_starts),
                kind,
                identifier,
            )
        )
    return tuple(anchors)


def _atx_heading(line: str) -> str | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3:
        return None
    index = indent
    count = _run_length(line, index, "#")
    if count < 1 or count > 6:
        return None
    index += count
    if index < len(line) and not line[index].isspace():
        return None
    body = line[index:].strip()
    closing = re.search(r"[ \t]+#+[ \t]*$", body)
    if closing is not None:
        body = body[: closing.start()].rstrip()
    return body


def _is_setext_underline(line: str) -> bool:
    stripped = line.strip(" \t")
    indent = len(line) - len(line.lstrip(" "))
    return (
        indent <= 3
        and bool(stripped)
        and stripped[0] in {"=", "-"}
        and set(stripped) == {stripped[0]}
    )


def _slug(value: str) -> str:
    output: list[str] = []
    pending_space = False
    for character in value.strip().lower():
        if character.isspace():
            pending_space = bool(output)
            continue
        category = unicodedata.category(character)
        if character in {"-", "_"} or not category.startswith(("P", "C", "Z")):
            if pending_space and output and output[-1] != "-":
                output.append("-")
            output.append(character)
            pending_space = False
    return "".join(output).strip("-")


class _ExplicitIdParser(HTMLParser):
    def __init__(self, line_starts: tuple[int, ...]) -> None:
        super().__init__(convert_charrefs=True)
        self._line_starts = line_starts
        self.candidates: list[tuple[int, AnchorKind, str]] = []

    def handle_starttag(
        self,
        _tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._record(attrs)

    def handle_startendtag(
        self,
        _tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._record(attrs)

    def _record(self, attrs: list[tuple[str, str | None]]) -> None:
        raw_tag = self.get_starttag_text()
        if raw_tag is None or inline_html_tag_end(raw_tag, 0) != len(raw_tag):
            return
        identifier = next(
            (value for name, value in attrs if name.casefold() == "id" and value),
            None,
        )
        if identifier is None:
            return
        line, column = self.getpos()
        offset = self._line_starts[line - 1] + column
        self.candidates.append((offset, AnchorKind.EXPLICIT, identifier))


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _run_length(text: str, index: int, character: str) -> int:
    end = index
    while end < len(text) and text[end] == character:
        end += 1
    return end - index


def _source_location(
    path: str,
    offset: int,
    line_starts: tuple[int, ...],
) -> SourceLocation:
    line_index = bisect_right(line_starts, offset) - 1
    return SourceLocation(path, line_index + 1, offset - line_starts[line_index] + 1)


def _mask_ranges(text: str, ranges: tuple[tuple[int, int], ...]) -> str:
    visible = list(text)
    for start, end in ranges:
        _blank(visible, start, end)
    return "".join(visible)


def _mask_escaped_html_openers(text: str) -> str:
    visible = list(text)
    for index, character in enumerate(text):
        if character == "<" and _is_escaped(text, index):
            visible[index] = " "
    return "".join(visible)


def _blank(characters: list[str], start: int, end: int) -> None:
    for index in range(start, min(end, len(characters))):
        if characters[index] not in "\r\n":
            characters[index] = " "
