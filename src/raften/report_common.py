"""Shared deterministic projections for every output renderer."""

from __future__ import annotations

from collections.abc import Sequence
from enum import Enum

from raften.matcher import compile_pattern, match_path
from raften.model import Diagnostic, ExactSelector, JsonValue, Selector, Severity
from raften.run_model import (
    CommandFailure,
    InitResult,
    PathExplanation,
    RepositoryRun,
    RunStatus,
)


ReportOutcome = RepositoryRun | PathExplanation | InitResult | CommandFailure


def outcome_status(outcome: ReportOutcome) -> RunStatus:
    if isinstance(outcome, CommandFailure):
        return outcome.status
    if isinstance(outcome, PathExplanation):
        return outcome.run.status
    if isinstance(outcome, RepositoryRun):
        return outcome.status
    return RunStatus.COMPLETE


def outcome_diagnostics(
    command: str,
    outcome: ReportOutcome,
) -> tuple[Diagnostic, ...]:
    if isinstance(outcome, CommandFailure):
        return outcome.diagnostics
    if isinstance(outcome, RepositoryRun):
        return outcome.diagnostics
    if isinstance(outcome, InitResult):
        return ()
    return tuple(
        item
        for item in outcome.run.diagnostics
        if _diagnostic_applies_to_explanation(item, outcome)
    )


def _diagnostic_applies_to_explanation(
    diagnostic: Diagnostic,
    outcome: PathExplanation,
) -> bool:
    selected = outcome.file.path
    if diagnostic.location is not None:
        return diagnostic.location.path == selected
    details = dict(diagnostic.details)
    exception_index = details.get("exception_index")
    if isinstance(exception_index, int) and not isinstance(exception_index, bool):
        records = outcome.run.policy.exceptions.records
        if 0 <= exception_index < len(records):
            selector = records[exception_index].selector
            if isinstance(selector, ExactSelector):
                return selector.path == selected
            return match_path(compile_pattern(selector.pattern), selected)
    context_index = details.get("context_index")
    if isinstance(context_index, int) and not isinstance(context_index, bool):
        contexts = outcome.run.policy.context_sets
        if 0 <= context_index < len(contexts):
            return contexts[context_index].name in outcome.file.context_sets
    return True


def summary_value(diagnostics: Sequence[Diagnostic]) -> dict[str, int]:
    return {
        "errors": sum(item.severity is Severity.ERROR for item in diagnostics),
        "warnings": sum(item.severity is Severity.WARNING for item in diagnostics),
        "notes": sum(item.severity is Severity.NOTE for item in diagnostics),
    }


def diagnostic_value(diagnostic: Diagnostic) -> dict[str, object]:
    location = diagnostic.location
    return {
        "code": diagnostic.code,
        "severity": diagnostic.severity.value,
        "message": diagnostic.message,
        "location": None
        if location is None
        else {
            "path": location.path,
            "line": location.line,
            "column": location.column,
        },
        "field_path": diagnostic.field_path,
        "details": {key: json_value(value) for key, value in diagnostic.details},
        "hint": diagnostic.hint,
    }


def json_value(value: JsonValue | object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, str):
        return value.encode("utf-8", errors="backslashreplace").decode("utf-8")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {item[0]: json_value(item[1]) for item in value}
        return [json_value(item) for item in value]
    return repr(value)


def selector_value(selector: Selector) -> dict[str, str]:
    if isinstance(selector, ExactSelector):
        return {"type": "path", "value": selector.path}
    return {"type": "pattern", "value": selector.pattern}
