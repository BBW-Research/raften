"""Concise one-line-safe human reports."""

from __future__ import annotations

import json

from raften.model import Diagnostic, Severity
from raften.report_common import (
    ReportOutcome,
    json_value,
    outcome_diagnostics,
    outcome_status,
    summary_value,
)
from raften.report_data import audit_value, explanation_value
from raften.run_model import InitResult, PathExplanation, RunStatus


def render_text(command: str, outcome: ReportOutcome) -> str:
    diagnostics = outcome_diagnostics(command, outcome)
    lines: list[str] = []
    if outcome_status(outcome) is RunStatus.COMPLETE:
        if isinstance(outcome, InitResult):
            lines.extend(f"Wrote {_quoted(path)}." for path in outcome.written_paths)
        elif isinstance(outcome, PathExplanation):
            lines.extend(_explanation_lines(explanation_value(outcome)))
        elif command == "audit":
            lines.extend(_audit_lines(audit_value(outcome)))
    lines.extend(_diagnostic_line(item) for item in diagnostics)
    counts = summary_value(diagnostics)
    lines.append(
        "Summary: "
        f"{_count(counts['errors'], 'error')}, "
        f"{_count(counts['warnings'], 'warning')}, "
        f"{_count(counts['notes'], 'note')}."
    )
    return "\n".join(lines) + "\n"


def _diagnostic_line(diagnostic: Diagnostic) -> str:
    location = diagnostic.location
    rendered_location = "<global>" if location is None else _quoted(location.path)
    if location is not None and location.line is not None:
        rendered_location += f":{location.line}"
        if location.column is not None:
            rendered_location += f":{location.column}"
    field = "" if diagnostic.field_path is None else f" [{diagnostic.field_path}]"
    details = ""
    if diagnostic.details:
        details = " " + json.dumps(
            {key: json_value(value) for key, value in diagnostic.details},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    hint = "" if diagnostic.hint is None else f" Hint: {diagnostic.hint}"
    return (
        f"{diagnostic.severity.value.upper()} {diagnostic.code} "
        f"{rendered_location}{field}: {diagnostic.message}{details}{hint}"
    )


def _audit_lines(data: dict[str, object]) -> list[str]:
    lines = [
        f"Audit: {data['inventory_count']} inventory paths, "
        f"{data['governed_document_count']} governed documents, "
        f"baseline={data['baseline_source']}."
    ]
    classifications = data["classification_counts"]
    classification_text = ", ".join(
        f"{item['kind']}={item['count']}"
        for item in classifications
    )
    lines.append(f"Classifications: {classification_text or 'none'}.")
    largest = data["largest_governed_files"]
    if largest:
        lines.append("Largest governed files:")
        for item in largest[:10]:
            lines.append(_audit_file_line(item))
    above_warning = data["files_above_warning"]
    if above_warning:
        lines.append("Files above warning thresholds:")
        for item in above_warning:
            lines.append(_audit_file_line(item, include_state=True))
    contexts = data["contexts"]
    if contexts:
        lines.append("Context sets:")
        for item in contexts:
            lines.append(
                f"  {_quoted(item['name'])}: {item['total_bytes']} bytes, "
                f"state={item['limit_state']}."
            )
    documentation = data["documentation"]
    lines.append(
        f"Documentation: {documentation['directory_count']} directories, "
        f"max depth={documentation['max_depth']}, "
        f"{len(documentation['unreachable_paths'])} unreachable."
    )
    directories = sorted(
        documentation["directories"],
        key=lambda item: (-item["fan_out"], item["path"]),
    )
    if directories:
        lines.append("Highest documentation fan-out:")
        for item in directories[:10]:
            lines.append(
                f"  {_quoted(item['path'])}: depth={item['depth']}, "
                f"fan_out={item['fan_out']}."
            )
    migration = data["migration"]
    if migration:
        lines.append("Migration candidates:")
        for item in migration:
            lines.append(
                f"  {_quoted(item['path'])}: status={item['status']}, "
                f"ceiling={item['ceiling_bytes']}."
            )
    exceptions = data["exceptions"]
    if exceptions:
        lines.append("Intentional exceptions:")
        for item in exceptions:
            lines.append(
                f"  {item['index']}: selector={json.dumps(item['selector'], ensure_ascii=True, sort_keys=True)}, "
                f"owner={_quoted(item['owner'])}, expired={_bool(item['expired'])}, "
                f"selected_paths={item['selected_path_count']}."
            )
    lines.append(f"Changes from base: {len(data['changes_from_base'])}.")
    return lines


def _explanation_lines(data: dict[str, object]) -> list[str]:
    lines = [f"Path: {_quoted(data['path'])}."]
    policy = data["policy"]
    if policy is None:
        lines.append("Policy: unmatched.")
    else:
        lines.append(
            f"Policy: kind={policy['kind']}, rule={_quoted(policy['rule']['name'])} "
            f"(index {policy['rule']['index']}, pattern {_quoted(policy['rule']['pattern'])}), "
            f"ordinary_scan={_bool(policy['ordinary_scan'])}, "
            f"effective_scan={_bool(policy['effective_scan'])}, "
            f"effective_limits={policy['effective_warn_bytes']}/{policy['effective_hard_bytes']}."
        )
        lines.append(
            "Override: none."
            if policy["override"] is None
            else f"Override: {json.dumps(policy['override'], ensure_ascii=True, sort_keys=True)}."
        )
        lines.append(
            "Exception: none."
            if policy["exception"] is None
            else f"Exception: {json.dumps(policy['exception'], ensure_ascii=True, sort_keys=True)}."
        )
    assessment = data["assessment"]
    if assessment is None:
        lines.append("Assessment: path is absent from the current inventory.")
    else:
        lines.append(
            f"Assessment: kind={assessment['worktree_kind']}, "
            f"content={assessment['content_state']}, size={assessment['size_bytes']}, "
            f"state={assessment['limit_state']}."
        )
    lines.append(f"Context sets: {json.dumps(data['context_sets'], ensure_ascii=True)}.")
    documentation = data["documentation"]
    lines.append(
        "Documentation: "
        f"governed={_bool(documentation['governed'])}, "
        f"document={_bool(documentation['document'])}, "
        f"root={_bool(documentation['root'])}, "
        f"unreachable={_bool(documentation['unreachable'])}."
    )
    lines.append(
        f"Documentation edges: inbound={json.dumps(documentation['inbound_paths'], ensure_ascii=True)}, "
        f"outbound={json.dumps(documentation['outbound_paths'], ensure_ascii=True)}."
    )
    migration = data["migration"]
    lines.append(
        f"Migration: status={migration['status']}, "
        f"baseline={migration['baseline_source']}, "
        f"ceiling={migration.get('ceiling_bytes')}."
    )
    return lines


def _audit_file_line(
    item: dict[str, object],
    *,
    include_state: bool = False,
) -> str:
    policy = item["policy"]
    state = f", state={item['limit_state']}" if include_state else ""
    size = "null" if item["size_bytes"] is None else f"{item['size_bytes']} bytes"
    percent = item["percent_of_effective_hard"]
    rendered_percent = "null" if percent is None else f"{percent}%"
    return (
        f"  {_quoted(item['path'])}: size={size}, classification={policy['kind']}, "
        f"rule={_quoted(policy['rule']['name'])}, "
        f"warn={policy['effective_warn_bytes']}, hard={policy['effective_hard_bytes']}, "
        f"percent_of_hard={rendered_percent}{state}."
    )


def _quoted(value: object) -> str:
    return json.dumps(value, ensure_ascii=True)


def _bool(value: object) -> str:
    return "true" if value is True else "false"


def _count(value: int, noun: str) -> str:
    return f"{value} {noun if value == 1 else noun + 's'}"
