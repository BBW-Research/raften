"""Repository path and pattern syntax owned by the matcher boundary."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_GLOB_CHARACTERS = frozenset("*?[]")


class PathFlavor(StrEnum):
    POSIX = "posix"
    WINDOWS = "windows"


class PatternSyntaxError(ValueError):
    """Raised when a repository pattern does not use the v1 glob language."""


@dataclass(frozen=True, slots=True)
class _LiteralToken:
    value: str


@dataclass(frozen=True, slots=True)
class _StarToken:
    pass


@dataclass(frozen=True, slots=True)
class _QuestionToken:
    pass


@dataclass(frozen=True, slots=True)
class _ClassToken:
    negated: bool
    ranges: tuple[tuple[str, str], ...]


PatternToken: TypeAlias = _LiteralToken | _StarToken | _QuestionToken | _ClassToken


@dataclass(frozen=True, slots=True)
class PatternComponent:
    recursive: bool
    tokens: tuple[PatternToken, ...]


@dataclass(frozen=True, slots=True)
class CompiledPattern:
    source: str
    components: tuple[PatternComponent, ...]


def path_validation_error(value: str) -> str | None:
    common = _common_path_error(value)
    if common is not None:
        return common
    if any(character in value for character in _GLOB_CHARACTERS):
        return "exact paths may not contain glob metacharacters"
    return None


def candidate_path_validation_error(value: str) -> str | None:
    """Validate an internal Git path without treating filename data as syntax."""

    if not value:
        return "path must not be empty"
    if value.startswith("/") or _has_drive_qualified_component(value):
        return "path must be repository-relative"
    if "\x00" in value:
        return "path must not contain NUL"
    if value.endswith("/") or "//" in value:
        return "path contains an empty component"
    if any(component in {".", ".."} for component in value.split("/")):
        return "path contains a traversal or non-canonical component"
    return None


def normalize_platform_path(
    value: str,
    *,
    flavor: PathFlavor | None = None,
) -> str:
    """Convert one native relative path to the canonical internal spelling."""

    selected_flavor = flavor
    if selected_flavor is None:
        selected_flavor = PathFlavor.WINDOWS if os.name == "nt" else PathFlavor.POSIX
    normalized = value.replace("\\", "/") if selected_flavor is PathFlavor.WINDOWS else value
    error = candidate_path_validation_error(normalized)
    if error is not None:
        raise ValueError(error)
    return normalized


def pattern_validation_error(value: str) -> str | None:
    common = _common_path_error(value)
    if common is not None:
        return common
    for component in value.split("/"):
        class_error = _character_class_error(component)
        if class_error is not None:
            return class_error
        if _contains_embedded_double_star(component):
            return "** must occupy an entire path component"
    return None


def compile_pattern(pattern: str) -> CompiledPattern:
    """Compile a validated v1 repository glob into immutable matcher tokens."""

    error = pattern_validation_error(pattern)
    if error is not None:
        raise PatternSyntaxError(error)
    return CompiledPattern(
        source=pattern,
        components=tuple(_compile_component(item) for item in pattern.split("/")),
    )


def match_path(pattern: CompiledPattern | str, path: str) -> bool:
    """Return whether a pattern matches one complete canonical repository path."""

    error = candidate_path_validation_error(path)
    if error is not None:
        raise ValueError(error)
    compiled = compile_pattern(pattern) if isinstance(pattern, str) else pattern
    return _match_compiled(compiled, path.split("/"))


def matches_any(patterns: tuple[CompiledPattern, ...], path: str) -> bool:
    """Return whether any precompiled pattern matches a repository path."""

    error = candidate_path_validation_error(path)
    if error is not None:
        raise ValueError(error)
    components = path.split("/")
    return any(_match_compiled(pattern, components) for pattern in patterns)


def pattern_has_wildcards(pattern: str) -> bool:
    return any(character in pattern for character in "*?[")


def pattern_specificity(pattern: str) -> tuple[int, int, int, int, int]:
    components = pattern.split("/")
    literal_components = sum(not pattern_has_wildcards(item) for item in components)
    literal_characters = sum(_literal_character_count(item) for item in components)
    double_stars = sum(item == "**" for item in components)
    other_wildcards = sum(_wildcard_count(item) for item in components if item != "**")
    return (
        literal_components,
        literal_characters,
        len(components),
        -double_stars,
        -other_wildcards,
    )


def patterns_provably_disjoint(left: str, right: str) -> bool:
    left_components = left.split("/")
    right_components = right.split("/")
    if "**" not in left_components and "**" not in right_components:
        if len(left_components) != len(right_components):
            return True
        return any(
            _literal_components_differ(left_component, right_component)
            for left_component, right_component in zip(left_components, right_components)
        )

    for left_component, right_component in zip(left_components, right_components):
        if left_component == "**" or right_component == "**":
            break
        if _literal_components_differ(left_component, right_component):
            return True
    for left_component, right_component in zip(
        reversed(left_components),
        reversed(right_components),
    ):
        if left_component == "**" or right_component == "**":
            break
        if _literal_components_differ(left_component, right_component):
            return True
    return False


def narrow_pattern_error(pattern: str) -> str | None:
    if not pattern_has_wildcards(pattern):
        return "a pattern selector must contain a wildcard; use an exact path instead"
    components = pattern.split("/")
    first_wildcard = next(
        (index for index, item in enumerate(components) if pattern_has_wildcards(item)),
        None,
    )
    if first_wildcard is None or first_wildcard == 0:
        return "a narrow pattern needs a fixed top-level directory prefix"
    if components[-1] == "**" or _literal_character_count(components[-1]) == 0:
        return "a narrow pattern needs a literal filename portion"
    return None


def _compile_component(component: str) -> PatternComponent:
    if component == "**":
        return PatternComponent(recursive=True, tokens=())
    tokens: list[PatternToken] = []
    index = 0
    while index < len(component):
        character = component[index]
        if character == "*":
            tokens.append(_StarToken())
            index += 1
        elif character == "?":
            tokens.append(_QuestionToken())
            index += 1
        elif character == "[":
            closing = component.index("]", index + 1)
            content = component[index + 1 : closing]
            negated = content.startswith("!")
            if negated:
                content = content[1:]
            tokens.append(_ClassToken(negated, _compile_class_ranges(content)))
            index = closing + 1
        else:
            tokens.append(_LiteralToken(character))
            index += 1
    return PatternComponent(recursive=False, tokens=tuple(tokens))


def _compile_class_ranges(content: str) -> tuple[tuple[str, str], ...]:
    ranges: list[tuple[str, str]] = []
    index = 0
    while index < len(content):
        if index + 2 < len(content) and content[index + 1] == "-":
            ranges.append((content[index], content[index + 2]))
            index += 3
        else:
            ranges.append((content[index], content[index]))
            index += 1
    return tuple(ranges)


def _match_compiled(pattern: CompiledPattern, path: list[str]) -> bool:
    path_count = len(path)
    following = [False] * (path_count + 1)
    following[path_count] = True
    for component in reversed(pattern.components):
        current = [False] * (path_count + 1)
        if component.recursive:
            current[path_count] = following[path_count]
            for path_index in range(path_count - 1, -1, -1):
                current[path_index] = following[path_index] or current[path_index + 1]
        else:
            for path_index in range(path_count - 1, -1, -1):
                current[path_index] = (
                    _match_component(component.tokens, path[path_index])
                    and following[path_index + 1]
                )
        following = current
    return following[0]


def _match_component(tokens: tuple[PatternToken, ...], value: str) -> bool:
    value_count = len(value)
    following = [False] * (value_count + 1)
    following[value_count] = True
    for token in reversed(tokens):
        current = [False] * (value_count + 1)
        if isinstance(token, _StarToken):
            current[value_count] = following[value_count]
            for value_index in range(value_count - 1, -1, -1):
                current[value_index] = following[value_index] or current[value_index + 1]
        else:
            for value_index, character in enumerate(value):
                current[value_index] = (
                    _token_matches_character(token, character)
                    and following[value_index + 1]
                )
        following = current
    return following[0]


def _token_matches_character(token: PatternToken, character: str) -> bool:
    if isinstance(token, _LiteralToken):
        return token.value == character
    if isinstance(token, _QuestionToken):
        return True
    if isinstance(token, _ClassToken):
        contained = any(start <= character <= end for start, end in token.ranges)
        return not contained if token.negated else contained
    raise AssertionError("star tokens are handled before character matching")


def _common_path_error(value: str) -> str | None:
    if not value:
        return "path must not be empty"
    if value.startswith("/") or _has_drive_qualified_component(value):
        return "path must be repository-relative"
    if "\\" in value:
        return "path must use POSIX separators"
    if any(
        ord(character) < 32 or 0x7F <= ord(character) <= 0x9F
        for character in value
    ):
        return "path must not contain control characters"
    if value.endswith("/") or "//" in value:
        return "path contains an empty component"
    components = value.split("/")
    if any(component in {".", ".."} for component in components):
        return "path contains a traversal or non-canonical component"
    return None


def _has_drive_qualified_component(value: str) -> bool:
    return any(_WINDOWS_DRIVE.match(component) for component in value.split("/"))


def _character_class_error(component: str) -> str | None:
    index = 0
    while index < len(component):
        character = component[index]
        if character == "]":
            return "pattern contains an unmatched ]"
        if character != "[":
            index += 1
            continue
        closing = component.find("]", index + 1)
        if closing < 0:
            return "pattern contains an unclosed character class"
        content = component[index + 1 : closing]
        if content.startswith("!"):
            content = content[1:]
        if not content or "[" in content:
            return "pattern contains an empty or nested character class"
        range_error = _character_class_range_error(content)
        if range_error is not None:
            return range_error
        index = closing + 1
    return None


def _contains_embedded_double_star(component: str) -> bool:
    index = 0
    while index < len(component):
        if component[index] == "[":
            closing = component.find("]", index + 1)
            index = len(component) if closing < 0 else closing + 1
        elif component.startswith("**", index):
            return component != "**"
        else:
            index += 1
    return False


def _literal_components_differ(left: str, right: str) -> bool:
    return (
        not pattern_has_wildcards(left)
        and not pattern_has_wildcards(right)
        and left != right
    )


def _character_class_range_error(content: str) -> str | None:
    index = 0
    while index < len(content):
        character = content[index]
        if index + 2 < len(content) and content[index + 1] == "-":
            end = content[index + 2]
            if character == "-" or end == "-":
                return "pattern contains an invalid character-class range"
            if ord(character) > ord(end):
                return "pattern contains a descending character-class range"
            index += 3
            continue
        if character == "-" and index not in {0, len(content) - 1}:
            return "pattern contains an invalid character-class range"
        index += 1
    return None


def _literal_character_count(component: str) -> int:
    count = 0
    index = 0
    while index < len(component):
        if component[index] in "*?":
            index += 1
        elif component[index] == "[":
            closing = component.find("]", index + 1)
            index = len(component) if closing < 0 else closing + 1
        else:
            count += 1
            index += 1
    return count


def _wildcard_count(component: str) -> int:
    count = 0
    index = 0
    while index < len(component):
        if component[index] in "*?":
            count += 1
            index += 1
        elif component[index] == "[":
            count += 1
            closing = component.find("]", index + 1)
            index = len(component) if closing < 0 else closing + 1
        else:
            index += 1
    return count
