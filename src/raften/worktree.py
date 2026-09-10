"""No-follow worktree path joining and metadata inspection."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from pathlib import Path
from typing import Never

from raften.diagnostics import GIT_FILESYSTEM, GIT_PATH_CHANGED
from raften.git_records import validate_git_repository_path
from raften.model import (
    GitIndexMetadata,
    InventoryEntry,
    InventorySource,
    RepositoryPath,
    WorktreeIdentity,
    WorktreeKind,
)
from raften.repository_errors import fail_repository


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
    allow_missing: bool = False,
) -> InventoryEntry:
    target = join_worktree_path(root, path)
    missing_allowed = allow_missing or listed_deleted or (
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
            identity=_identity(status),
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


def read_regular_bytes(root: Path, entry: InventoryEntry) -> bytes:
    """Read one inventoried regular file without accepting path replacement."""

    if entry.kind is not WorktreeKind.REGULAR:
        raise ValueError("worktree content reads require a regular inventory entry")
    if entry.identity is None:
        raise ValueError("regular inventory entry lacks snapshot identity")
    _require_current_identity(root, entry, "content-lstat")
    try:
        descriptor = _open_snapshot_file(root, entry.path)
    except OSError as error:
        _require_current_identity(root, entry, "content-open-recheck")
        if _is_path_change_error(error):
            _path_changed(entry.path, entry.source, "path changed before content open")
        _filesystem_error(entry.path, "open", error)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _identity(before) != entry.identity:
            _path_changed(entry.path, entry.source, "path identity changed before content read")
        data = _read_descriptor(descriptor, entry.identity.size_bytes)
        after = os.fstat(descriptor)
        if _identity(after) != entry.identity or len(data) != entry.identity.size_bytes:
            _path_changed(entry.path, entry.source, "file changed during content read")
        _require_current_identity(root, entry, "content-post-lstat")
        return data
    except OSError as error:
        _filesystem_error(entry.path, "read", error)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def hash_regular_blob(root: Path, entry: InventoryEntry, algorithm: str) -> str:
    """Hash one regular snapshot as a Git blob without retaining its bytes."""

    if entry.kind is not WorktreeKind.REGULAR:
        raise ValueError("worktree blob hashes require a regular inventory entry")
    if entry.identity is None:
        raise ValueError("regular inventory entry lacks snapshot identity")
    _require_current_identity(root, entry, "hash-lstat")
    try:
        descriptor = _open_snapshot_file(root, entry.path)
    except OSError as error:
        _require_current_identity(root, entry, "hash-open-recheck")
        if _is_path_change_error(error):
            _path_changed(entry.path, entry.source, "path changed before content hash")
        _filesystem_error(entry.path, "hash-open", error)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _identity(before) != entry.identity:
            _path_changed(entry.path, entry.source, "path identity changed before content hash")
        digest, observed_size = _hash_descriptor(
            descriptor,
            entry.identity.size_bytes,
            algorithm,
        )
        after = os.fstat(descriptor)
        if _identity(after) != entry.identity or observed_size != entry.identity.size_bytes:
            _path_changed(entry.path, entry.source, "file changed during content hash")
        _require_current_identity(root, entry, "hash-post-lstat")
        return digest
    except OSError as error:
        _filesystem_error(entry.path, "hash", error)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


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


def _identity(status: os.stat_result) -> WorktreeIdentity:
    return WorktreeIdentity(
        mode=status.st_mode,
        device=status.st_dev,
        inode=status.st_ino,
        size_bytes=status.st_size,
        modified_ns=status.st_mtime_ns,
        changed_ns=status.st_ctime_ns,
    )


def _require_current_identity(
    root: Path,
    entry: InventoryEntry,
    operation: str,
) -> None:
    target = join_worktree_path(root, entry.path)
    _inspect_parent_chain(root, entry.path, entry.source, False)
    try:
        status = _lstat(target)
    except (FileNotFoundError, NotADirectoryError):
        _path_changed(entry.path, entry.source, "path disappeared before content read completed")
    except OSError as error:
        _filesystem_error(entry.path, operation, error)
    if not stat.S_ISREG(status.st_mode) or _identity(status) != entry.identity:
        _path_changed(entry.path, entry.source, "path identity changed before content read completed")


def _open_snapshot_file(root: Path, path: str) -> int:
    components = path.split("/")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    nonblocking = getattr(os, "O_NONBLOCK", 0)
    if os.open in os.supports_dir_fd and no_follow and directory:
        directory_flags = os.O_RDONLY | close_on_exec | no_follow | directory
        current = os.open(root, directory_flags)
        try:
            for component in components[:-1]:
                following = os.open(component, directory_flags, dir_fd=current)
                os.close(current)
                current = following
            return os.open(
                components[-1],
                os.O_RDONLY | close_on_exec | no_follow | nonblocking,
                dir_fd=current,
            )
        finally:
            os.close(current)
    raise OSError(
        getattr(errno, "ENOTSUP", errno.ENOSYS),
        "secure descriptor-relative no-follow opens are unavailable",
    )


def _read_descriptor(descriptor: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = expected_size + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _hash_descriptor(
    descriptor: int,
    expected_size: int,
    algorithm: str,
) -> tuple[str, int]:
    digest = hashlib.new(algorithm)
    digest.update(f"blob {expected_size}\0".encode("ascii"))
    observed_size = 0
    remaining = expected_size + 1
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            break
        digest.update(chunk)
        observed_size += len(chunk)
        remaining -= len(chunk)
    return digest.hexdigest(), observed_size


def _is_path_change_error(error: OSError) -> bool:
    return error.errno in {
        errno.ENOENT,
        errno.ENOTDIR,
        errno.ELOOP,
        errno.EISDIR,
    }


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
