"""Repository orchestration without command-line or presentation concerns."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from repo_context.command_paths import (
    validate_candidate_command_path,
    validate_command_path,
)
from repo_context.config import ConfigurationError, parse_policy
from repo_context.debt import DebtManifestError, debt_manifest_path, parse_debt_manifest
from repo_context.diagnostics import (
    CFG_PARSE,
    GIT_BASE_OBJECT,
    config_diagnostic,
    diagnostic_sort_key,
)
from repo_context.docs import (
    compile_documentation_policy,
    documentation_text_paths,
    evaluate_documentation,
)
from repo_context.inventory import (
    InventorySnapshot,
    RepositoryAccessError,
    RepositoryHandle,
    find_base_entry,
    inspect_repository_path,
    inventory_worktree,
    list_base_tree,
    open_repository,
    read_base_blob,
    read_worktree_bytes,
    resolve_base_revision,
)
from repo_context.initialization import initialize_repository
from repo_context.model import (
    BaseTreeEntry,
    Diagnostic,
    FileAssessment,
    FileRatchetEvaluation,
    GitFileMode,
    GitObjectType,
    InventoryEntry,
    Policy,
    MigrationDebtManifest,
    RatchetUnavailableReason,
    WorktreeKind,
)
from repo_context.policy_ratchet import compare_policies
from repo_context.ratchet import (
    evaluate_file_ratchet,
    is_all_zero_ref,
    reconcile_size_diagnostics,
)
from repo_context.repository_errors import fail_repository
from repo_context.run_model import (
    CommandFailure,
    DocumentationExplanation,
    ExplainOutcome,
    PathExplanation,
    RepositoryRun,
    RunOutcome,
    RunStatus,
)
from repo_context.size_policy import compile_size_policy
from repo_context.sizes import SizePolicyError, evaluate_sizes, explain_size_path


__all__ = (
    "explain_repository_path",
    "initialize_repository",
    "run_repository",
)


@dataclass(slots=True)
class _ContentCache:
    repository: RepositoryHandle
    retained_paths: frozenset[str]
    values: dict[str, bytes] = field(default_factory=dict)

    def read(self, entry: InventoryEntry) -> bytes:
        if entry.path in self.values:
            return self.values[entry.path]
        data = read_worktree_bytes(self.repository, entry)
        if entry.path in self.retained_paths:
            self.values[entry.path] = data
        return data


@dataclass(slots=True)
class _BaseContentCache:
    repository: RepositoryHandle
    retained_object_ids: frozenset[str]
    values: dict[str, bytes] = field(default_factory=dict)

    def read(self, entry: BaseTreeEntry) -> bytes:
        if entry.object_id in self.values:
            return self.values[entry.object_id]
        data = read_base_blob(self.repository, entry)
        if entry.object_id in self.retained_object_ids:
            self.values[entry.object_id] = data
        return data


def run_repository(
    repository_path: str | Path,
    *,
    config_path: str | Path = "repo-context.toml",
    base_ref: str | None = None,
    evaluation_date: date,
) -> RunOutcome:
    """Evaluate current policy and any requested historical comparison."""

    try:
        return _run_repository(
            repository_path,
            config_path=validate_command_path(config_path, "--config"),
            base_ref=base_ref,
            evaluation_date=evaluation_date,
        )
    except ConfigurationError as error:
        return CommandFailure(RunStatus.CONFIGURATION_ERROR, error.diagnostics)
    except DebtManifestError as error:
        return CommandFailure(RunStatus.CONFIGURATION_ERROR, error.diagnostics)
    except RepositoryAccessError as error:
        return CommandFailure(RunStatus.OPERATIONAL_ERROR, error.diagnostics)


def explain_repository_path(
    repository_path: str | Path,
    path: str | Path,
    *,
    config_path: str | Path = "repo-context.toml",
    base_ref: str | None = None,
    evaluation_date: date,
) -> ExplainOutcome:
    """Evaluate the repository and project one path's complete provenance."""

    try:
        selected_path = validate_candidate_command_path(path, "PATH")
    except ConfigurationError as error:
        return CommandFailure(RunStatus.CONFIGURATION_ERROR, error.diagnostics)
    outcome = run_repository(
        repository_path,
        config_path=config_path,
        base_ref=base_ref,
        evaluation_date=evaluation_date,
    )
    if isinstance(outcome, CommandFailure):
        return outcome
    if outcome.status is not RunStatus.COMPLETE:
        return CommandFailure(outcome.status, outcome.diagnostics)
    try:
        file_explanation = explain_size_path(
            compile_size_policy(outcome.policy),
            selected_path,
            evaluation_date,
            outcome.sizes,
        )
    except SizePolicyError as error:
        return CommandFailure(RunStatus.CONFIGURATION_ERROR, error.diagnostics)
    documentation = outcome.documentation
    inbound = tuple(
        sorted(
            edge.source_path
            for edge in documentation.edges
            if edge.target_path == selected_path
        )
    )
    outbound = tuple(
        sorted(
            edge.target_path
            for edge in documentation.edges
            if edge.source_path == selected_path
        )
    )
    migration = next(
        (item for item in outcome.ratchet.files if item.path == selected_path),
        None,
    )
    return PathExplanation(
        run=outcome,
        file=file_explanation,
        documentation=DocumentationExplanation(
            governed=selected_path in documentation.governed_paths,
            document=any(item.path == selected_path for item in documentation.documents),
            root=selected_path in documentation.roots,
            unreachable=selected_path in documentation.unreachable_paths,
            inbound_paths=inbound,
            outbound_paths=outbound,
        ),
        migration=migration,
    )


def _run_repository(
    repository_path: str | Path,
    *,
    config_path: str,
    base_ref: str | None,
    evaluation_date: date,
) -> RepositoryRun:
    repository = open_repository(repository_path)
    snapshot = inventory_worktree(repository)
    content = _ContentCache(
        repository,
        frozenset({config_path, debt_manifest_path(config_path)}),
    )
    policy = _load_current_policy(repository, snapshot, content, config_path)
    compiled_documentation = compile_documentation_policy(policy)
    retained_paths = documentation_text_paths(compiled_documentation, snapshot.entries)
    sizes = evaluate_sizes(
        compile_size_policy(policy),
        snapshot.entries,
        content.read,
        evaluation_date=evaluation_date,
        retain_text_paths=retained_paths,
    )
    current_configuration_diagnostics = tuple(
        item for item in sizes.diagnostics if item.code.startswith("CFG")
    )
    if current_configuration_diagnostics:
        raise ConfigurationError(current_configuration_diagnostics)
    documentation = evaluate_documentation(
        compiled_documentation,
        snapshot.entries,
        sizes.documents,
        file_assessments=sizes.files,
    )
    ratchet, policy_diagnostics, base_commit_id = _evaluate_baseline(
        repository,
        snapshot,
        content,
        policy,
        sizes.files,
        config_path=config_path,
        base_ref=base_ref,
        evaluation_date=evaluation_date,
    )
    diagnostics = tuple(
        sorted(
            (
                *reconcile_size_diagnostics(sizes.diagnostics, ratchet),
                *documentation.diagnostics,
                *ratchet.diagnostics,
                *policy_diagnostics,
            ),
            key=diagnostic_sort_key,
        )
    )
    configuration_diagnostics = tuple(
        item for item in diagnostics if item.code.startswith("CFG")
    )
    status = (
        RunStatus.CONFIGURATION_ERROR
        if configuration_diagnostics
        else RunStatus.COMPLETE
    )
    if configuration_diagnostics:
        diagnostics = configuration_diagnostics
    return RepositoryRun(
        status=status,
        repository_root=repository.root,
        config_path=config_path,
        policy=policy,
        inventory=snapshot.entries,
        sizes=sizes,
        documentation=documentation,
        ratchet=ratchet,
        diagnostics=diagnostics,
        base_commit_id=base_commit_id,
        evaluation_date=evaluation_date,
    )


def _load_current_policy(
    repository: RepositoryHandle,
    snapshot: InventorySnapshot,
    content: _ContentCache,
    config_path: str,
) -> Policy:
    entry = _snapshot_or_direct(repository, snapshot, config_path)
    if entry.kind is not WorktreeKind.REGULAR:
        state = entry.kind.value
        raise ConfigurationError(
            (
                config_diagnostic(
                    CFG_PARSE,
                    config_path,
                    "$",
                    "configuration must be a repo-contained regular file",
                    details=(("state", state),),
                ),
            )
        )
    return parse_policy(
        content.read(entry),
        source_path=config_path,
    )


def _evaluate_baseline(
    repository: RepositoryHandle,
    snapshot: InventorySnapshot,
    content: _ContentCache,
    current_policy: Policy,
    current_files: Sequence[FileAssessment],
    *,
    config_path: str,
    base_ref: str | None,
    evaluation_date: date,
) -> tuple[FileRatchetEvaluation, tuple[Diagnostic, ...], str | None]:
    if base_ref is None:
        return (
            evaluate_file_ratchet(
                current_policy,
                current_files,
                evaluation_date=evaluation_date,
                unavailable_reason=RatchetUnavailableReason.BASE_REF_ABSENT,
            ),
            (),
            None,
        )
    if is_all_zero_ref(base_ref):
        return (
            evaluate_file_ratchet(
                current_policy,
                current_files,
                evaluation_date=evaluation_date,
                unavailable_reason=RatchetUnavailableReason.ZERO_SENTINEL,
            ),
            (),
            None,
        )

    revision = resolve_base_revision(repository, base_ref)
    base_entries = list_base_tree(repository, revision)
    config_entry = find_base_entry(base_entries, config_path)
    if config_entry is None:
        if not current_policy.ratchet.compare_file_sizes:
            return (
                evaluate_file_ratchet(
                    current_policy,
                    current_files,
                    evaluation_date=evaluation_date,
                ),
                (),
                revision.commit_id,
            )
        manifest = _load_manifest(
            repository,
            snapshot,
            content,
            config_path,
            revision.commit_id,
        )
        return (
            evaluate_file_ratchet(
                current_policy,
                current_files,
                evaluation_date=evaluation_date,
                debt_manifest=manifest,
            ),
            (),
            revision.commit_id,
        )
    if (
        config_entry.object_type is not GitObjectType.BLOB
        or config_entry.mode not in {GitFileMode.REGULAR, GitFileMode.EXECUTABLE}
    ):
        fail_repository(
            GIT_BASE_OBJECT,
            "base configuration path is not a regular blob",
            path=config_path,
            details=(
                ("base_commit_id", revision.commit_id),
                ("mode", config_entry.mode.value),
                ("object_type", config_entry.object_type.value),
            ),
        )
    base_content = _BaseContentCache(
        repository,
        frozenset({config_entry.object_id}),
    )
    base_policy = parse_policy(
        base_content.read(config_entry),
        source_path=f"git:{revision.commit_id}:{config_path}",
    )
    ratchet = evaluate_file_ratchet(
        current_policy,
        current_files,
        evaluation_date=evaluation_date,
        base_policy=base_policy,
        base_entries=base_entries,
        read_base=base_content.read,
    )
    return (
        ratchet,
        compare_policies(current_policy, base_policy, policy_path=config_path),
        revision.commit_id,
    )


def _load_manifest(
    repository: RepositoryHandle,
    snapshot: InventorySnapshot,
    content: _ContentCache,
    config_path: str,
    base_commit_id: str,
) -> MigrationDebtManifest:
    manifest_path = debt_manifest_path(config_path)
    entry = _snapshot_or_direct(repository, snapshot, manifest_path)
    if entry.kind is not WorktreeKind.REGULAR:
        state = entry.kind.value
        fail_repository(
            GIT_BASE_OBJECT,
            "base commit has no policy and no eligible first-adoption manifest is available",
            path=manifest_path,
            details=(
                ("base_commit_id", base_commit_id),
                ("config_path", config_path),
                ("state", state),
            ),
        )
    return parse_debt_manifest(
        content.read(entry),
        source_path=manifest_path,
    )


def _snapshot_or_direct(
    repository: RepositoryHandle,
    snapshot: InventorySnapshot,
    path: str,
) -> InventoryEntry:
    selected = next((entry for entry in snapshot.entries if entry.path == path), None)
    return inspect_repository_path(repository, path) if selected is None else selected
