"""Versioned JSON command reports."""

from __future__ import annotations

import json

from repo_context import __version__
from repo_context.report_common import (
    ReportOutcome,
    diagnostic_value,
    outcome_diagnostics,
    outcome_status,
    summary_value,
)
from repo_context.report_data import audit_value, check_value, explanation_value
from repo_context.run_model import InitResult, PathExplanation, RunStatus


JSON_SCHEMA_VERSION = 1


def render_json(command: str, outcome: ReportOutcome) -> str:
    diagnostics = outcome_diagnostics(command, outcome)
    document = {
        "schema_version": JSON_SCHEMA_VERSION,
        "tool": {"name": "repo-context", "version": __version__},
        "command": command,
        "status": outcome_status(outcome).value,
        "summary": summary_value(diagnostics),
        "diagnostics": [diagnostic_value(item) for item in diagnostics],
        "data": _data_value(command, outcome),
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


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
        return audit_value(outcome)
    return check_value(outcome)
