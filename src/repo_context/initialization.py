"""Guarded first-adoption policy and debt initialization."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Never

from repo_context.command_paths import validate_command_path
from repo_context.config import ConfigurationError, render_starter_policy, starter_policy
from repo_context.debt import capture_debt_manifest, debt_manifest_path, render_debt_manifest
from repo_context.diagnostics import (
    INIT_DEBT_REQUIRED,
    INIT_REPOSITORY_DIRTY,
    operational_diagnostic,
)
from repo_context.init_safety import (
    InitializationError,
    _fail,
    _open_root_anchor,
    _require_safe_install_primitives,
)
from repo_context.init_transaction import _Artifact, _write_artifacts
from repo_context.inventory import (
    RepositoryAccessError,
    RepositoryHandle,
    inventory_worktree,
    open_repository,
    read_worktree_bytes,
    repository_is_clean,
)
from repo_context.model import MigrationDebtManifest, SizeEvaluation
from repo_context.run_model import CommandFailure, InitOutcome, InitResult, RunStatus
from repo_context.size_policy import compile_size_policy
from repo_context.sizes import evaluate_sizes


def initialize_repository(
    repository_path: str | Path,
    *,
    config_path: str | Path = "repo-context.toml",
    capture_debt: bool = False,
    force: bool = False,
) -> InitOutcome:
    """Create canonical initialization artifacts after all preconditions pass."""

    try:
        selected_config = validate_command_path(config_path, "--config")
        return _initialize_repository(
            repository_path,
            config_path=selected_config,
            capture_debt=capture_debt,
            force=force,
        )
    except ConfigurationError as error:
        return CommandFailure(RunStatus.CONFIGURATION_ERROR, error.diagnostics)
    except RepositoryAccessError as error:
        return CommandFailure(RunStatus.OPERATIONAL_ERROR, error.diagnostics)
    except InitializationError as error:
        return CommandFailure(RunStatus.OPERATIONAL_ERROR, error.diagnostics)


def _initialize_repository(
    repository_path: str | Path,
    *,
    config_path: str,
    capture_debt: bool,
    force: bool,
) -> InitResult:
    repository = open_repository(repository_path)
    _require_safe_install_primitives()
    root_anchor_fd = _open_root_anchor(repository.root)
    try:
        return _initialize_anchored(
            repository,
            root_anchor_fd,
            config_path=config_path,
            capture_debt=capture_debt,
            force=force,
        )
    finally:
        os.close(root_anchor_fd)


def _initialize_anchored(
    repository: RepositoryHandle,
    root_anchor_fd: int,
    *,
    config_path: str,
    capture_debt: bool,
    force: bool,
) -> InitResult:
    _require_clean(repository)
    manifest_path = debt_manifest_path(config_path)
    snapshot = inventory_worktree(repository)
    excluded = frozenset({config_path, manifest_path})
    entries = tuple(entry for entry in snapshot.entries if entry.path not in excluded)
    sizes = evaluate_sizes(
        compile_size_policy(starter_policy()),
        entries,
        lambda entry: read_worktree_bytes(repository, entry),
        evaluation_date=date.min,
    )
    manifest = capture_debt_manifest(sizes.files)
    if manifest.entries and not capture_debt:
        _fail_debt_required(manifest, sizes)

    artifacts: list[_Artifact] = []
    if capture_debt:
        artifacts.append(_Artifact(manifest_path, render_debt_manifest(manifest)))
    artifacts.append(_Artifact(config_path, render_starter_policy()))
    _require_clean(repository)
    absence_guards = (
        ()
        if capture_debt
        else (_Artifact(manifest_path, render_debt_manifest(manifest)),)
    )
    _write_artifacts(
        repository.root,
        artifacts,
        root_anchor_fd=root_anchor_fd,
        force=force,
        absence_guards=absence_guards,
    )
    return InitResult(
        repository_root=repository.root,
        config_path=config_path,
        debt_manifest_path=manifest_path if capture_debt else None,
        manifest=manifest if capture_debt else None,
        written_paths=tuple(item.path for item in artifacts),
    )


def _require_clean(repository: RepositoryHandle) -> None:
    if repository_is_clean(repository):
        return
    _fail(
        INIT_REPOSITORY_DIRTY,
        "initialization requires a clean index and worktree",
        hint="commit or stash tracked and nonignored-untracked changes, then retry",
    )


def _fail_debt_required(
    manifest: MigrationDebtManifest,
    sizes: SizeEvaluation,
) -> Never:
    assessments = {item.entry.path: item for item in sizes.files}
    diagnostics = tuple(
        operational_diagnostic(
            INIT_DEBT_REQUIRED,
            "authored file exceeds the starter policy hard limit",
            path=entry.path,
            details=(
                ("size_bytes", entry.size_bytes),
                (
                    "ordinary_hard_bytes",
                    assessments[entry.path].policy.ordinary_hard_bytes,
                ),
            ),
            hint="split the file or retry with --capture-debt",
        )
        for entry in manifest.entries
    )
    raise InitializationError(diagnostics)
