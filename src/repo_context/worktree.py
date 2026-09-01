"""No-follow worktree path joining and metadata inspection."""

from __future__ import annotations

import errno
import os
import stat
from pathlib import Path
from typing import Never

from repo_context.diagnostics import GIT_FILESYSTEM, GIT_PATH_CHANGED
from repo_context.git_records import validate_git_repository_path
from repo_context.model import (
    GitIndexMetadata,
    InventoryEntry,
    InventorySource,
    RepositoryPath,
    WorktreeKind,
)
from repo_context.repository_errors import fail_repository


def join_worktree_path(root: Path, path: RepositoryPath) -> Path:
    """Join one validated Git path without resolving or following its leaf."""

    error = validate_git_repository_path(path)
    if error is not None:
        raise ValueError(error)
    candidate = root.joinpath(*path.split("/"))
    if not candidate.is_relative_to(root):
        raise ValueError("path escapes the repository root during platform joining")
    return candidate


def inspect_worktree_entry(
    root: Path,
    path: str,
    *,
    source: InventorySource,
    index: GitIndexMetadata | None,
    listed_deleted: bool,
) -> InventoryEntry:
    target = join_worktree_path(root, path)
    missing_allowed = listed_deleted or (
        index is not None and index.skip_worktree
    )
    parents_present = _inspect_parent_chain(
        root,
        path,
        source,
        missing_allowed,
    )
    if not parents_present:
        return _missing_entry(path, source, index, listed_deleted)
    try:
        status = _lstat(target)
    except FileNotFoundError:
        if missing_allowed:
            return _missing_entry(path, source, index, listed_deleted)
        _path_changed(path, source, "path disappeared after Git inventory")
    except OSError as error:
        _filesystem_error(path, "lstat", error)
    if listed_deleted:
        _path_changed(path, source, "path appeared after Git deletion inventory")

    if stat.S_ISREG(status.st_mode):
        return InventoryEntry(
            path=path,
            source=source,
            kind=WorktreeKind.REGULAR,
            size_bytes=status.st_size,
            index=index,
        )
    if stat.S_ISLNK(status.st_mode):
        try:
            symlink_target = os.readlink(target)
        except (FileNotFoundError, NotADirectoryError):
            _path_changed(path, source, "symlink changed while its target was inspected")
        except OSError as error:
            if error.errno == errno.EINVAL or getattr(error, "winerror", None) == 4390:
                _path_changed(path, source, "symlink changed while its target was inspected")
            _filesystem_error(path, "readlink", error)
        return InventoryEntry(
            path=path,
            source=source,
            kind=WorktreeKind.SYMLINK,
            symlink_target=symlink_target,
            index=index,
        )
    return InventoryEntry(
        path=path,
        source=source,
        kind=WorktreeKind.OTHER,
        index=index,
    )


def _inspect_parent_chain(
    root: Path,
    path: str,
    source: InventorySource,
    missing_allowed: bool,
) -> bool:
    current = root
    for component in path.split("/")[:-1]:
        current = current / component
        try:
            parent_status = _lstat(current)
        except FileNotFoundError:
            if missing_allowed:
                return False
            _path_changed(path, source, "parent directory disappeared")
        except OSError as error:
            _filesystem_error(path, "parent-lstat", error)
        if stat.S_ISLNK(parent_status.st_mode) or _is_junction(current):
            _path_changed(path, source, "intermediate path is a symlink or junction")
        if not stat.S_ISDIR(parent_status.st_mode):
            _path_changed(path, source, "intermediate path is not a directory")
    return True


def _missing_entry(
    path: str,
    source: InventorySource,
    index: GitIndexMetadata | None,
    listed_deleted: bool,
) -> InventoryEntry:
    return InventoryEntry(
        path=path,
        source=InventorySource.DELETED if listed_deleted else source,
        kind=WorktreeKind.MISSING,
        index=index,
    )


def _lstat(path: Path) -> os.stat_result:
    return path.lstat()


def _is_junction(path: Path) -> bool:
    return path.is_junction()


def _path_changed(path: str, source: InventorySource, message: str) -> Never:
    fail_repository(
        GIT_PATH_CHANGED,
        message,
        path=path,
        details=(("listed_source", source.value),),
    )


def _filesystem_error(path: str, operation: str, error: OSError) -> Never:
    fail_repository(
        GIT_FILESYSTEM,
        "filesystem inspection failed",
        path=path,
        details=(
            ("operation", operation),
            ("error_type", type(error).__name__),
        ),
    )
