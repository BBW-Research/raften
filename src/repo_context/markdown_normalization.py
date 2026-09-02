"""Safe normalization of Markdown references and local destinations."""

from __future__ import annotations

import html
import re
from urllib.parse import unquote_to_bytes

from repo_context.matcher import candidate_path_validation_error
from repo_context.model import DestinationIssueKind, Link, LinkKind, SourceLocation


_ASCII_PUNCTUATION = frozenset(
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
)
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_DRIVE_QUALIFIED_COMPONENT = re.compile(r"^[A-Za-z]:")


def _make_link(
    source_path: str,
    raw_destination: str,
    kind: LinkKind,
    source: SourceLocation,
    known_directories: frozenset[str],
) -> Link | None:
    resolved = _resolve_destination(source_path, raw_destination, known_directories)
    if resolved is None:
        return None
    target, fragment, issue, directory_hint = resolved
    return Link(
        source,
        kind,
        raw_destination,
        target,
        fragment,
        issue,
        directory_hint,
    )


def _resolve_destination(
    source_path: str,
    raw_destination: str,
    known_directories: frozenset[str],
) -> tuple[str | None, str | None, DestinationIssueKind | None, bool] | None:
    path_and_query, _separator, raw_fragment = raw_destination.partition("#")
    raw_path = path_and_query.partition("?")[0]
    source_path_probe = _decode_destination_markup(raw_path)
    source_drive = _DRIVE_QUALIFIED_COMPONENT.match(source_path_probe)
    if source_drive is None and (
        _SCHEME.match(source_path_probe) or source_path_probe.startswith("//")
    ):
        return None
    percent_decoded_path, path_issue = _strict_percent_decode(raw_path)
    percent_decoded_fragment, fragment_issue = _strict_percent_decode(raw_fragment)
    issue = path_issue or fragment_issue
    if issue is not None:
        return None, None, issue, False
    decoded_path = _decode_destination_markup(percent_decoded_path)
    decoded_fragment = _decode_destination_markup(percent_decoded_fragment)
    if _DRIVE_QUALIFIED_COMPONENT.match(decoded_path):
        return None, None, DestinationIssueKind.UNSAFE_PATH, False
    if _SCHEME.match(decoded_path) or decoded_path.startswith("//"):
        return None
    if any(
        _DRIVE_QUALIFIED_COMPONENT.match(component)
        for component in decoded_path.split("/")[1:]
    ):
        return None, None, DestinationIssueKind.UNSAFE_PATH, False
    if decoded_path.startswith("/"):
        return None, decoded_fragment or None, DestinationIssueKind.ABSOLUTE, False
    if _contains_unsafe_character(decoded_path) or _contains_unsafe_character(decoded_fragment):
        return None, None, DestinationIssueKind.UNSAFE_PATH, False
    if decoded_path == "":
        return source_path, decoded_fragment or None, None, False

    final_component = decoded_path.rstrip("/").rpartition("/")[2]
    directory_hint = decoded_path.endswith("/") or final_component in {".", ".."}
    components = source_path.split("/")[:-1]
    raw_components = decoded_path.split("/")
    for component_index, component in enumerate(raw_components):
        if component == "" and component_index == len(raw_components) - 1:
            continue
        if component in {"", "."}:
            if component == "":
                return None, None, DestinationIssueKind.UNSAFE_PATH, directory_hint
            continue
        if component == "..":
            if not components:
                return None, None, DestinationIssueKind.ESCAPES_REPOSITORY, directory_hint
            components.pop()
            continue
        components.append(component)
    target = "/".join(components)
    if target and candidate_path_validation_error(target) is not None:
        return None, None, DestinationIssueKind.UNSAFE_PATH, directory_hint
    if target in known_directories:
        directory_hint = True
    if directory_hint:
        target = f"{target}/index.md" if target else "index.md"
    if not target:
        return None, None, DestinationIssueKind.UNSAFE_PATH, directory_hint
    return target, decoded_fragment or None, None, directory_hint


def _strict_percent_decode(
    value: str,
) -> tuple[str, DestinationIssueKind | None]:
    index = 0
    while index < len(value):
        if value[index] != "%":
            index += 1
            continue
        if (
            index + 2 >= len(value)
            or value[index + 1] not in _HEX_DIGITS
            or value[index + 2] not in _HEX_DIGITS
        ):
            return "", DestinationIssueKind.INVALID_PERCENT_ENCODING
        index += 3
    try:
        return unquote_to_bytes(value).decode("utf-8", errors="strict"), None
    except UnicodeDecodeError:
        return "", DestinationIssueKind.INVALID_UTF8


def _contains_unsafe_character(value: str) -> bool:
    return "\\" in value or any(
        character == "\x00"
        or ord(character) < 32
        or 0x7F <= ord(character) <= 0x9F
        for character in value
    )


def _normalize_reference_label(value: str) -> str:
    decoded = html.unescape(_decode_markdown_escapes(value))
    return " ".join(decoded.split()).casefold()


def _decode_destination_markup(value: str) -> str:
    return html.unescape(_decode_markdown_escapes(value))


def _decode_markdown_escapes(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        if (
            value[index] == "\\"
            and index + 1 < len(value)
            and value[index + 1] in _ASCII_PUNCTUATION
        ):
            output.append(value[index + 1])
            index += 2
        else:
            output.append(value[index])
            index += 1
    return "".join(output)
