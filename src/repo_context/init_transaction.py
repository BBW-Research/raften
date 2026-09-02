"""Descriptor-safe initialization artifact activation and coordination."""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from repo_context.diagnostics import (
    INIT_DESTINATION,
    INIT_WRITE,
)
from repo_context.init_preparation import _PreparationFailure, _prepare_artifact
from repo_context.init_recovery import (
    _Artifact,
    _PreparedArtifact,
    _auxiliary_path,
    _close_prepared,
    _metadata_identity,
    _name_exists,
    _name_has_identity,
    _remove_backups,
    _renew_removal_placeholder,
    _retained_recovery_paths,
    _rollback,
    _unlink_owned_name,
)
from repo_context.init_safety import (
    InitializationError,
    _fail,
    _require_safe_install_primitives,
    _require_unchanged_parent,
)


def _with_recovery_paths(
    error: InitializationError,
    recovery_paths: Sequence[str],
) -> InitializationError:
    merged = set(recovery_paths)
    for diagnostic in error.diagnostics:
        for key, value in diagnostic.details:
            if key == "recovery_paths" and isinstance(value, tuple):
                merged.update(str(path) for path in value)
    retained = tuple(sorted(merged))
    return InitializationError(
        tuple(
            replace(
                diagnostic,
                details=(
                    *(item for item in diagnostic.details if item[0] != "recovery_paths"),
                    ("recovery_paths", retained),
                ),
            )
            for diagnostic in error.diagnostics
        )
    )


def _write_artifacts(
    root: Path,
    artifacts: Sequence[_Artifact],
    *,
    root_anchor_fd: int,
    force: bool,
    absence_guards: Sequence[_Artifact] = (),
) -> None:
    _require_safe_install_primitives()
    prepared: list[_PreparedArtifact] = []
    committed = False
    try:
        for guard in absence_guards:
            prepared.append(
                _prepare_artifact(
                    root,
                    guard,
                    root_anchor_fd=root_anchor_fd,
                    force=False,
                    existing_message=(
                        "an existing debt manifest cannot be left behind by "
                        "initialization without capture"
                    ),
                    existing_hint="retry with --capture-debt to regenerate the manifest",
                )
            )
        guard_count = len(prepared)
        for artifact in artifacts:
            prepared.append(
                _prepare_artifact(
                    root,
                    artifact,
                    root_anchor_fd=root_anchor_fd,
                    force=force,
                )
            )
        for index, item in enumerate(prepared):
            _install_artifact(item, force=False if index < guard_count else force)
        for item in prepared[:guard_count]:
            _remove_absence_guard(item)
        for item in prepared[guard_count:]:
            _revalidate_parent(item)
            _require_installed_artifact(item)
        for item in prepared[:guard_count]:
            _require_absence_guard_target_absent(item)
        committed = True
        _remove_backups(prepared)
    except _PreparationFailure as failure:
        recovery_paths = set(failure.recovery_paths)
        recovery_paths.update(_rollback(prepared))
        retained = tuple(sorted(recovery_paths))
        if isinstance(failure.error, InitializationError):
            raise _with_recovery_paths(failure.error, retained) from failure.error
        _fail(
            INIT_WRITE,
            "initialization artifacts could not be prepared safely",
            details=(
                ("error_type", type(failure.error).__name__),
                ("recovery_paths", retained),
            ),
            hint="preserve the reported recovery files while reconciling concurrent changes",
        )
    except InitializationError as error:
        recovery_paths: tuple[str, ...] = ()
        if not committed:
            recovery_paths = _rollback(prepared)
        if recovery_paths:
            raise _with_recovery_paths(error, recovery_paths) from error
        raise
    except OSError as error:
        if committed:
            recovery_paths = _retained_recovery_paths(prepared)
            details = [("error_type", type(error).__name__)]
            if recovery_paths:
                details.append(("recovery_paths", recovery_paths))
            _fail(
                INIT_WRITE,
                "initialization artifacts were installed but rollback backups could not be removed",
                details=tuple(details),
                hint=(
                    "preserve the reported recovery files while reconciling concurrent changes"
                    if recovery_paths
                    else "inspect the destination directories for a retained .repo-context backup"
                ),
            )
        recovery_paths = _rollback(prepared)
        details = [("error_type", type(error).__name__)]
        if recovery_paths:
            details.append(("recovery_paths", recovery_paths))
        _fail(
            INIT_WRITE,
            "initialization artifacts could not be written atomically",
            details=tuple(details),
            hint=(
                "preserve the reported recovery files while reconciling concurrent changes"
                if recovery_paths
                else None
            ),
        )
    except Exception as error:
        if not committed:
            recovery_paths = _rollback(prepared)
            if recovery_paths:
                _fail(
                    INIT_WRITE,
                    "initialization rollback preserved concurrent destination changes",
                    details=(
                        ("error_type", type(error).__name__),
                        ("recovery_paths", recovery_paths),
                    ),
                    hint="preserve the reported recovery files while reconciling concurrent changes",
                )
        raise
    finally:
        _close_prepared(prepared)


def _install_artifact(item: _PreparedArtifact, *, force: bool) -> None:
    _revalidate_parent(item)
    _require_owned_auxiliary(
        item,
        item.temporary_name,
        item.artifact_identity,
        "temporary artifact",
    )
    if item.removal_name is None:
        raise AssertionError("prepared artifact has no rollback quarantine")
    _require_owned_auxiliary(
        item,
        item.removal_name,
        item.removal_identity,
        "rollback quarantine",
    )
    if force and item.target_identity is not None:
        if item.backup_name is None:
            raise AssertionError("forced replacement has no rollback backup")
        _require_owned_auxiliary(
            item,
            item.backup_name,
            item.target_identity,
            "rollback backup",
        )
        _require_unchanged_force_target(item)
        _activate_forced_artifact(item)
    else:
        _link_temporary_artifact(item)
    _require_installed_artifact(item)
    os.fsync(item.parent_fd)
    _revalidate_parent(item)
    _require_installed_artifact(item)


def _activate_forced_artifact(item: _PreparedArtifact) -> None:
    if item.target_identity is None or item.backup_name is None:
        raise AssertionError("forced activation requires a target backup")
    if item.removal_name is None:
        raise AssertionError("forced activation requires a rollback quarantine")
    try:
        os.rename(
            item.target_name,
            item.removal_name,
            src_dir_fd=item.parent_fd,
            dst_dir_fd=item.parent_fd,
        )
    except FileNotFoundError:
        _fail(
            INIT_DESTINATION,
            "forced initialization destination changed during activation",
            path=item.artifact.path,
            details=(("state", "missing"),),
        )
    except OSError as error:
        _fail(
            INIT_DESTINATION,
            "forced initialization destination could not be quarantined",
            path=item.artifact.path,
            details=(("error_type", type(error).__name__),),
        )
    try:
        quarantined = os.stat(
            item.removal_name,
            dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        item.removal_identity = None
        item.recovery_paths.add(_auxiliary_path(item, item.removal_name))
        _fail(
            INIT_DESTINATION,
            "forced initialization destination could not be verified after quarantine",
            path=item.artifact.path,
            details=(("error_type", type(error).__name__),),
        )
    if _metadata_identity(quarantined) != item.target_identity:
        item.removal_identity = None
        item.recovery_paths.add(_auxiliary_path(item, item.removal_name))
        try:
            os.link(
                item.removal_name,
                item.target_name,
                src_dir_fd=item.parent_fd,
                dst_dir_fd=item.parent_fd,
                follow_symlinks=False,
            )
            restored = True
        except OSError:
            restored = False
        _fail(
            INIT_DESTINATION,
            "forced initialization destination changed during activation",
            path=item.artifact.path,
            details=(
                ("state", "identity_changed"),
                ("replacement_restored", restored),
            ),
        )

    item.removal_identity = item.target_identity
    original_backup_name = item.backup_name
    original_backup_retained = not _unlink_owned_name(
        item,
        original_backup_name,
        item.target_identity,
    )
    if original_backup_retained:
        item.recovery_paths.add(_auxiliary_path(item, original_backup_name))
    item.backup_name = item.removal_name
    item.removal_name = None
    item.removal_identity = None
    if original_backup_retained:
        _fail(
            INIT_WRITE,
            "forced initialization rollback backup changed during activation",
            path=item.artifact.path,
        )
    if not _renew_removal_placeholder(item):
        _fail(
            INIT_WRITE,
            "forced initialization rollback quarantine could not be renewed",
            path=item.artifact.path,
        )
    _require_owned_auxiliary(
        item,
        item.temporary_name,
        item.artifact_identity,
        "temporary artifact",
    )
    _link_temporary_artifact(item)


def _link_temporary_artifact(item: _PreparedArtifact) -> None:
    try:
        os.link(
            item.temporary_name,
            item.target_name,
            src_dir_fd=item.parent_fd,
            dst_dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except FileExistsError:
        _fail(
            INIT_DESTINATION,
            "initialization destination appeared after preflight",
            path=item.artifact.path,
            details=(("state", "created_concurrently"),),
        )
    item.installed = True
    if not _unlink_owned_name(item, item.temporary_name, item.artifact_identity):
        item.recovery_paths.add(_auxiliary_path(item, item.temporary_name))
        _fail(
            INIT_DESTINATION,
            "temporary artifact changed during activation",
            path=item.artifact.path,
            details=(("state", "identity_changed"),),
        )


def _require_installed_artifact(item: _PreparedArtifact) -> None:
    if _name_has_identity(item, item.target_name, item.artifact_identity):
        return
    state = "missing"
    if _name_exists(item, item.target_name):
        state = "identity_changed"
        item.recovery_paths.add(item.artifact.path)
    _fail(
        INIT_DESTINATION,
        "installed initialization artifact changed during activation",
        path=item.artifact.path,
        details=(("state", state),),
    )


def _require_owned_auxiliary(
    item: _PreparedArtifact,
    name: str,
    expected: tuple[int, int, int, int, int] | None,
    label: str,
) -> None:
    if expected is not None and _name_has_identity(item, name, expected):
        return
    state = "missing"
    if _name_exists(item, name):
        state = "identity_changed"
        item.recovery_paths.add(_auxiliary_path(item, name))
    _fail(
        INIT_DESTINATION,
        f"initialization {label} changed after preparation",
        path=item.artifact.path,
        details=(("state", state),),
    )


def _require_unchanged_force_target(item: _PreparedArtifact) -> None:
    try:
        metadata = os.stat(
            item.target_name,
            dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        _fail(
            INIT_DESTINATION,
            "forced initialization destination changed after preflight",
            path=item.artifact.path,
            details=(("state", "missing"),),
        )
    except OSError as error:
        _fail(
            INIT_DESTINATION,
            "forced initialization destination could not be revalidated",
            path=item.artifact.path,
            details=(("error_type", type(error).__name__),),
        )
    if not stat.S_ISREG(metadata.st_mode):
        state = "symlink" if stat.S_ISLNK(metadata.st_mode) else "non_regular"
        _fail(
            INIT_DESTINATION,
            "forced initialization destination changed after preflight",
            path=item.artifact.path,
            details=(("state", state),),
        )
    if _metadata_identity(metadata) != item.target_identity:
        _fail(
            INIT_DESTINATION,
            "forced initialization destination changed after preflight",
            path=item.artifact.path,
            details=(("state", "identity_changed"),),
        )


def _remove_absence_guard(item: _PreparedArtifact) -> None:
    if item.removal_name is None:
        raise AssertionError("absence guard has no quarantine name")
    _revalidate_parent(item)
    _require_owned_auxiliary(
        item,
        item.removal_name,
        item.removal_identity,
        "rollback quarantine",
    )
    try:
        os.rename(
            item.target_name,
            item.removal_name,
            src_dir_fd=item.parent_fd,
            dst_dir_fd=item.parent_fd,
        )
    except OSError as error:
        _fail(
            INIT_DESTINATION,
            "debt-manifest absence guard changed before cleanup",
            path=item.artifact.path,
            details=(("error_type", type(error).__name__),),
        )
    item.installed = False
    try:
        metadata = os.stat(
            item.removal_name,
            dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except OSError as error:
        item.removal_identity = None
        _fail(
            INIT_DESTINATION,
            "debt-manifest absence guard could not be revalidated after activation",
            path=item.artifact.path,
            details=(
                ("error_type", type(error).__name__),
                ("recovery_path", _auxiliary_path(item, item.removal_name)),
            ),
        )
    if _metadata_identity(metadata) != item.artifact_identity:
        item.removal_identity = None
        try:
            os.link(
                item.removal_name,
                item.target_name,
                src_dir_fd=item.parent_fd,
                dst_dir_fd=item.parent_fd,
                follow_symlinks=False,
            )
            restored = True
        except OSError:
            restored = False
        _fail(
            INIT_DESTINATION,
            "debt-manifest absence guard was replaced during initialization",
            path=item.artifact.path,
            details=(
                ("replacement_restored", restored),
                ("recovery_path", _auxiliary_path(item, item.removal_name)),
            ),
            hint="preserve the reported recovery file while reconciling the concurrent change",
        )
    item.removal_identity = item.artifact_identity
    if not _unlink_owned_name(item, item.removal_name, item.artifact_identity):
        item.removal_identity = None
        item.recovery_paths.add(_auxiliary_path(item, item.removal_name))
        _fail(
            INIT_DESTINATION,
            "debt-manifest quarantine changed before cleanup",
            path=item.artifact.path,
            details=(("state", "identity_changed"),),
        )
    item.removal_name = None
    item.removal_identity = None
    os.fsync(item.parent_fd)
    _revalidate_parent(item)


def _require_absence_guard_target_absent(item: _PreparedArtifact) -> None:
    _revalidate_parent(item)
    try:
        os.stat(
            item.target_name,
            dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return
    except OSError as error:
        _fail(
            INIT_DESTINATION,
            "debt-manifest absence could not be revalidated after cleanup",
            path=item.artifact.path,
            details=(("error_type", type(error).__name__),),
        )
    _fail(
        INIT_DESTINATION,
        "debt manifest appeared after absence-guard cleanup",
        path=item.artifact.path,
        details=(("state", "created_concurrently"),),
        hint="retry with --capture-debt to regenerate the manifest",
    )


def _revalidate_parent(item: _PreparedArtifact) -> None:
    _require_unchanged_parent(
        root_path=item.root_path,
        root_fd=item.root_fd,
        parent_fd=item.parent_fd,
        parent_components=item.parent_components,
        path=item.artifact.path,
    )
