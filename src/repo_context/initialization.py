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
from repo_context.init_recovery import _Artifact
from repo_context.init_safety import (
    InitializationError,
    _fail,
    _open_root_anchor,
    _require_safe_install_primitives,
)
from repo_context.init_transaction import _write_artifacts
from repo_context.inventory import (
    RepositoryAccessError,
    RepositoryHandle,
    capture_clean_repository,
    inventory_worktree,
    open_repository,
    read_index_verified_worktree_bytes,
    repository_remains_clean,
)
from repo_context.model import InventoryEntry, MigrationDebtManifest, SizeEvaluation
from repo_context.run_model import CommandFailure, InitOutcome, InitResult, RunStatus
from repo_context.size_policy import compile_size_policy
from repo_context.sizes import content_paths_for_evaluation, evaluate_sizes


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
    manifest_path = debt_manifest_path(config_path)
    snapshot = inventory_worktree(repository)
    excluded = frozenset({config_path, manifest_path})
    entries = tuple(entry for entry in snapshot.entries if entry.path not in excluded)
    compiled = compile_size_policy(starter_policy())
    content_paths = content_paths_for_evaluation(
        compiled,
        entries,
        evaluation_date=date.min,
    )
    clean_capture = capture_clean_repository(
        repository,
        snapshot=snapshot,
        defer_content_paths=content_paths,
    )
    if clean_capture is None:
        _fail_dirty()
    clean_state = clean_capture.state
    pending_content = set(clean_capture.deferred_content_paths)
    del clean_capture

    def read_verified_content(entry: InventoryEntry) -> bytes:
        if entry.path not in pending_content:
            raise RuntimeError("size evaluation requested unexpected content")
        data = read_index_verified_worktree_bytes(repository, entry)
        if data is None:
            _fail_dirty()
        pending_content.remove(entry.path)
        return data

    sizes = evaluate_sizes(
        compiled,
        entries,
        read_verified_content,
        evaluation_date=date.min,
    )
    if pending_content:
        raise RuntimeError("size evaluation did not consume expected content")
    manifest = capture_debt_manifest(sizes.files)
    if manifest.entries and not capture_debt:
        _fail_debt_required(manifest, sizes)

    artifacts: list[_Artifact] = []
    if capture_debt:
        artifacts.append(_Artifact(manifest_path, render_debt_manifest(manifest)))
    artifacts.append(
        _Artifact(
            config_path,
            render_starter_policy(debt_manifest_path=manifest_path),
        )
    )
    if not repository_remains_clean(repository, clean_state):
        _fail_dirty()
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


def _fail_dirty() -> Never:
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
