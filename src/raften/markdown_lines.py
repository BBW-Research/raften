"""Physical-line primitives shared by Markdown extraction modules."""

from __future__ import annotations

from collections.abc import Iterator


def line_starts(text: str) -> tuple[int, ...]:
    """Return offsets after LF, CRLF, and CR line endings."""

    starts = [0]
    index = 0
    while index < len(text):
        if text[index] == "\r":
            index += 2 if index + 1 < len(text) and text[index + 1] == "\n" else 1
            starts.append(index)
        elif text[index] == "\n":
            index += 1
            starts.append(index)
        else:
            index += 1
    return tuple(starts)


def is_line_start(text: str, index: int) -> bool:
    """Return whether index begins a physical Markdown line."""

    if index == 0:
        return True
    if text[index - 1] == "\n":
        return True
    return text[index - 1] == "\r" and text[index] != "\n"


def line_bounds(text: str, start: int) -> tuple[int, int]:
    """Return content end and terminator end for the line at start."""

    index = start
    while index < len(text) and text[index] not in "\r\n":
        index += 1
    content_end = index
    if index < len(text):
        if text[index] == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
            index += 2
        else:
            index += 1
    return content_end, index


def physical_lines(text: str) -> Iterator[tuple[int, str, int]]:
    """Yield start offset, content, and end offset for each physical line."""

    start = 0
    while start < len(text):
        content_end, end = line_bounds(text, start)
        yield start, text[start:content_end], end
        start = end
