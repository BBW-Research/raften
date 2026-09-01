"""Deterministic Git-visible repository inventory and base-object access."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repo_context.diagnostics import (
    GIT_BASE_OBJECT,
    GIT_BASE_REVISION,
    GIT_COMMAND,
    GIT_INVALID_ROOT,
)
from repo_context.git_executable import resolve_git_executable
from repo_context.git_records import (
    decode_git_path,
    decode_object_id as _decode_object_id,
    find_base_entry,
    parse_base_tree as _parse_base_tree,
    parse_index_entries as _parse_index_entries,
    parse_path_records as _parse_path_records,
    require_object_id as _require_object_id,
    validate_git_repository_path,
)
from repo_context.model import (
    BaseRevision,
    BaseTreeEntry,
    GitObjectType,
    InventoryEntry,
    InventorySource,
    RepositoryPath,
)
from repo_context.repository_errors import (
    RepositoryAccessError,
    fail_repository as _fail,
    malformed_git_output as _malformed,
)
from repo_context.worktree import (
    inspect_worktree_entry as _inspect_worktree_entry,
    join_worktree_path,
    read_regular_bytes as _read_regular_bytes,
)


__all__ = (
    "InventorySnapshot",
    "RepositoryAccessError",
    "RepositoryHandle",
    "decode_git_path",
    "find_base_entry",
    "inventory_worktree",
    "list_base_tree",
    "open_repository",
    "read_base_blob",
    "read_worktree_bytes",
    "resolve_base_revision",
    "validate_git_repository_path",
    "worktree_path",
)


GIT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True, slots=True)
class RepositoryHandle:
    root: Path


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    repository: RepositoryHandle
    entries: tuple[InventoryEntry, ...]


def open_repository(candidate: str | os.PathLike[str]) -> RepositoryHandle:
    """Validate and canonicalize one explicitly selected Git worktree root."""

    supplied = os.fspath(candidate)
    if not supplied:
        _fail(
            GIT_INVALID_ROOT,
            "repository root must not be empty",
            details=(("root", str(supplied)),),
        )
    try:
        root = Path(supplied).resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as error:
        _fail(
            GIT_INVALID_ROOT,
            "repository root does not exist or cannot be resolved",
            details=(
                ("root", str(supplied)),
                ("error_type", type(error).__name__),
            ),
        )
    if not root.is_dir():
        _fail(
            GIT_INVALID_ROOT,
            "repository root is not a directory",
            details=(("root", str(supplied)),),
        )
    output = _run_git(
        root,
        operation="validate-root",
        arguments=("rev-parse", "--is-inside-work-tree", "--show-prefix"),
        failure_code=GIT_INVALID_ROOT,
        failure_message="repository root is not an accessible Git worktree",
    )
    if output not in {b"true\n\n", b"true\r\n\r\n"}:
        _fail(
            GIT_INVALID_ROOT,
            "repository root must be the exact top level of a non-bare Git worktree",
            details=(("root", str(supplied)),),
        )
    return RepositoryHandle(root=root)


def inventory_worktree(repository: RepositoryHandle) -> InventorySnapshot:
    """Return a sorted snapshot of tracked and non-ignored untracked paths."""

    tracked = _parse_index_entries(
        _run_git(
            repository.root,
            operation="list-index",
            arguments=("ls-files", "--stage", "-t", "-z"),
        )
    )
    deleted = set(
        _parse_path_records(
            _run_git(
                repository.root,
                operation="list-deleted",
                arguments=("ls-files", "--deleted", "-z"),
            ),
            operation="list-deleted",
        )
    )
    untracked = _parse_path_records(
        _run_git(
            repository.root,
            operation="list-untracked",
            arguments=("ls-files", "--others", "--exclude-standard", "-z"),
        ),
        operation="list-untracked",
    )
    unknown_deleted = deleted.difference(tracked)
    if unknown_deleted:
        _malformed(
            "list-deleted",
            "Git reported a deleted path that is absent from the index",
            path=min(unknown_deleted),
        )
    overlap = set(tracked).intersection(untracked)
    if overlap:
        _malformed(
            "inventory",
            "Git reported the same path as both tracked and untracked",
            path=min(overlap),
        )

    entries: list[InventoryEntry] = []
    for path in sorted(set(tracked).union(untracked)):
        if path in tracked:
            source = InventorySource.TRACKED
            metadata = tracked[path]
            listed_deleted = path in deleted
        else:
            source = InventorySource.UNTRACKED
            metadata = None
            listed_deleted = False
        entries.append(
            _inspect_worktree_entry(
                repository.root,
                path,
                source=source,
                index=metadata,
                listed_deleted=listed_deleted,
            )
        )
    return InventorySnapshot(
        repository=repository,
        entries=tuple(sorted(entries, key=lambda item: item.path)),
    )


def resolve_base_revision(repository: RepositoryHandle, ref: str) -> BaseRevision:
    """Resolve a requested ref to an immutable commit identity."""

    if not ref or "\x00" in ref:
        _fail(
            GIT_BASE_REVISION,
            "base revision must be a nonempty Git ref without NUL",
            details=(("requested_ref", ref),),
        )
    output = _run_git(
        repository.root,
        operation="resolve-base-revision",
        arguments=("rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"),
        failure_code=GIT_BASE_REVISION,
        failure_message="base revision does not resolve to an available commit",
    )
    lines = output.splitlines()
    if len(lines) != 1 or not output.endswith(b"\n"):
        _malformed(
            "resolve-base-revision",
            "Git returned malformed base-revision output",
        )
    commit_id = _decode_object_id(
        lines[0],
        operation="resolve-base-revision",
        record_index=0,
    )
    return BaseRevision(requested_ref=ref, commit_id=commit_id)


def list_base_tree(
    repository: RepositoryHandle,
    revision: BaseRevision,
) -> tuple[BaseTreeEntry, ...]:
    """List base-tree blobs and gitlinks without touching the worktree or index."""

    _require_object_id(revision.commit_id, operation="list-base-tree")
    output = _run_git(
        repository.root,
        operation="list-base-tree",
        arguments=("ls-tree", "-r", "-z", "--full-tree", revision.commit_id),
        failure_code=GIT_BASE_OBJECT,
        failure_message="base tree is unavailable",
    )
    return _parse_base_tree(output)


def read_base_blob(
    repository: RepositoryHandle,
    entry: BaseTreeEntry,
) -> bytes:
    """Read exact base blob bytes by object identity, never by revision:path syntax."""

    if entry.object_type is not GitObjectType.BLOB:
        _fail(
            GIT_BASE_OBJECT,
            "base entry is not a blob",
            path=entry.path,
            details=(
                ("object_id", entry.object_id),
                ("object_type", entry.object_type.value),
            ),
        )
    _require_object_id(entry.object_id, operation="read-base-blob")
    return _run_git(
        repository.root,
        operation="read-base-blob",
        arguments=("cat-file", "blob", entry.object_id),
        failure_code=GIT_BASE_OBJECT,
        failure_message="base blob is unavailable or has the wrong type",
    )


def read_worktree_bytes(
    repository: RepositoryHandle,
    entry: InventoryEntry,
) -> bytes:
    """Read exact bytes for one regular entry from its inventory snapshot."""

    return _read_regular_bytes(repository.root, entry)


def worktree_path(repository: RepositoryHandle, path: RepositoryPath) -> Path:
    """Join one validated Git path without resolving or following its leaf."""

    return join_worktree_path(repository.root, path)


def _run_git(
    root: Path,
    *,
    operation: str,
    arguments: tuple[str, ...],
    failure_code: str = GIT_COMMAND,
    failure_message: str = "Git command failed",
) -> bytes:
    try:
        git_executable, safe_path = resolve_git_executable(root)
    except (OSError, RuntimeError, ValueError) as error:
        _fail(
            GIT_COMMAND,
            "trusted Git executable could not be resolved",
            details=(
                ("operation", operation),
                ("error_type", type(error).__name__),
            ),
        )
    command = [
        git_executable,
        "-c",
        f"core.excludesFile={os.devnull}",
        "-c",
        f"core.fsmonitor={os.devnull}",
        "-c",
        f"core.hooksPath={os.devnull}",
        "-c",
        "core.untrackedCache=false",
        *arguments,
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(safe_path),
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        _fail(
            GIT_COMMAND,
            "Git command could not be executed",
            details=(
                ("operation", operation),
                ("error_type", type(error).__name__),
            ),
        )
    if completed.returncode != 0:
        _fail(
            failure_code,
            failure_message,
            details=(
                ("operation", operation),
                ("return_code", completed.returncode),
            ),
        )
    return completed.stdout


def _git_environment(safe_path: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "NoDefaultCurrentDirectoryInExePath": "1",
            "PATH": safe_path,
        }
    )
    return environment
