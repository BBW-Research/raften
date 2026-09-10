"""Inline Markdown links, references, and local destination normalization."""

from __future__ import annotations

import html
from bisect import bisect_right
from dataclasses import dataclass

from raften.markdown_lines import physical_lines
from raften.markdown_normalization import (
    _ASCII_PUNCTUATION,
    _make_link,
    _normalize_reference_label,
)
from raften.model import Link, LinkKind, SourceLocation


_MAX_REFERENCE_LABEL_CHARACTERS = 999


@dataclass(frozen=True, slots=True)
class LinkExtraction:
    links: tuple[Link, ...]
    definition_ranges: tuple[tuple[int, int], ...]
    html_mask_ranges: tuple[tuple[int, int], ...]
    defined_reference_labels: frozenset[str]


def extract_links(
    source_path: str,
    text: str,
    known_directories: frozenset[str],
    line_starts: tuple[int, ...],
) -> LinkExtraction:
    """Extract local links and ranges hidden from block and HTML parsing."""

    definitions, definition_ranges = _reference_definitions(text)
    visible = _mask_ranges(text, definition_ranges)
    closing_brackets = _bracket_pairs(visible)
    links: list[Link] = []
    html_ranges: list[tuple[int, int]] = []
    skip_starts: dict[int, int] = {}
    active_navigation_end: int | None = None
    index = 0
    while index < len(visible):
        if active_navigation_end is not None and index >= active_navigation_end:
            active_navigation_end = None
        skip_end = skip_starts.get(index)
        if skip_end is not None and skip_end > index:
            index = skip_end
            continue
        if visible[index] != "[" or _is_escaped(visible, index):
            index += 1
            continue
        image = (
            index > 0
            and visible[index - 1] == "!"
            and not _is_escaped(visible, index - 1)
        )
        closing = closing_brackets.get(index)
        if closing is None:
            index += 1
            continue
        destination: str | None = None
        end = closing + 1
        suffix_start: int | None = None
        if end < len(visible) and visible[end] == "(":
            parsed = _parse_inline_destination(visible, end)
            if parsed is not None:
                suffix_start = end
                destination, end = parsed
        elif definitions and end < len(visible) and visible[end] == "[":
            reference_end = _find_reference_end(visible, end + 1)
            if reference_end is not None:
                reference_start = end + 1
                reference_stop = reference_end
                if reference_start == reference_stop:
                    reference_start = index + 1
                    reference_stop = closing
                destination = _reference_destination(
                    definitions,
                    visible,
                    reference_start,
                    reference_stop,
                )
                if destination is not None:
                    suffix_start = end
                    end = reference_end + 1
        elif definitions:
            destination = _reference_destination(
                definitions,
                visible,
                index + 1,
                closing,
            )
        if destination is None:
            index += 1
            continue
        if suffix_start is not None:
            html_ranges.append((suffix_start, end))
            skip_starts[suffix_start] = max(skip_starts.get(suffix_start, 0), end)
        kind = LinkKind.IMAGE if image else LinkKind.NAVIGATION
        if kind is LinkKind.IMAGE:
            html_ranges.append((index + 1, closing))
            if closing > index + 1:
                skip_starts[index + 1] = max(
                    skip_starts.get(index + 1, 0),
                    closing,
                )
        nested_navigation = (
            kind is LinkKind.NAVIGATION and active_navigation_end is not None
        )
        link = _make_link(
            source_path,
            destination,
            kind,
            _source_location(source_path, index, line_starts),
            known_directories,
        )
        if link is not None and not nested_navigation:
            links.append(link)
        if kind is LinkKind.NAVIGATION and not nested_navigation:
            active_navigation_end = closing
        index += 1
    return LinkExtraction(
        tuple(links),
        definition_ranges,
        tuple(sorted(set(html_ranges))),
        frozenset(definitions),
    )


def heading_display_text(
    value: str,
    *,
    defined_reference_labels: frozenset[str] = frozenset(),
    _depth: int = 0,
) -> str:
    """Project supported inline-to-display reduction for heading slugs."""

    if _depth >= 64:
        return value
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if (
            character == "\\"
            and index + 1 < len(value)
            and value[index + 1] in _ASCII_PUNCTUATION
        ):
            output.append(value[index + 1])
            index += 2
            continue
        if character == "`":
            run = _run_length(value, index, "`")
            closing = _find_equal_run(value, index + run, "`", run)
            if closing is not None:
                output.append(value[index + run : closing])
                index = closing + run
                continue
        if character in {"*", "_", "~"}:
            run = _run_length(value, index, character)
            intraword_underscore = (
                character == "_"
                and index > 0
                and index + run < len(value)
                and value[index - 1].isalnum()
                and value[index + run].isalnum()
            )
            closing = None if intraword_underscore else _find_equal_run(
                value,
                index + run,
                character,
                run,
            )
            if closing is not None:
                output.append(
                    heading_display_text(
                        value[index + run : closing],
                        defined_reference_labels=defined_reference_labels,
                        _depth=_depth + 1,
                    )
                )
                index = closing + run
                continue
        if character == "<":
            html_end = inline_html_span_end(value, index)
            if html_end is not None:
                index = html_end
                continue
        if character in {"[", "!"}:
            opening = (
                index + 1
                if character == "!"
                and index + 1 < len(value)
                and value[index + 1] == "["
                else index
            )
            if value[opening] == "[":
                closing = _find_closing_bracket(value, opening)
                if closing is not None:
                    output.append(
                        heading_display_text(
                            value[opening + 1 : closing],
                            defined_reference_labels=defined_reference_labels,
                            _depth=_depth + 1,
                        )
                    )
                    index = closing + 1
                    if index < len(value) and value[index] == "(":
                        parsed = _parse_inline_destination(value, index)
                        if parsed is not None:
                            index = parsed[1]
                    elif index < len(value) and value[index] == "[":
                        reference_end = _find_reference_end(value, index + 1)
                        if reference_end is not None:
                            reference = value[index + 1 : reference_end]
                            if not reference:
                                reference = value[opening + 1 : closing]
                            if (
                                len(reference) <= _MAX_REFERENCE_LABEL_CHARACTERS
                                and _normalize_reference_label(reference)
                                in defined_reference_labels
                            ):
                                index = reference_end + 1
                    continue
        output.append(character)
        index += 1
    reduced = "".join(output)
    return html.unescape(reduced) if _depth == 0 else reduced


def _reference_definitions(
    text: str,
) -> tuple[dict[str, str], tuple[tuple[int, int], ...]]:
    definitions: dict[str, str] = {}
    ranges: list[tuple[int, int]] = []
    for offset, content, end in physical_lines(text):
        parsed = _parse_reference_definition(content)
        if parsed is not None:
            label, destination = parsed
            definitions.setdefault(label, destination)
            ranges.append((offset, end))
    return definitions, tuple(ranges)


def _parse_reference_definition(line: str) -> tuple[str, str] | None:
    indent = len(line) - len(line.lstrip(" "))
    if indent > 3 or indent >= len(line) or line[indent] != "[":
        return None
    closing = _find_closing_bracket(line, indent)
    if closing is None or closing + 1 >= len(line) or line[closing + 1] != ":":
        return None
    if closing - indent - 1 > _MAX_REFERENCE_LABEL_CHARACTERS:
        return None
    label = _normalize_reference_label(line[indent + 1 : closing])
    if not label:
        return None
    destination = _parse_definition_destination(line[closing + 2 :])
    if destination is None:
        return None
    return label, destination


def _reference_destination(
    definitions: dict[str, str],
    text: str,
    start: int,
    end: int,
) -> str | None:
    if end - start > _MAX_REFERENCE_LABEL_CHARACTERS:
        return None
    return definitions.get(_normalize_reference_label(text[start:end]))


def _find_reference_end(text: str, start: int) -> int | None:
    stop = min(len(text), start + _MAX_REFERENCE_LABEL_CHARACTERS + 1)
    return _find_unescaped(text, "]", start, stop=stop)


def _parse_definition_destination(value: str) -> str | None:
    index = _skip_space(value, 0)
    if index >= len(value):
        return None
    if value[index] == "<":
        closing = _find_unescaped(value, ">", index + 1)
        if closing is None:
            return None
        destination = value[index + 1 : closing]
        index = closing + 1
    else:
        start = index
        depth = 0
        while index < len(value) and not value[index].isspace():
            character = value[index]
            if character == "\\" and index + 1 < len(value):
                index += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    return None
                depth -= 1
            index += 1
        if depth != 0 or index == start:
            return None
        destination = value[start:index]
    return destination if _valid_title_remainder(value[index:]) else None


def _valid_title_remainder(value: str) -> bool:
    stripped = value.strip(" \t")
    if not stripped:
        return True
    opening = stripped[0]
    closing = ")" if opening == "(" else opening
    if opening not in {"\"", "'", "("}:
        return False
    end = _find_unescaped(stripped, closing, 1)
    return end is not None and not stripped[end + 1 :].strip(" \t")


def _parse_inline_destination(text: str, opening: int) -> tuple[str, int] | None:
    index = _skip_space(text, opening + 1)
    if index >= len(text):
        return None
    if text[index] == ")":
        return "", index + 1
    if text[index] == "<":
        closing = _find_unescaped(text, ">", index + 1)
        if closing is None or any(
            ending in text[index + 1 : closing] for ending in "\r\n"
        ):
            return None
        destination = text[index + 1 : closing]
        index = closing + 1
    else:
        start = index
        depth = 0
        while index < len(text):
            character = text[index]
            if character == "\\" and index + 1 < len(text):
                index += 2
                continue
            if character == "(":
                depth += 1
            elif character == ")":
                if depth == 0:
                    return text[start:index], index + 1
                depth -= 1
            elif character.isspace() and depth == 0:
                break
            index += 1
        if index == start or depth != 0:
            return None
        destination = text[start:index]

    index = _skip_space(text, index)
    if index >= len(text):
        return None
    if text[index] == ")":
        return destination, index + 1
    title_end = _parse_title(text, index)
    if title_end is None:
        return None
    index = _skip_space(text, title_end)
    if index >= len(text) or text[index] != ")":
        return None
    return destination, index + 1


def _parse_title(text: str, start: int) -> int | None:
    opening = text[start]
    if opening not in {"\"", "'", "("}:
        return None
    closing = ")" if opening == "(" else opening
    end = _find_unescaped(text, closing, start + 1)
    return None if end is None else end + 1


def inline_html_tag_end(text: str, start: int) -> int | None:
    index = start + 1
    if index < len(text) and text[index] == "/":
        index += 1
    if index >= len(text) or not text[index].isascii() or not text[index].isalpha():
        return None
    while index < len(text) and (
        text[index].isascii() and (text[index].isalnum() or text[index] in "-:")
    ):
        index += 1
    while index < len(text):
        index = _skip_markdown_whitespace(text, index)
        if index >= len(text):
            return None
        if text[index] == ">":
            return index + 1
        if text[index] == "/":
            return index + 2 if text.startswith("/>", index) else None
        if not _is_html_attribute_name_start(text[index]):
            return None
        index += 1
        while index < len(text) and _is_html_attribute_name_character(text[index]):
            index += 1
        index = _skip_markdown_whitespace(text, index)
        if index >= len(text) or text[index] != "=":
            continue
        index = _skip_markdown_whitespace(text, index + 1)
        if index >= len(text):
            return None
        if text[index] in {"\"", "'"}:
            quote = text[index]
            closing = text.find(quote, index + 1)
            if closing < 0:
                return None
            index = closing + 1
            continue
        value_start = index
        while index < len(text) and text[index] not in " \t\r\n\"'=<>`":
            index += 1
        if index == value_start:
            return None
    return None


def inline_html_span_end(text: str, start: int) -> int | None:
    tag_end = inline_html_tag_end(text, start)
    if tag_end is not None:
        return tag_end
    if text.startswith("<!--", start):
        closing = text.find("-->", start + 4)
        return None if closing < 0 else closing + 3
    if text.startswith("<?", start):
        closing = text.find("?>", start + 2)
        return None if closing < 0 else closing + 2
    if text.startswith("<![CDATA[", start):
        closing = text.find("]]>", start + 9)
        return None if closing < 0 else closing + 3
    declaration = start + 2
    if (
        text.startswith("<!", start)
        and declaration < len(text)
        and text[declaration].isascii()
        and text[declaration].isalpha()
    ):
        closing = text.find(">", declaration + 1)
        return None if closing < 0 else closing + 1
    return None


def _is_html_attribute_name_start(character: str) -> bool:
    return character.isascii() and (character.isalpha() or character in "_:")


def _is_html_attribute_name_character(character: str) -> bool:
    return character.isascii() and (character.isalnum() or character in "_.:-")


def _skip_markdown_whitespace(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\r\n":
        index += 1
    return index


def _find_closing_bracket(text: str, opening: int) -> int | None:
    depth = 1
    index = opening + 1
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            index += 2
            continue
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _bracket_pairs(text: str) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}
    index = 0
    while index < len(text):
        if text[index] == "\\" and index + 1 < len(text):
            index += 2
            continue
        if text[index] == "[":
            stack.append(index)
        elif text[index] == "]" and stack:
            pairs[stack.pop()] = index
        index += 1
    return pairs


def _find_unescaped(
    text: str,
    character: str,
    start: int,
    *,
    stop: int | None = None,
) -> int | None:
    index = start
    limit = len(text) if stop is None else min(stop, len(text))
    while index < limit:
        found = text.find(character, index, limit)
        if found < 0:
            return None
        if not _is_escaped(text, found):
            return found
        index = found + 1
    return None


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


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t":
        index += 1
    return index


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
        for index in range(start, min(end, len(visible))):
            if visible[index] not in "\r\n":
                visible[index] = " "
    return "".join(visible)
