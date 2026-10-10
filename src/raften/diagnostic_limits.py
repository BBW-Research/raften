"""Bound diagnostic retention at every producer before aggregation."""

from collections.abc import Iterable

from raften import resource_limits as limits
from raften.diagnostics import GIT_RESOURCE_LIMIT
from raften.model import Diagnostic
from raften.repository_errors import fail_repository


class DiagnosticBuffer(list[Diagnostic]):
    def __init__(self, values: Iterable[Diagnostic] = (), *, code: str = GIT_RESOURCE_LIMIT) -> None:
        super().__init__()
        self.code = code
        self.extend(values)

    def append(self, value: Diagnostic) -> None:
        if len(self) >= limits.MAX_COMMAND_DIAGNOSTICS:
            fail_repository(self.code, "evaluation exceeds an operational diagnostic limit",
                            details=(("resource", "diagnostics"),
                                     ("limit", limits.MAX_COMMAND_DIAGNOSTICS)))
        super().append(value)

    def extend(self, values: Iterable[Diagnostic]) -> None:
        for value in values:
            self.append(value)
