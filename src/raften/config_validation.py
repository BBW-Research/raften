"""Low-level strict validation helpers for v1 TOML configuration."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

from raften.diagnostics import (
    CFG_MISSING_KEY,
    CFG_TYPE,
    CFG_UNKNOWN_KEY,
    CFG_VALUE,
    config_diagnostic,
)
from raften.model import Diagnostic, JsonValue


MISSING = object()


class Validator:
    def __init__(self, source_path: str) -> None:
        self.source_path = source_path
        self.diagnostics: list[Diagnostic] = []

    def add(
        self,
        code: str,
        field_path: str,
        message: str,
        *,
        details: tuple[tuple[str, JsonValue], ...] = (),
        hint: str | None = None,
    ) -> None:
        self.diagnostics.append(
            config_diagnostic(
                code,
                self.source_path,
                field_path,
                message,
                details=details,
                hint=hint,
            )
        )

    def keys(
        self,
        table: dict[str, Any],
        *,
        parent: str,
        allowed: frozenset[str],
        required: frozenset[str],
    ) -> None:
        for key in sorted(set(table) - allowed):
            field_path = child_path(parent, key)
            self.add(
                CFG_UNKNOWN_KEY,
                field_path,
                f"unknown configuration key {field_path}",
                details=(("key", key),),
            )
        for key in sorted(required - set(table)):
            field_path = child_path(parent, key)
            self.add(
                CFG_MISSING_KEY,
                field_path,
                f"missing required configuration key {field_path}",
                details=(("key", key),),
            )

    def table(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str = "$",
        required: bool = True,
    ) -> dict[str, Any] | None:
        field_path = child_path(parent, key)
        value = table.get(key, MISSING)
        if value is MISSING:
            if required:
                self.add(
                    CFG_MISSING_KEY,
                    field_path,
                    f"missing required table {field_path}",
                )
            return None
        if type(value) is not dict:
            self.type_error(field_path, "table", value)
            return None
        return value

    def array_of_tables(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str = "$",
        required: bool = False,
    ) -> list[tuple[int, dict[str, Any]]]:
        field_path = child_path(parent, key)
        value = table.get(key, MISSING)
        if value is MISSING:
            if required:
                self.add(
                    CFG_MISSING_KEY,
                    field_path,
                    f"missing required array of tables {field_path}",
                )
            return []
        if type(value) is not list:
            self.type_error(field_path, "array of tables", value)
            return []
        result: list[tuple[int, dict[str, Any]]] = []
        for index, item in enumerate(value):
            item_path = f"{field_path}[{index}]"
            if type(item) is not dict:
                self.type_error(item_path, "table", item)
            else:
                result.append((index, item))
        return result

    def string(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str,
        required: bool = True,
        human: bool = False,
    ) -> str | None:
        field_path = child_path(parent, key)
        value = self._value(table, key, field_path, required)
        if value is MISSING:
            return None
        if type(value) is not str:
            self.type_error(field_path, "string", value)
            return None
        if human:
            if not value.strip():
                self.add(CFG_VALUE, field_path, f"{field_path} must not be blank")
                return None
            if any(
                ord(character) < 32 or 0x7F <= ord(character) <= 0x9F
                for character in value
            ):
                self.add(
                    CFG_VALUE,
                    field_path,
                    f"{field_path} must not contain control characters",
                )
                return None
        return value

    def boolean(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str,
        required: bool = True,
    ) -> bool | None:
        field_path = child_path(parent, key)
        value = self._value(table, key, field_path, required)
        if value is MISSING:
            return None
        if type(value) is not bool:
            self.type_error(field_path, "boolean", value)
            return None
        return value

    def integer(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str,
        required: bool = True,
    ) -> int | None:
        field_path = child_path(parent, key)
        value = self._value(table, key, field_path, required)
        if value is MISSING:
            return None
        if type(value) is not int:
            self.type_error(field_path, "integer", value)
            return None
        return value

    def local_date(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str,
        required: bool = True,
    ) -> date | None:
        field_path = child_path(parent, key)
        value = self._value(table, key, field_path, required)
        if value is MISSING:
            return None
        if type(value) is not date:
            self.type_error(field_path, "TOML local date", value)
            return None
        return value

    def array(
        self,
        table: dict[str, Any],
        key: str,
        *,
        parent: str,
        required: bool = True,
    ) -> list[Any] | None:
        field_path = child_path(parent, key)
        value = self._value(table, key, field_path, required)
        if value is MISSING:
            return None
        if type(value) is not list:
            self.type_error(field_path, "array", value)
            return None
        return value

    def type_error(self, field_path: str, expected: str, actual: object) -> None:
        self.add(
            CFG_TYPE,
            field_path,
            f"{field_path} must be a {expected}",
            details=(("expected", expected), ("actual", type(actual).__name__)),
        )

    def _value(
        self,
        table: dict[str, Any],
        key: str,
        field_path: str,
        required: bool,
    ) -> object:
        value = table.get(key, MISSING)
        if value is MISSING and required:
            self.add(
                CFG_MISSING_KEY,
                field_path,
                f"missing required configuration key {field_path}",
                details=(("key", key),),
            )
        return value


def child_path(parent: str, key: str) -> str:
    if key and all(
        character.isascii() and (character.isalnum() or character in "_-")
        for character in key
    ):
        return key if parent == "$" else f"{parent}.{key}"
    rendered = json.dumps(key, ensure_ascii=True)
    return f"{parent}[{rendered}]"
