"""Descriptor-safe preparation of initialization artifacts."""

from __future__ import annotations

import errno
import os
import secrets
import stat
from pathlib import Path

from repo_context.diagnostics import INIT_DESTINATION
from repo_context.init_recovery import (
    _Artifact,
    _PreparedArtifact,
    _metadata_identity,
    _relative_auxiliary_path,
    _unlink_owned_at,
)
from repo_context.init_safety import _fail, _open_parent


class _PreparationFailure(RuntimeError):
    """A preparation failure that left ownership-uncertain auxiliary data."""

    def __init__(self, error: Exception, recovery_paths: tuple[str, ...]) -> None:
        self.error = error
        self.recovery_paths = recovery_paths
        super().__init__(str(error))


def _prepare_artifact(
    root: Path,
    artifact: _Artifact,
    *,
    root_anchor_fd: int,
    force: bool,
    existing_message: str = "initialization destination already exists",
    existing_hint: str = "retry with --force only when replacement is intended",
) -> _PreparedArtifact:
    components = artifact.path.split("/")
    parent_components = tuple(components[:-1])
    root_fd, parent_fd = _open_parent(
        root,
        root_anchor_fd,
        parent_components,
        artifact.path,
    )
    target_name = components[-1]
    temporary_name: str | None = None
    backup_name: str | None = None
    removal_name: str | None = None
    temporary_created = False
    backup_created = False
    removal_created = False
    temporary_identity: tuple[int, int, int, int, int] | None = None
    removal_identity: tuple[int, int, int, int, int] | None = None
    try:
        target_metadata = _target_metadata(
            parent_fd,
            target_name,
            artifact.path,
            force=force,
            existing_message=existing_message,
            existing_hint=existing_hint,
        )
        target_identity = (
            None if target_metadata is None else _metadata_identity(target_metadata)
        )
        existed = target_metadata is not None
        token = secrets.token_hex(12)
        temporary_name = f".{target_name}.repo-context-{token}.tmp"
        backup_name = f".{target_name}.repo-context-{token}.bak" if existed else None
        removal_name = f".{target_name}.repo-context-{token}.rollback"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_name, flags, 0o600, dir_fd=parent_fd)
        temporary_created = True
        temporary_identity = _metadata_identity(os.fstat(descriptor))
        try:
            _write_all(descriptor, artifact.data)
            os.fchmod(descriptor, 0o644)
            os.fsync(descriptor)
            artifact_identity = _metadata_identity(os.fstat(descriptor))
        finally:
            try:
                temporary_identity = _metadata_identity(os.fstat(descriptor))
            except OSError:
                pass
            os.close(descriptor)
        removal_descriptor = os.open(removal_name, flags, 0o600, dir_fd=parent_fd)
        removal_created = True
        removal_identity = _metadata_identity(os.fstat(removal_descriptor))
        try:
            os.fsync(removal_descriptor)
        finally:
            os.close(removal_descriptor)
        if backup_name is not None:
            os.link(
                target_name,
                backup_name,
                src_dir_fd=parent_fd,
                dst_dir_fd=parent_fd,
                follow_symlinks=False,
            )
            backup_created = True
        return _PreparedArtifact(
            artifact,
            root,
            root_fd,
            parent_fd,
            parent_components,
            target_name,
            temporary_name,
            backup_name,
            target_identity,
            artifact_identity,
            removal_name,
            removal_identity,
        )
    except Exception as error:
        recovery_paths: set[str] = set()
        created_names = (
            (temporary_created, temporary_name, temporary_identity),
            (backup_created, backup_name, target_identity if backup_created else None),
            (removal_created, removal_name, removal_identity),
        )
        for created, name, identity in created_names:
            if created and name is not None and not _unlink_owned_at(
                parent_fd,
                name,
                identity,
            ):
                recovery_paths.add(_relative_auxiliary_path(parent_components, name))
        os.close(parent_fd)
        os.close(root_fd)
        if recovery_paths:
            raise _PreparationFailure(error, tuple(sorted(recovery_paths))) from error
        raise


def _target_metadata(
    parent_fd: int,
    name: str,
    path: str,
    *,
    force: bool,
    existing_message: str,
    existing_hint: str,
) -> os.stat_result | None:
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    except OSError as error:
        _fail(
            INIT_DESTINATION,
            "initialization destination could not be inspected safely",
            path=path,
            details=(("error_type", type(error).__name__),),
        )
    if not stat.S_ISREG(metadata.st_mode):
        _fail(
            INIT_DESTINATION,
            "initialization destination must be absent or a regular file",
            path=path,
        )
    if not force:
        _fail(
            INIT_DESTINATION,
            existing_message,
            path=path,
            hint=existing_hint,
        )
    return metadata


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError(errno.EIO, "zero-length initialization write")
        view = view[written:]
