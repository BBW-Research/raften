"""Shared value and diagnostic helpers for policy ratchet domains."""

from __future__ import annotations

from datetime import date
from enum import Enum

from raften.diagnostics import policy_diagnostic
from raften.model import (
    Diagnostic,
    ExactSelector,
    JsonValue,
    Selector,
    Severity,
)


def compare_limits(
    current_warn: int | None,
    current_hard: int | None,
    base_warn: int | None,
    base_hard: int | None,
    code: str,
    policy_path: str,
    parent: str,
    findings: list[Diagnostic],
    *,
    reason_prefix: str = "",
) -> None:
    for name, current, base in (
        ("warn", current_warn, base_warn),
        ("hard", current_hard, base_hard),
    ):
        if current is not None and base is not None and current > base:
            findings.append(
                ratchet_finding(
                    code,
                    policy_path,
                    f"{parent}.{name}_bytes",
                    f"{reason_prefix}{'warning' if name == 'warn' else 'hard'}_limit_increased",
                    base=base,
                    current=current,
                )
            )


def selector_key(selector: Selector) -> tuple[str, str]:
    if isinstance(selector, ExactSelector):
        return "path", selector.path
    return "pattern", selector.pattern


def ratchet_finding(
    code: str,
    policy_path: str,
    field_path: str,
    reason: str,
    *,
    base: object,
    current: object,
    extra: tuple[tuple[str, JsonValue], ...] = (),
) -> Diagnostic:
    details: tuple[tuple[str, JsonValue], ...] = (
        ("reason", reason),
        ("base_value", _json_value(base)),
        ("current_value", _json_value(current)),
        *extra,
    )
    return policy_diagnostic(
        code,
        Severity.ERROR,
        "repository policy weakens a configured base guarantee",
        path=policy_path,
        field_path=field_path,
        details=details,
        hint="restore or tighten the base guarantee",
    )


def _json_value(value: object) -> JsonValue:
    if isinstance(value, Enum):
        return str(value.value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, tuple):
        return tuple(_json_value(item) for item in value)
    return repr(value)
