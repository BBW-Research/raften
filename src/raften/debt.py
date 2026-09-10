"""Strict deterministic codec for first-adoption migration debt."""

from __future__ import annotations

import json
import posixpath
import re
from collections.abc import Sequence
from typing import Any, Never

from raften.diagnostics import (
    CFG_DUPLICATE_SELECTOR,
    CFG_MISSING_KEY,
    CFG_PARSE,
    CFG_PATH,
    CFG_TYPE,
    CFG_UNKNOWN_KEY,
    CFG_VALUE,
    config_diagnostic,
    config_diagnostic_sort_key,
)
from raften.config_validation import child_path
from raften.matcher import candidate_path_validation_error, path_validation_error
from raften.model import (
    ContentState,
    Diagnostic,
    FileAssessment,
    FileKind,
    MigrationDebtEntry,
    MigrationDebtManifest,
    WorktreeKind,
)


SCHEMA_VERSION = 1
_ROOT_KEYS = frozenset({"schema_version", "entries"})
_ENTRY_KEYS = frozenset({"path", "size_bytes", "content_identity"})
_CONTENT_IDENTITY = re.compile(r"sha256:[0-9a-f]{64}\Z")


class DebtManifestError(ValueError):
    """One or more deterministic first-adoption manifest diagnostics."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        if not diagnostics:
            raise ValueError("DebtManifestError requires at least one diagnostic")
        self.diagnostics = tuple(sorted(diagnostics, key=config_diagnostic_sort_key))
        first = self.diagnostics[0]
        super().__init__(f"{first.code} {first.field_path}: {first.message}")


class _DuplicateJsonKey(ValueError):
    pass


def capture_debt_manifest(files: Sequence[FileAssessment]) -> MigrationDebtManifest:
    """Capture exact current oversized authored plaintext without broad selectors."""

    entries: list[MigrationDebtEntry] = []
    for assessment in sorted(files, key=lambda item: item.entry.path):
        policy = assessment.policy
        if (
            policy is None
            or assessment.entry.kind is not WorktreeKind.REGULAR
            or policy.kind is not FileKind.AUTHORED
            or not policy.ordinary_scan
            or policy.ordinary_hard_bytes is None
            or assessment.content_state is not ContentState.PLAINTEXT
            or assessment.size_bytes is None
            or assessment.size_bytes <= policy.ordinary_hard_bytes
        ):
            continue
        identity = assessment.content_identity
        if identity is None or _CONTENT_IDENTITY.fullmatch(identity) is None:
            raise ValueError(
                f"oversized assessment {assessment.entry.path!r} has no SHA-256 content identity"
            )
        entries.append(
            MigrationDebtEntry(
                path=assessment.entry.path,
                size_bytes=assessment.size_bytes,
                content_identity=identity,
            )
        )
    return MigrationDebtManifest(SCHEMA_VERSION, tuple(entries))


def render_debt_manifest(manifest: MigrationDebtManifest) -> bytes:
    """Render the single canonical UTF-8/LF representation."""

    _validate_model(manifest)
    value = {
        "schema_version": manifest.schema_version,
        "entries": [
            {
                "path": entry.path,
                "size_bytes": entry.size_bytes,
                "content_identity": entry.content_identity,
            }
            for entry in manifest.entries
        ],
    }
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def parse_debt_manifest(
    data: bytes,
    *,
    source_path: str = "raften.debt.json",
) -> MigrationDebtManifest:
    """Parse a strict JSON sidecar into sorted immutable records."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail(
            CFG_PARSE,
            source_path,
            "$",
            "migration-debt manifest must be valid UTF-8",
            details=(("byte_offset", error.start),),
        )
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as error:
        _fail(
            CFG_PARSE,
            source_path,
            "$",
            f"invalid migration-debt JSON: {error}",
            line=error.lineno,
            column=error.colno,
        )
    except (_DuplicateJsonKey, RecursionError, ValueError) as error:
        _fail(
            CFG_PARSE,
            source_path,
            "$",
            f"invalid migration-debt JSON: {error}",
        )
    if not isinstance(raw, dict):
        _fail(CFG_TYPE, source_path, "$", "manifest root must be a JSON object")
    _require_exact_keys(raw, _ROOT_KEYS, source_path, "$")

    version = raw["schema_version"]
    if not _is_integer(version):
        _fail(CFG_TYPE, source_path, "schema_version", "schema_version must be an integer")
    if version != SCHEMA_VERSION:
        _fail(
            CFG_VALUE,
            source_path,
            "schema_version",
            f"unsupported migration-debt schema version {version}",
            details=(("supported", SCHEMA_VERSION), ("value", version)),
        )
    raw_entries = raw["entries"]
    if not isinstance(raw_entries, list):
        _fail(CFG_TYPE, source_path, "entries", "entries must be a JSON array")

    entries: list[MigrationDebtEntry] = []
    seen: dict[str, int] = {}
    for index, raw_entry in enumerate(raw_entries):
        parent = f"entries[{index}]"
        if not isinstance(raw_entry, dict):
            _fail(CFG_TYPE, source_path, parent, "debt entry must be a JSON object")
        _require_exact_keys(raw_entry, _ENTRY_KEYS, source_path, parent)
        path = raw_entry["path"]
        size = raw_entry["size_bytes"]
        identity = raw_entry["content_identity"]
        if not isinstance(path, str):
            _fail(CFG_TYPE, source_path, f"{parent}.path", "path must be a string")
        path_error = _manifest_entry_path_error(path)
        if path_error is not None:
            _fail(
                CFG_PATH,
                source_path,
                f"{parent}.path",
                path_error,
                details=(("value", path),),
            )
        if path in seen:
            _fail(
                CFG_DUPLICATE_SELECTOR,
                source_path,
                f"{parent}.path",
                "duplicate migration-debt path",
                details=(("first_index", seen[path]), ("path", path)),
            )
        seen[path] = index
        if not _is_integer(size):
            _fail(CFG_TYPE, source_path, f"{parent}.size_bytes", "size_bytes must be an integer")
        if size <= 0:
            _fail(
                CFG_VALUE,
                source_path,
                f"{parent}.size_bytes",
                "size_bytes must be positive",
                details=(("value", size),),
            )
        if not isinstance(identity, str):
            _fail(
                CFG_TYPE,
                source_path,
                f"{parent}.content_identity",
                "content_identity must be a string",
            )
        if _CONTENT_IDENTITY.fullmatch(identity) is None:
            _fail(
                CFG_VALUE,
                source_path,
                f"{parent}.content_identity",
                "content_identity must be sha256 followed by 64 lowercase hexadecimal digits",
                details=(("value", identity),),
            )
        entries.append(MigrationDebtEntry(path, size, identity))
    return MigrationDebtManifest(SCHEMA_VERSION, tuple(sorted(entries, key=lambda item: item.path)))


def debt_manifest_path(config_path: str) -> str:
    """Derive the deterministic sidecar path from a canonical policy path."""

    error = _config_path_error(config_path)
    if error is not None:
        raise ValueError(error)
    directory, filename = posixpath.split(config_path)
    stem = filename[:-5] if filename.endswith(".toml") else filename
    sidecar = f"{stem}.debt.json"
    return sidecar if not directory else f"{directory}/{sidecar}"


def _validate_model(manifest: MigrationDebtManifest) -> None:
    if not _is_integer(manifest.schema_version) or manifest.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported migration-debt schema version {manifest.schema_version}")
    for entry in manifest.entries:
        if not isinstance(entry.path, str) or _manifest_entry_path_error(entry.path) is not None:
            raise ValueError(f"invalid migration-debt path {entry.path!r}")
        if (
            not _is_integer(entry.size_bytes)
            or entry.size_bytes <= 0
            or not isinstance(entry.content_identity, str)
            or _CONTENT_IDENTITY.fullmatch(entry.content_identity) is None
        ):
            raise ValueError(f"invalid migration-debt entry for {entry.path!r}")
    paths = tuple(entry.path for entry in manifest.entries)
    if paths != tuple(sorted(paths)) or len(paths) != len(set(paths)):
        raise ValueError("migration-debt entries must have unique sorted paths")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Never:
    raise ValueError(f"non-finite JSON number {value}")


def _require_exact_keys(
    value: dict[str, Any],
    expected: frozenset[str],
    source_path: str,
    parent: str,
) -> None:
    missing = sorted(expected.difference(value))
    if missing:
        key = missing[0]
        field_path = child_path(parent, key)
        _fail(
            CFG_MISSING_KEY,
            source_path,
            field_path,
            f"missing required key {key!r}",
            details=(("key", key),),
        )
    unknown = sorted(set(value).difference(expected))
    if unknown:
        key = unknown[0]
        field_path = child_path(parent, key)
        _fail(
            CFG_UNKNOWN_KEY,
            source_path,
            field_path,
            f"unknown key {key!r}",
            details=(("key", key),),
        )


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _manifest_entry_path_error(path: str) -> str | None:
    error = candidate_path_validation_error(path)
    if error is not None:
        return error
    return _unicode_scalar_error(path)


def _config_path_error(path: str) -> str | None:
    error = path_validation_error(path)
    if error is not None:
        return error
    return _unicode_scalar_error(path)


def _unicode_scalar_error(path: str) -> str | None:
    try:
        path.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return "path must contain only Unicode scalar values"
    return None


def _fail(
    code: str,
    source_path: str,
    field_path: str,
    message: str,
    *,
    details=(),
    line: int | None = None,
    column: int | None = None,
) -> Never:
    raise DebtManifestError(
        (
            config_diagnostic(
                code,
                source_path,
                field_path,
                message,
                line=line,
                column=column,
                details=details,
            ),
        )
    )
