"""Shared deterministic command-data projections for text and JSON reports."""

from __future__ import annotations

from collections import Counter
from datetime import date

from repo_context.model import (
    EffectiveFilePolicy,
    FileAssessment,
    FileRatchetAssessment,
    LimitState,
)
from repo_context.report_common import diagnostic_value, selector_value
from repo_context.run_model import PathExplanation, RepositoryRun
from repo_context.size_policy import exception_is_expired
from repo_context.sizes import classification_counts, largest_governed_files


def check_value(run: RepositoryRun) -> dict[str, object]:
    return {
        "evaluation_date": run.evaluation_date.isoformat(),
        "base_commit_id": run.base_commit_id,
        "baseline_source": run.ratchet.baseline_source.value,
        "inventory_count": len(run.inventory),
        "governed_document_count": len(run.documentation.governed_paths),
        "context_count": len(run.sizes.contexts),
    }


def audit_value(run: RepositoryRun) -> dict[str, object]:
    largest = largest_governed_files(run.sizes)
    above_warning = tuple(
        item
        for item in run.sizes.files
        if item.limit_state in {LimitState.WARNING, LimitState.HARD}
    )
    directories = tuple(
        {
            "path": item.path,
            "depth": 0 if item.path == "." else len(item.path.split("/")),
            "document_count": len(item.document_paths),
            "child_directory_count": len(item.child_paths),
            "fan_out": sum(path != item.index_path for path in item.document_paths)
            + len(item.child_paths),
        }
        for item in run.documentation.directories
    )
    selected_exceptions = Counter(
        item.policy.exception_match.exception_index
        for item in run.sizes.files
        if item.policy is not None and item.policy.exception_match is not None
    )
    return {
        **check_value(run),
        "largest_governed_files": [
            _file_value(item, run.evaluation_date) for item in largest
        ],
        "files_above_warning": [
            _file_value(item, run.evaluation_date) for item in above_warning
        ],
        "classification_counts": [
            {"kind": kind.value, "count": count}
            for kind, count in classification_counts(run.sizes)
        ],
        "contexts": [
            {
                "name": item.name,
                "total_bytes": item.total_bytes,
                "warn_bytes": item.warn_bytes,
                "hard_bytes": item.hard_bytes,
                "limit_state": item.limit_state.value,
                "missing_exact_paths": list(item.missing_exact_paths),
                "members": [
                    {
                        "path": member.path,
                        "required_exact": member.required_exact,
                        "matched_pattern_indexes": list(member.matched_pattern_indexes),
                        "counted_bytes": member.counted_bytes,
                    }
                    for member in item.members
                ],
            }
            for item in run.sizes.contexts
        ],
        "documentation": {
            "roots": list(run.documentation.roots),
            "governed_paths": list(run.documentation.governed_paths),
            "directory_count": len(directories),
            "max_depth": max((item["depth"] for item in directories), default=0),
            "directories": list(directories),
            "edge_count": len(run.documentation.edges),
            "unreachable_paths": list(run.documentation.unreachable_paths),
        },
        "migration": [_migration_value(item) for item in run.ratchet.files],
        "exceptions": [
            {
                "index": index,
                "selector": selector_value(item.selector),
                "owner": item.owner,
                "rationale": item.rationale,
                "tracking_reference": item.tracking_reference,
                "created_on": item.created_on.isoformat(),
                "expires_on": (
                    None if item.expires_on is None else item.expires_on.isoformat()
                ),
                "expired": exception_is_expired(item, run.evaluation_date),
                "selected_path_count": selected_exceptions[index],
            }
            for index, item in enumerate(run.policy.exceptions.records)
        ],
        "changes_from_base": [
            diagnostic_value(item)
            for item in run.diagnostics
            if item.code.startswith("RAT") and item.code != "RAT001"
        ],
    }


def explanation_value(explanation: PathExplanation) -> dict[str, object]:
    policy = explanation.file.policy
    assessment = explanation.file.assessment
    migration = explanation.migration
    return {
        "path": explanation.file.path,
        "evaluation_date": explanation.run.evaluation_date.isoformat(),
        "base_commit_id": explanation.run.base_commit_id,
        "baseline_source": explanation.run.ratchet.baseline_source.value,
        "policy": None
        if policy is None
        else _policy_value(policy, explanation.run.evaluation_date),
        "context_sets": list(explanation.file.context_sets),
        "assessment": None
        if assessment is None
        else _file_value(assessment, explanation.run.evaluation_date),
        "documentation": {
            "governed": explanation.documentation.governed,
            "document": explanation.documentation.document,
            "root": explanation.documentation.root,
            "unreachable": explanation.documentation.unreachable,
            "inbound_paths": list(explanation.documentation.inbound_paths),
            "outbound_paths": list(explanation.documentation.outbound_paths),
        },
        "migration": {
            "status": "not_applicable",
            "baseline_source": explanation.run.ratchet.baseline_source.value,
        }
        if migration is None
        else _migration_value(migration),
    }


def _file_value(
    assessment: FileAssessment,
    evaluation_date: date,
) -> dict[str, object]:
    policy = assessment.policy
    hard = None if policy is None else policy.effective_hard_bytes
    percent = (
        None
        if assessment.size_bytes is None or hard is None
        else round(assessment.size_bytes * 100 / hard, 2)
    )
    return {
        "path": assessment.entry.path,
        "inventory_source": assessment.entry.source.value,
        "worktree_kind": assessment.entry.kind.value,
        "size_bytes": assessment.size_bytes,
        "content_state": (
            None if assessment.content_state is None else assessment.content_state.value
        ),
        "content_identity": assessment.content_identity,
        "limit_state": (
            None if assessment.limit_state is None else assessment.limit_state.value
        ),
        "percent_of_effective_hard": percent,
        "policy": None
        if policy is None
        else _policy_value(policy, evaluation_date),
    }


def _policy_value(
    policy: EffectiveFilePolicy,
    evaluation_date: date,
) -> dict[str, object]:
    override = policy.override_match
    exception = policy.exception_match
    return {
        "kind": policy.kind.value,
        "rule": {
            "index": policy.rule_match.rule_index,
            "name": policy.rule_match.rule.name,
            "pattern_index": policy.rule_match.pattern_index,
            "pattern": policy.rule_match.pattern,
        },
        "override": None
        if override is None
        else {
            "index": override.override_index,
            "selector": selector_value(override.override.selector),
            "warn_bytes": override.override.warn_bytes,
            "hard_bytes": override.override.hard_bytes,
            "specificity": (
                None if override.specificity is None else list(override.specificity)
            ),
        },
        "exception": None
        if exception is None
        else {
            "index": exception.exception_index,
            "selector": selector_value(exception.exception.selector),
            "owner": exception.exception.owner,
            "rationale": exception.exception.rationale,
            "tracking_reference": exception.exception.tracking_reference,
            "created_on": exception.exception.created_on.isoformat(),
            "expires_on": (
                None
                if exception.exception.expires_on is None
                else exception.exception.expires_on.isoformat()
            ),
            "expired": exception_is_expired(exception.exception, evaluation_date),
            "scan": exception.exception.scan,
            "warn_bytes": exception.exception.warn_bytes,
            "hard_bytes": exception.exception.hard_bytes,
            "specificity": (
                None if exception.specificity is None else list(exception.specificity)
            ),
        },
        "ordinary_scan": policy.ordinary_scan,
        "ordinary_warn_bytes": policy.ordinary_warn_bytes,
        "ordinary_hard_bytes": policy.ordinary_hard_bytes,
        "effective_scan": policy.effective_scan,
        "effective_warn_bytes": policy.effective_warn_bytes,
        "effective_hard_bytes": policy.effective_hard_bytes,
    }


def _migration_value(item: FileRatchetAssessment) -> dict[str, object]:
    return {
        "path": item.path,
        "status": item.migration_status.value,
        "baseline_source": item.baseline_source.value,
        "current_size_bytes": item.current_size_bytes,
        "ordinary_hard_bytes": item.ordinary_hard_bytes,
        "base_size_bytes": item.base_size_bytes,
        "base_content_identity": item.base_content_identity,
        "ceiling_bytes": item.ceiling_bytes,
    }
