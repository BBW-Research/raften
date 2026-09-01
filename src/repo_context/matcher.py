"""Repository path and pattern syntax owned by the matcher boundary."""

from __future__ import annotations

import re


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:")
_GLOB_CHARACTERS = frozenset("*?[]")


def path_validation_error(value: str) -> str | None:
    common = _common_path_error(value)
    if common is not None:
        return common
    if any(character in value for character in _GLOB_CHARACTERS):
        return "exact paths may not contain glob metacharacters"
    return None


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


def _common_path_error(value: str) -> str | None:
    if not value:
        return "path must not be empty"
    if value.startswith("/") or _WINDOWS_DRIVE.match(value):
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
