"""Pure output-format dispatch and semantic exit-code selection."""

from __future__ import annotations

from raften.model import OutputFormat, Severity
from raften.report_common import (
    ReportOutcome,
    outcome_diagnostics,
    outcome_status,
)
from raften.report_emergency import render_emergency_failure
from raften.report_json import render_json
from raften.report_sarif import render_sarif
from raften.report_text import render_text
from raften.run_model import RunStatus
from raften.evaluation_limits import EvaluationBudget


__all__ = ("command_exit_code", "render_emergency_failure", "render_report")


def render_report(
    command: str,
    outcome: ReportOutcome,
    output_format: OutputFormat,
    *, budget: EvaluationBudget | None = None,
) -> str:
    if output_format is OutputFormat.TEXT:
        return render_text(command, outcome, budget=budget)
    if output_format is OutputFormat.JSON:
        return render_json(command, outcome, budget=budget)
    if command != "check":
        raise ValueError("SARIF output is supported only for check")
    return render_sarif(command, outcome, budget=budget)


def command_exit_code(command: str, outcome: ReportOutcome) -> int:
    if outcome_status(outcome) is not RunStatus.COMPLETE:
        return 2
    if command == "check" and any(
        item.severity is Severity.ERROR
        for item in outcome_diagnostics(command, outcome)
    ):
        return 1
    return 0
