"""Deterministic Git-visible repository inventory and base-object access."""

from __future__ import annotations

import errno
import hashlib
import os
import re
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Never

from repo_context.diagnostics import (
    GIT_BASE_OBJECT,
    GIT_BASE_REVISION,
    GIT_COMMAND,
    GIT_FILESYSTEM,
    GIT_INVALID_ROOT,
    GIT_MALFORMED_OUTPUT,
    GIT_PATH_CHANGED,
    GIT_UNMERGED_INDEX,
    GIT_UNSAFE_PATH,
    diagnostic_sort_key,
    operational_diagnostic,
)
from repo_context.git_executable import resolve_git_executable
from repo_context.matcher import candidate_path_validation_error
from repo_context.model import (
    BaseRevision,
    BaseTreeEntry,
    Diagnostic,
    GitFileMode,
    GitIndexMetadata,
    GitObjectType,
    InventoryEntry,
    InventorySource,
    JsonValue,
    RepositoryPath,
    WorktreeKind,
)


GIT_TIMEOUT_SECONDS = 120
_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


@dataclass(frozen=True, slots=True)
class RepositoryHandle:
    root: Path


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    repository: RepositoryHandle
    entries: tuple[InventoryEntry, ...]


class RepositoryAccessError(RuntimeError):
    """A deterministic repository-boundary failure with structured diagnostics."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = tuple(sorted(diagnostics, key=diagnostic_sort_key))
        super().__init__("; ".join(item.message for item in self.diagnostics))


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
                repository,
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
    entries: dict[str, BaseTreeEntry] = {}
    for record_index, record in enumerate(_split_nul_records(output, "list-base-tree")):
        try:
            header, raw_path = record.split(b"\t", 1)
            raw_mode, raw_type, raw_object_id = header.split(b" ")
        except ValueError:
            _malformed(
                "list-base-tree",
                "Git returned a malformed base-tree record",
                record_index=record_index,
            )
        mode = _decode_mode(raw_mode, "list-base-tree", record_index)
        object_type = _decode_object_type(raw_type, "list-base-tree", record_index)
        object_id = _decode_object_id(
            raw_object_id,
            operation="list-base-tree",
            record_index=record_index,
        )
        path = decode_git_path(
            raw_path,
            operation="list-base-tree",
            index=record_index,
        )
        _require_mode_type_pair(mode, object_type, record_index)
        if path in entries:
            _malformed(
                "list-base-tree",
                "Git returned a duplicate base-tree path",
                path=path,
                record_index=record_index,
            )
        entries[path] = BaseTreeEntry(path, mode, object_type, object_id)
    return tuple(entries[path] for path in sorted(entries))


def find_base_entry(
    entries: Sequence[BaseTreeEntry],
    path: RepositoryPath,
) -> BaseTreeEntry | None:
    """Find one exact path in an already materialized base-tree snapshot."""

    error = validate_git_repository_path(path)
    if error is not None:
        raise ValueError(error)
    lower = 0
    upper = len(entries)
    while lower < upper:
        middle = (lower + upper) // 2
        candidate = entries[middle]
        if candidate.path < path:
            lower = middle + 1
        else:
            upper = middle
    if lower < len(entries) and entries[lower].path == path:
        return entries[lower]
    return None


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


def decode_git_path(record: bytes, *, operation: str, index: int) -> str:
    """Strictly decode and structurally validate one NUL-framed Git path."""

    try:
        path = record.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        _malformed(
            operation,
            "Git returned a path that is not UTF-8",
            record_index=index,
            extra_details=(
                ("byte_offset", error.start),
                ("record_sha256", hashlib.sha256(record).hexdigest()),
            ),
        )
    validation_error = validate_git_repository_path(path)
    if validation_error is not None:
        _fail(
            GIT_UNSAFE_PATH,
            "Git returned an unsafe or noncanonical repository path",
            details=(
                ("operation", operation),
                ("record_index", index),
                ("reason", validation_error),
                ("path", path),
            ),
        )
    return path


def validate_git_repository_path(path: str) -> str | None:
    """Validate Git's POSIX path spelling without interpreting filename globs."""

    error = candidate_path_validation_error(path)
    if error is not None:
        return error
    if os.name == "nt" and "\\" in path:
        return "Git paths must use POSIX separators on Windows"
    return None


def worktree_path(repository: RepositoryHandle, path: RepositoryPath) -> Path:
    """Join one validated Git path without resolving or following its leaf."""

    error = validate_git_repository_path(path)
    if error is not None:
        raise ValueError(error)
    candidate = repository.root.joinpath(*path.split("/"))
    if not candidate.is_relative_to(repository.root):
        raise ValueError("path escapes the repository root during platform joining")
    return candidate


def _parse_index_entries(output: bytes) -> dict[str, GitIndexMetadata]:
    entries: dict[str, GitIndexMetadata] = {}
    for record_index, record in enumerate(_split_nul_records(output, "list-index")):
        try:
            header, raw_path = record.split(b"\t", 1)
            raw_tag, raw_mode, raw_object_id, raw_stage = header.split(b" ")
        except ValueError:
            _malformed(
                "list-index",
                "Git returned a malformed index record",
                record_index=record_index,
            )
        mode = _decode_mode(raw_mode, "list-index", record_index)
        object_id = _decode_object_id(
            raw_object_id,
            operation="list-index",
            record_index=record_index,
        )
        if raw_stage in {b"1", b"2", b"3"}:
            path = decode_git_path(
                raw_path,
                operation="list-index",
                index=record_index,
            )
            _fail(
                GIT_UNMERGED_INDEX,
                "unmerged index stages are unsupported",
                path=path,
                details=(("stage", int(raw_stage)),),
            )
        if raw_stage != b"0":
            _malformed(
                "list-index",
                "Git returned an invalid index stage",
                record_index=record_index,
            )
        if raw_tag not in {b"H", b"S"}:
            _malformed(
                "list-index",
                "Git returned an unsupported index status tag",
                record_index=record_index,
            )
        path = decode_git_path(
            raw_path,
            operation="list-index",
            index=record_index,
        )
        if path in entries:
            _malformed(
                "list-index",
                "Git returned a duplicate index path",
                path=path,
                record_index=record_index,
            )
        entries[path] = GitIndexMetadata(
            mode=mode,
            object_id=object_id,
            skip_worktree=raw_tag == b"S",
        )
    return entries


def _parse_path_records(output: bytes, *, operation: str) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for record_index, record in enumerate(_split_nul_records(output, operation)):
        path = decode_git_path(record, operation=operation, index=record_index)
        if path in seen:
            _malformed(
                operation,
                "Git returned a duplicate path",
                path=path,
                record_index=record_index,
            )
        seen.add(path)
        paths.append(path)
    return tuple(paths)


def _split_nul_records(output: bytes, operation: str) -> tuple[bytes, ...]:
    if not output:
        return ()
    if not output.endswith(b"\x00"):
        _malformed(operation, "Git output is not NUL terminated")
    records = tuple(output[:-1].split(b"\x00"))
    if any(not record for record in records):
        _malformed(operation, "Git output contains an empty NUL record")
    return records


def _inspect_worktree_entry(
    repository: RepositoryHandle,
    path: str,
    *,
    source: InventorySource,
    index: GitIndexMetadata | None,
    listed_deleted: bool,
) -> InventoryEntry:
    target = worktree_path(repository, path)
    missing_allowed = listed_deleted or (
        index is not None and index.skip_worktree
    )
    parents_present = _inspect_parent_chain(
        repository,
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
    repository: RepositoryHandle,
    path: str,
    source: InventorySource,
    missing_allowed: bool,
) -> bool:
    current = repository.root
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


def _decode_mode(raw: bytes, operation: str, record_index: int) -> GitFileMode:
    try:
        return GitFileMode(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        _malformed(
            operation,
            "Git returned an unsupported file mode",
            record_index=record_index,
        )


def _decode_object_type(
    raw: bytes,
    operation: str,
    record_index: int,
) -> GitObjectType:
    try:
        return GitObjectType(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        _malformed(
            operation,
            "Git returned an unsupported object type",
            record_index=record_index,
        )


def _decode_object_id(raw: bytes, *, operation: str, record_index: int) -> str:
    try:
        object_id = raw.decode("ascii")
    except UnicodeDecodeError:
        _malformed(
            operation,
            "Git returned a non-ASCII object identity",
            record_index=record_index,
        )
    _require_object_id(
        object_id,
        operation=operation,
        record_index=record_index,
    )
    return object_id


def _require_object_id(
    object_id: str,
    *,
    operation: str,
    record_index: int | None = None,
) -> None:
    if _OBJECT_ID.fullmatch(object_id) is None:
        _malformed(
            operation,
            "Git returned an invalid object identity",
            record_index=record_index,
        )


def _require_mode_type_pair(
    mode: GitFileMode,
    object_type: GitObjectType,
    record_index: int,
) -> None:
    expected = (
        GitObjectType.COMMIT
        if mode is GitFileMode.GITLINK
        else GitObjectType.BLOB
    )
    if object_type is not expected:
        _malformed(
            "list-base-tree",
            "Git returned an inconsistent file mode and object type",
            record_index=record_index,
        )


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


def _path_changed(path: str, source: InventorySource, message: str) -> Never:
    _fail(
        GIT_PATH_CHANGED,
        message,
        path=path,
        details=(("listed_source", source.value),),
    )


def _filesystem_error(path: str, operation: str, error: OSError) -> Never:
    _fail(
        GIT_FILESYSTEM,
        "filesystem inspection failed",
        path=path,
        details=(
            ("operation", operation),
            ("error_type", type(error).__name__),
        ),
    )


def _malformed(
    operation: str,
    message: str,
    *,
    path: str | None = None,
    record_index: int | None = None,
    extra_details: tuple[tuple[str, JsonValue], ...] = (),
) -> Never:
    details: list[tuple[str, JsonValue]] = [("operation", operation)]
    if record_index is not None:
        details.append(("record_index", record_index))
    details.extend(extra_details)
    _fail(
        GIT_MALFORMED_OUTPUT,
        message,
        path=path,
        details=tuple(details),
    )


def _fail(
    code: str,
    message: str,
    *,
    path: str | None = None,
    details: tuple[tuple[str, JsonValue], ...] = (),
) -> Never:
    raise RepositoryAccessError(
        (
            operational_diagnostic(
                code,
                message,
                path=path,
                details=details,
            ),
        )
    )
