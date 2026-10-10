"""Versioned JSON command reports."""

from __future__ import annotations

from raften import __version__
from raften.report_common import (
    ReportOutcome,
    diagnostic_value,
    outcome_diagnostics,
    outcome_status,
    summary_value,
)
from raften.report_data import audit_value, check_value, explanation_value
from raften.report_encoding import encode_report
from raften.run_model import InitResult, PathExplanation, RunStatus
from raften.evaluation_limits import EvaluationBudget


JSON_SCHEMA_VERSION = 1


def render_json(command: str, outcome: ReportOutcome, *,
                budget: EvaluationBudget | None = None) -> str:
    diagnostics = outcome_diagnostics(command, outcome, budget=budget)
    document = {
        "schema_version": JSON_SCHEMA_VERSION,
        "tool": {"name": "raften", "version": __version__},
        "command": command,
        "status": outcome_status(outcome).value,
        "summary": summary_value(diagnostics),
        "diagnostics": (diagnostic_value(item) for item in diagnostics),
        "data": _data_value(command, outcome),
    }
    return encode_report(document)


def _data_value(command: str, outcome: ReportOutcome) -> object:
    if outcome_status(outcome) is not RunStatus.COMPLETE:
        return None
    if isinstance(outcome, InitResult):
        return {
            "config_path": outcome.config_path,
            "debt_manifest_path": outcome.debt_manifest_path,
            "captured_debt_count": 0 if outcome.manifest is None else len(outcome.manifest.entries),
            "written_paths": list(outcome.written_paths),
        }
    if isinstance(outcome, PathExplanation):
        return explanation_value(outcome)
    if command == "audit":
        return audit_value(outcome, lazy=True)
    return check_value(outcome)
