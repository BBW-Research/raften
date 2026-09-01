"""Stable diagnostic identities and deterministic ordering helpers."""

from __future__ import annotations

from repo_context.model import Diagnostic, JsonValue, Severity, SourceLocation


CFG_PARSE = "CFG001"
CFG_UNKNOWN_KEY = "CFG002"
CFG_MISSING_KEY = "CFG003"
CFG_TYPE = "CFG004"
CFG_VALUE = "CFG005"
CFG_PATH = "CFG006"
CFG_PATTERN = "CFG007"
CFG_DUPLICATE_NAME = "CFG008"
CFG_DUPLICATE_SELECTOR = "CFG009"
CFG_CATCH_ALL = "CFG010"
CFG_AMBIGUOUS_OVERRIDE = "CFG011"
CFG_LIMIT = "CFG012"
CFG_INCONSISTENT = "CFG013"
EXC_BROAD_SELECTOR = "EXC001"
EXC_EXPIRED = "EXC002"


def config_diagnostic(
    code: str,
    source_path: str,
    field_path: str,
    message: str,
    *,
    line: int | None = None,
    column: int | None = None,
    details: tuple[tuple[str, JsonValue], ...] = (),
    hint: str | None = None,
) -> Diagnostic:
    return Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        location=SourceLocation(source_path, line, column),
        field_path=field_path,
        details=details,
        hint=hint,
    )


def config_diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[object, ...]:
    location = diagnostic.location
    return (
        "" if location is None else location.path,
        0 if location is None or location.line is None else location.line,
        0 if location is None or location.column is None else location.column,
        diagnostic.code,
        diagnostic.field_path or "$",
        repr(diagnostic.details),
    )


def diagnostic_sort_key(diagnostic: Diagnostic) -> tuple[object, ...]:
    location = diagnostic.location
    return (
        "" if location is None else location.path,
        0 if location is None or location.line is None else location.line,
        0 if location is None or location.column is None else location.column,
        diagnostic.code,
        diagnostic.field_path or "",
        repr(diagnostic.details),
    )
