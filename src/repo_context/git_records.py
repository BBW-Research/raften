"""Pure decoding and validation for NUL-delimited Git records."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Sequence

from repo_context.diagnostics import GIT_UNMERGED_INDEX, GIT_UNSAFE_PATH
from repo_context.matcher import candidate_path_validation_error
from repo_context.model import (
    BaseTreeEntry,
    GitFileMode,
    GitIndexMetadata,
    GitObjectType,
    RepositoryPath,
)
from repo_context.repository_errors import fail_repository, malformed_git_output


_OBJECT_ID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def parse_index_entries(output: bytes) -> dict[str, GitIndexMetadata]:
    entries: dict[str, GitIndexMetadata] = {}
    for record_index, record in enumerate(_split_nul_records(output, "list-index")):
        try:
            header, raw_path = record.split(b"\t", 1)
            raw_tag, raw_mode, raw_object_id, raw_stage = header.split(b" ")
        except ValueError:
            malformed_git_output(
                "list-index",
                "Git returned a malformed index record",
                record_index=record_index,
            )
        mode = _decode_mode(raw_mode, "list-index", record_index)
        object_id = decode_object_id(
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
            fail_repository(
                GIT_UNMERGED_INDEX,
                "unmerged index stages are unsupported",
                path=path,
                details=(("stage", int(raw_stage)),),
            )
        if raw_stage != b"0":
            malformed_git_output(
                "list-index",
                "Git returned an invalid index stage",
                record_index=record_index,
            )
        if raw_tag not in {b"H", b"S"}:
            malformed_git_output(
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
            malformed_git_output(
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


def parse_path_records(output: bytes, *, operation: str) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for record_index, record in enumerate(_split_nul_records(output, operation)):
        path = decode_git_path(record, operation=operation, index=record_index)
        if path in seen:
            malformed_git_output(
                operation,
                "Git returned a duplicate path",
                path=path,
                record_index=record_index,
            )
        seen.add(path)
        paths.append(path)
    return tuple(paths)


def parse_base_tree(output: bytes) -> tuple[BaseTreeEntry, ...]:
    entries: dict[str, BaseTreeEntry] = {}
    for record_index, record in enumerate(_split_nul_records(output, "list-base-tree")):
        try:
            header, raw_path = record.split(b"\t", 1)
            raw_mode, raw_type, raw_object_id = header.split(b" ")
        except ValueError:
            malformed_git_output(
                "list-base-tree",
                "Git returned a malformed base-tree record",
                record_index=record_index,
            )
        mode = _decode_mode(raw_mode, "list-base-tree", record_index)
        object_type = _decode_object_type(raw_type, "list-base-tree", record_index)
        object_id = decode_object_id(
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
            malformed_git_output(
                "list-base-tree",
                "Git returned a duplicate base-tree path",
                path=path,
                record_index=record_index,
            )
        entries[path] = BaseTreeEntry(path, mode, object_type, object_id)
    return tuple(entries[path] for path in sorted(entries))


def decode_git_path(record: bytes, *, operation: str, index: int) -> str:
    """Strictly decode and structurally validate one NUL-framed Git path."""

    try:
        path = record.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        malformed_git_output(
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
        fail_repository(
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


def decode_object_id(raw: bytes, *, operation: str, record_index: int) -> str:
    try:
        object_id = raw.decode("ascii")
    except UnicodeDecodeError:
        malformed_git_output(
            operation,
            "Git returned a non-ASCII object identity",
            record_index=record_index,
        )
    require_object_id(
        object_id,
        operation=operation,
        record_index=record_index,
    )
    return object_id


def require_object_id(
    object_id: str,
    *,
    operation: str,
    record_index: int | None = None,
) -> None:
    if _OBJECT_ID.fullmatch(object_id) is None:
        malformed_git_output(
            operation,
            "Git returned an invalid object identity",
            record_index=record_index,
        )


def _split_nul_records(output: bytes, operation: str) -> tuple[bytes, ...]:
    if not output:
        return ()
    if not output.endswith(b"\x00"):
        malformed_git_output(operation, "Git output is not NUL terminated")
    records = tuple(output[:-1].split(b"\x00"))
    if any(not record for record in records):
        malformed_git_output(operation, "Git output contains an empty NUL record")
    return records


def _decode_mode(raw: bytes, operation: str, record_index: int) -> GitFileMode:
    try:
        return GitFileMode(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError):
        malformed_git_output(
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
        malformed_git_output(
            operation,
            "Git returned an unsupported object type",
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
        malformed_git_output(
            "list-base-tree",
            "Git returned an inconsistent file mode and object type",
            record_index=record_index,
        )
