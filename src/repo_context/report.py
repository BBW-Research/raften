"""Pure output-format dispatch and semantic exit-code selection."""

from __future__ import annotations

from repo_context.model import OutputFormat, Severity
from repo_context.report_common import (
    ReportOutcome,
    outcome_diagnostics,
    outcome_status,
)
from repo_context.report_emergency import render_emergency_failure
from repo_context.report_json import render_json
from repo_context.report_sarif import render_sarif
from repo_context.report_text import render_text
from repo_context.run_model import RunStatus


__all__ = ("command_exit_code", "render_emergency_failure", "render_report")


def render_report(
    command: str,
    outcome: ReportOutcome,
    output_format: OutputFormat,
) -> str:
    if output_format is OutputFormat.TEXT:
        return render_text(command, outcome)
    if output_format is OutputFormat.JSON:
        return render_json(command, outcome)
    if command != "check":
        raise ValueError("SARIF output is supported only for check")
    return render_sarif(command, outcome)


def command_exit_code(command: str, outcome: ReportOutcome) -> int:
    if outcome_status(outcome) is not RunStatus.COMPLETE:
        return 2
    if command == "check" and any(
        item.severity is Severity.ERROR
        for item in outcome_diagnostics(command, outcome)
    ):
        return 1
    return 0
