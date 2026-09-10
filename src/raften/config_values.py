"""Typed scalar, selector, list, and limit parsing for v1 policies."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar

from raften.config_validation import Validator, child_path
from raften.diagnostics import (
    CFG_DUPLICATE_SELECTOR,
    CFG_INCONSISTENT,
    CFG_LIMIT,
    CFG_PATH,
    CFG_PATTERN,
    CFG_VALUE,
)
from raften.matcher import (
    narrow_pattern_error,
    path_validation_error,
    pattern_has_wildcards,
    pattern_validation_error,
)
from raften.model import ExactSelector, PatternSelector, Selector


EnumValue = TypeVar("EnumValue", bound=StrEnum)


def parse_selector(
    validator: Validator,
    table: dict[str, Any],
    parent: str,
    *,
    narrow: bool = False,
    narrow_code: str = CFG_PATTERN,
) -> Selector | None:
    has_path = "path" in table
    has_pattern = "pattern" in table
    if has_path == has_pattern:
        validator.add(
            CFG_INCONSISTENT,
            parent,
            "exactly one of path or pattern must be declared",
        )
        return None
    if has_path:
        path = parse_path_value(validator, table, "path", parent, required=False)
        return None if path is None else ExactSelector(path)
    pattern = parse_pattern_value(validator, table, "pattern", parent, required=False)
    if pattern is None:
        return None
    if not pattern_has_wildcards(pattern):
        validator.add(
            CFG_PATTERN,
            f"{parent}.pattern",
            "a pattern selector must contain a wildcard; use path instead",
        )
        return None
    if narrow:
        error = narrow_pattern_error(pattern)
        if error is not None:
            validator.add(narrow_code, f"{parent}.pattern", error)
            return None
    return PatternSelector(pattern)


def parse_path_value(
    validator: Validator,
    table: dict[str, Any],
    key: str,
    parent: str,
    *,
    required: bool,
) -> str | None:
    value = validator.string(table, key, parent=parent, required=required)
    if value is None:
        return None
    error = path_validation_error(value)
    if error is not None:
        validator.add(CFG_PATH, child_path(parent, key), error, details=(("value", value),))
        return None
    return value


def parse_pattern_value(
    validator: Validator,
    table: dict[str, Any],
    key: str,
    parent: str,
    *,
    required: bool,
) -> str | None:
    value = validator.string(table, key, parent=parent, required=required)
    if value is None:
        return None
    error = pattern_validation_error(value)
    if error is not None:
        validator.add(CFG_PATTERN, child_path(parent, key), error, details=(("value", value),))
        return None
    return value


def parse_path_list(
    validator: Validator,
    table: dict[str, Any],
    key: str,
    *,
    parent: str,
    required: bool,
    nonempty: bool,
) -> tuple[str, ...] | None:
    return _parse_string_list(
        validator,
        table,
        key,
        parent=parent,
        required=required,
        nonempty=nonempty,
        pattern=False,
        narrow=False,
    )


def parse_pattern_list(
    validator: Validator,
    table: dict[str, Any],
    key: str,
    *,
    parent: str,
    required: bool,
    nonempty: bool,
    narrow: bool = False,
) -> tuple[str, ...] | None:
    return _parse_string_list(
        validator,
        table,
        key,
        parent=parent,
        required=required,
        nonempty=nonempty,
        pattern=True,
        narrow=narrow,
    )


def parse_limits(
    validator: Validator,
    table: dict[str, Any],
    parent: str,
    *,
    required: bool,
) -> tuple[int | None, int | None]:
    warn_bytes = validator.integer(table, "warn_bytes", parent=parent, required=required)
    hard_bytes = validator.integer(table, "hard_bytes", parent=parent, required=required)
    for key, value in (("warn_bytes", warn_bytes), ("hard_bytes", hard_bytes)):
        if value is not None and value <= 0:
            validator.add(
                CFG_LIMIT,
                f"{parent}.{key}",
                "byte limits must be positive integers",
                details=(("value", value),),
            )
    if warn_bytes is not None and hard_bytes is not None and warn_bytes >= hard_bytes:
        validator.add(
            CFG_LIMIT,
            f"{parent}.hard_bytes",
            "hard_bytes must be greater than warn_bytes",
            details=(("warn_bytes", warn_bytes), ("hard_bytes", hard_bytes)),
        )
    return warn_bytes, hard_bytes


def parse_enum(
    validator: Validator,
    table: dict[str, Any],
    key: str,
    parent: str,
    enum_type: type[EnumValue],
    *,
    required: bool,
) -> EnumValue | None:
    value = validator.string(table, key, parent=parent, required=required)
    if value is None:
        return None
    try:
        return enum_type(value)
    except ValueError:
        allowed = tuple(item.value for item in enum_type)
        validator.add(
            CFG_VALUE,
            child_path(parent, key),
            f"unsupported {key} value {value!r}",
            details=(("allowed", allowed), ("value", value)),
        )
        return None


def _parse_string_list(
    validator: Validator,
    table: dict[str, Any],
    key: str,
    *,
    parent: str,
    required: bool,
    nonempty: bool,
    pattern: bool,
    narrow: bool,
) -> tuple[str, ...] | None:
    values = validator.array(table, key, parent=parent, required=required)
    if values is None:
        return None
    field_path = child_path(parent, key)
    if nonempty and not values:
        validator.add(CFG_VALUE, field_path, f"{field_path} must not be empty")
    result: list[str] = []
    seen: dict[str, int] = {}
    for index, value in enumerate(values):
        item_path = f"{field_path}[{index}]"
        if type(value) is not str:
            validator.type_error(item_path, "string", value)
            continue
        error = pattern_validation_error(value) if pattern else path_validation_error(value)
        if error is not None:
            validator.add(
                CFG_PATTERN if pattern else CFG_PATH,
                item_path,
                error,
                details=(("value", value),),
            )
            continue
        if narrow:
            error = narrow_pattern_error(value)
            if error is not None:
                validator.add(CFG_PATTERN, item_path, error, details=(("value", value),))
                continue
        previous = seen.get(value)
        if previous is not None:
            validator.add(
                CFG_DUPLICATE_SELECTOR,
                item_path,
                f"duplicate value {value!r}",
                details=(("first_index", previous),),
            )
            continue
        seen[value] = index
        result.append(value)
    return tuple(result)
