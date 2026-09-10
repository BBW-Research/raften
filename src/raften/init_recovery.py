"""Initialization artifact records, identity-safe cleanup, and rollback."""

from __future__ import annotations

import errno
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


_Identity = tuple[int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class _Artifact:
    path: str
    data: bytes


@dataclass(slots=True)
class _PreparedArtifact:
    artifact: _Artifact
    root_path: Path
    root_fd: int
    parent_fd: int
    parent_components: tuple[str, ...]
    target_name: str
    temporary_name: str
    backup_name: str | None
    target_identity: _Identity | None
    artifact_identity: _Identity
    removal_name: str | None
    removal_identity: _Identity | None
    installed: bool = False
    recovery_paths: set[str] = field(default_factory=set)


def _rollback(prepared: Sequence[_PreparedArtifact]) -> tuple[str, ...]:
    recovery_paths: set[str] = set()
    for item in reversed(prepared):
        recovery_paths.update(item.recovery_paths)
        if item.installed:
            recovery_paths.update(_rollback_installed(item))
        elif item.backup_name is not None:
            recovery_paths.update(_discard_unused_backup(item))
        if not _unlink_owned_name(
            item,
            item.temporary_name,
            item.artifact_identity,
        ):
            recovery_paths.add(_auxiliary_path(item, item.temporary_name))
        if item.removal_name is not None:
            if item.removal_identity is None or not _unlink_owned_name(
                item,
                item.removal_name,
                item.removal_identity,
            ):
                recovery_paths.add(_auxiliary_path(item, item.removal_name))
            else:
                item.removal_name = None
                item.removal_identity = None
        try:
            os.fsync(item.parent_fd)
        except OSError:
            pass
    return tuple(sorted(recovery_paths))


def _rollback_installed(item: _PreparedArtifact) -> tuple[str, ...]:
    recovery_paths: set[str] = set()
    if item.removal_name is None:
        return (item.artifact.path,)
    if item.removal_identity is None or not _name_has_identity(
        item,
        item.removal_name,
        item.removal_identity,
    ):
        if _name_exists(item, item.removal_name):
            recovery_paths.add(_auxiliary_path(item, item.removal_name))
        if not _renew_removal_placeholder(item):
            recovery_paths.add(item.artifact.path)
            if item.backup_name is not None:
                recovery_paths.add(_auxiliary_path(item, item.backup_name))
            return tuple(recovery_paths)
    try:
        os.rename(
            item.target_name,
            item.removal_name,
            src_dir_fd=item.parent_fd,
            dst_dir_fd=item.parent_fd,
        )
        item.installed = False
    except FileNotFoundError:
        item.installed = False
        recovery_paths.update(_restore_backup(item))
        return tuple(recovery_paths)
    except OSError:
        recovery_paths.add(item.artifact.path)
        if item.backup_name is not None:
            recovery_paths.add(_auxiliary_path(item, item.backup_name))
        return tuple(recovery_paths)

    try:
        quarantined = os.stat(
            item.removal_name,
            dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        item.removal_identity = None
        recovery_paths.add(_auxiliary_path(item, item.removal_name))
        if item.backup_name is not None:
            recovery_paths.add(_auxiliary_path(item, item.backup_name))
        return tuple(recovery_paths)
    if _metadata_identity(quarantined) != item.artifact_identity:
        item.removal_identity = None
        try:
            os.link(
                item.removal_name,
                item.target_name,
                src_dir_fd=item.parent_fd,
                dst_dir_fd=item.parent_fd,
                follow_symlinks=False,
            )
        except OSError:
            pass
        recovery_paths.add(_auxiliary_path(item, item.removal_name))
        if item.backup_name is not None:
            recovery_paths.add(_auxiliary_path(item, item.backup_name))
        return tuple(recovery_paths)

    item.removal_identity = item.artifact_identity
    if _unlink_owned_name(item, item.removal_name, item.artifact_identity):
        item.removal_name = None
        item.removal_identity = None
    else:
        recovery_paths.add(_auxiliary_path(item, item.removal_name))
    recovery_paths.update(_restore_backup(item))
    return tuple(recovery_paths)


def _renew_removal_placeholder(item: _PreparedArtifact) -> bool:
    token = secrets.token_hex(12)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    for attempt in range(4):
        suffix = token if attempt == 0 else f"{token}-{attempt}"
        name = f".{item.target_name}.raften-{suffix}.rollback"
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=item.parent_fd)
        except FileExistsError:
            continue
        except OSError:
            return False
        try:
            identity = _metadata_identity(os.fstat(descriptor))
            item.removal_name = name
            item.removal_identity = identity
            os.fsync(descriptor)
        except OSError:
            if item.removal_identity is None:
                item.recovery_paths.add(_auxiliary_path(item, name))
            return False
        finally:
            os.close(descriptor)
        return True
    return False


def _restore_backup(item: _PreparedArtifact) -> tuple[str, ...]:
    if item.backup_name is None:
        return ()
    recovery_path = _auxiliary_path(item, item.backup_name)
    if item.target_identity is None or not _name_has_identity(
        item,
        item.backup_name,
        item.target_identity,
    ):
        return (recovery_path,)
    try:
        os.link(
            item.backup_name,
            item.target_name,
            src_dir_fd=item.parent_fd,
            dst_dir_fd=item.parent_fd,
            follow_symlinks=False,
        )
    except OSError:
        return (recovery_path,)
    if not _unlink_owned_name(item, item.backup_name, item.target_identity):
        return (recovery_path,)
    item.backup_name = None
    return ()


def _discard_unused_backup(item: _PreparedArtifact) -> tuple[str, ...]:
    if item.backup_name is None or item.target_identity is None:
        return ()
    recovery_path = _auxiliary_path(item, item.backup_name)
    if _name_has_identity(item, item.target_name, item.target_identity):
        if not _unlink_owned_name(item, item.backup_name, item.target_identity):
            return (recovery_path,)
        item.backup_name = None
        return ()
    if not _name_exists(item, item.target_name):
        return _restore_backup(item)
    else:
        return (recovery_path,)


def _metadata_identity(metadata: os.stat_result) -> _Identity:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
    )


def _name_has_identity(
    item: _PreparedArtifact,
    name: str,
    expected: _Identity,
) -> bool:
    try:
        metadata = os.stat(name, dir_fd=item.parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return _metadata_identity(metadata) == expected


def _name_exists(item: _PreparedArtifact, name: str) -> bool:
    try:
        os.stat(name, dir_fd=item.parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return True


def _unlink_owned_name(
    item: _PreparedArtifact,
    name: str,
    expected: _Identity,
) -> bool:
    return _unlink_owned_at(item.parent_fd, name, expected)


def _unlink_owned_at(
    parent_fd: int,
    name: str,
    expected: _Identity | None,
) -> bool:
    if expected is None:
        return False
    try:
        metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if _metadata_identity(metadata) != expected:
        return False
    try:
        os.unlink(name, dir_fd=parent_fd)
    except OSError:
        return False
    return True


def _auxiliary_path(item: _PreparedArtifact, name: str) -> str:
    return _relative_auxiliary_path(item.parent_components, name)


def _relative_auxiliary_path(components: Sequence[str], name: str) -> str:
    return "/".join((*components, name))


def _remove_backups(prepared: Sequence[_PreparedArtifact]) -> None:
    first_error: OSError | None = None
    for item in prepared:
        if item.backup_name is not None:
            if item.target_identity is not None and _unlink_owned_name(
                item,
                item.backup_name,
                item.target_identity,
            ):
                item.backup_name = None
            else:
                item.recovery_paths.add(_auxiliary_path(item, item.backup_name))
                if first_error is None:
                    first_error = OSError(errno.EBUSY, "rollback backup identity changed")
        if item.removal_name is not None:
            if item.removal_identity is not None and _unlink_owned_name(
                item,
                item.removal_name,
                item.removal_identity,
            ):
                item.removal_name = None
                item.removal_identity = None
            else:
                item.recovery_paths.add(_auxiliary_path(item, item.removal_name))
                if first_error is None:
                    first_error = OSError(errno.EBUSY, "rollback quarantine identity changed")
        try:
            os.fsync(item.parent_fd)
        except OSError as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def _retained_recovery_paths(
    prepared: Sequence[_PreparedArtifact],
) -> tuple[str, ...]:
    recovery_paths: set[str] = set()
    for item in prepared:
        recovery_paths.update(item.recovery_paths)
        names = (item.temporary_name, item.backup_name, item.removal_name)
        for name in names:
            if name is not None and _name_exists(item, name):
                recovery_paths.add(_auxiliary_path(item, name))
    return tuple(sorted(recovery_paths))


def _close_prepared(prepared: Sequence[_PreparedArtifact]) -> None:
    for item in prepared:
        try:
            os.close(item.parent_fd)
        except OSError:
            pass
        try:
            os.close(item.root_fd)
        except OSError:
            pass
