"""Structured failures shared across the repository boundary."""

from __future__ import annotations

from typing import Never

from raften.diagnostics import (
    GIT_MALFORMED_OUTPUT,
    diagnostic_sort_key,
    operational_diagnostic,
)
from raften.model import Diagnostic, JsonValue


class RepositoryAccessError(RuntimeError):
    """A deterministic repository-boundary failure with structured diagnostics."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = tuple(sorted(diagnostics, key=diagnostic_sort_key))
        super().__init__("; ".join(item.message for item in self.diagnostics))


def fail_repository(
    code: str,
    message: str,
    *,
    path: str | None = None,
    details: tuple[tuple[str, JsonValue], ...] = (),
) -> Never:
    raise RepositoryAccessError(
        (
            operational_diagnostic(
                code,
                message,
                path=path,
                details=details,
            ),
        )
    )


def malformed_git_output(
    operation: str,
    message: str,
    *,
    path: str | None = None,
    record_index: int | None = None,
    extra_details: tuple[tuple[str, JsonValue], ...] = (),
) -> Never:
    details: list[tuple[str, JsonValue]] = [("operation", operation)]
    if record_index is not None:
        details.append(("record_index", record_index))
    details.extend(extra_details)
    fail_repository(
        GIT_MALFORMED_OUTPUT,
        message,
        path=path,
        details=tuple(details),
    )
