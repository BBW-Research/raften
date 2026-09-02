"""SARIF 2.1.0 diagnostics with only verified artifact locations."""

from __future__ import annotations

import json
from urllib.parse import quote

from repo_context import __version__
from repo_context.model import Diagnostic
from repo_context.report_common import (
    ReportOutcome,
    json_value,
    outcome_diagnostics,
    outcome_status,
)
from repo_context.run_model import PathExplanation, RepositoryRun, RunStatus


SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"


def render_sarif(command: str, outcome: ReportOutcome) -> str:
    diagnostics = outcome_diagnostics(command, outcome)
    artifact_paths = _artifact_paths(outcome)
    rules = []
    for code in sorted({item.code for item in diagnostics}):
        first = next(item for item in diagnostics if item.code == code)
        rules.append(
            {
                "id": code,
                "shortDescription": {"text": first.message},
            }
        )
    document = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "repo-context",
                        "version": __version__,
                        "rules": rules,
                    }
                },
                "invocations": [
                    {
                        "executionSuccessful": outcome_status(outcome) is RunStatus.COMPLETE,
                    }
                ],
                "results": [
                    _result_value(item, artifact_paths)
                    for item in diagnostics
                ],
            }
        ],
    }
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def _result_value(
    diagnostic: Diagnostic,
    artifact_paths: frozenset[str],
) -> dict[str, object]:
    value: dict[str, object] = {
        "ruleId": diagnostic.code,
        "level": diagnostic.severity.value,
        "message": {"text": diagnostic.message},
        "properties": {
            "field_path": diagnostic.field_path,
            "details": {key: json_value(item) for key, item in diagnostic.details},
            "hint": diagnostic.hint,
        },
    }
    location = diagnostic.location
    if location is not None and location.path in artifact_paths:
        physical: dict[str, object] = {
            "artifactLocation": {
                "uri": quote(location.path, safe="/-._~"),
                "uriBaseId": "%SRCROOT%",
            }
        }
        if location.line is not None and location.line > 0:
            region: dict[str, int] = {"startLine": location.line}
            if location.column is not None and location.column > 0:
                region["startColumn"] = location.column
            physical["region"] = region
        value["locations"] = [{"physicalLocation": physical}]
    return value


def _artifact_paths(outcome: ReportOutcome) -> frozenset[str]:
    if isinstance(outcome, PathExplanation):
        run = outcome.run
    elif isinstance(outcome, RepositoryRun):
        run = outcome
    else:
        return frozenset()
    return frozenset({run.config_path, *(item.path for item in run.inventory)})
