"""Fixed-shape internal-failure rendering independent of normal dispatch."""

from __future__ import annotations

import json

from raften import __version__
from raften.diagnostics import INT_INTERNAL
from raften.model import OutputFormat
from raften.run_model import CommandFailure, RunStatus


def render_emergency_failure(
    command: str,
    outcome: CommandFailure,
    output_format: OutputFormat,
) -> str:
    """Render INT001 even when the selected normal renderer has failed."""

    diagnostic = outcome.diagnostics[0]
    details = {key: value for key, value in diagnostic.details}
    if output_format is OutputFormat.JSON:
        document = {
            "schema_version": 1,
            "tool": {"name": "raften", "version": __version__},
            "command": command,
            "status": RunStatus.INTERNAL_ERROR.value,
            "summary": {"errors": 1, "warnings": 0, "notes": 0},
            "diagnostics": [
                {
                    "code": INT_INTERNAL,
                    "severity": "error",
                    "message": diagnostic.message,
                    "location": None,
                    "field_path": None,
                    "details": details,
                    "hint": diagnostic.hint,
                }
            ],
            "data": None,
        }
        return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    if output_format is OutputFormat.SARIF:
        document = {
            "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": "raften",
                            "version": __version__,
                            "rules": [
                                {
                                    "id": INT_INTERNAL,
                                    "shortDescription": {"text": diagnostic.message},
                                }
                            ],
                        }
                    },
                    "invocations": [{"executionSuccessful": False}],
                    "results": [
                        {
                            "ruleId": INT_INTERNAL,
                            "level": "error",
                            "message": {"text": diagnostic.message},
                            "properties": {
                                "field_path": None,
                                "details": details,
                                "hint": diagnostic.hint,
                            },
                        }
                    ],
                }
            ],
        }
        return json.dumps(document, ensure_ascii=False, indent=2) + "\n"
    rendered_details = json.dumps(details, ensure_ascii=True, separators=(",", ":"))
    return (
        f"ERROR {INT_INTERNAL} <global>: {diagnostic.message} {rendered_details} "
        f"Hint: {diagnostic.hint}\n"
        "Summary: 1 error, 0 warnings, 0 notes.\n"
    )
