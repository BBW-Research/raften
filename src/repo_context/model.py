"""Immutable domain records shared across repository policy phases."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TypeAlias


RepositoryPath: TypeAlias = str
RepositoryPattern: TypeAlias = str
JsonValue: TypeAlias = (
    None
    | bool
    | int
    | float
    | str
    | tuple["JsonValue", ...]
    | tuple[tuple[str, "JsonValue"], ...]
)


class OutputFormat(StrEnum):
    TEXT = "text"
    JSON = "json"
    SARIF = "sarif"


class FileKind(StrEnum):
    AUTHORED = "authored"
    GENERATED = "generated"
    VENDORED = "vendored"
    FIXTURE = "fixture"
    LEGAL = "legal"


class InventoryMode(StrEnum):
    GIT_VISIBLE = "git-visible"


class TextEncoding(StrEnum):
    UTF8 = "utf-8"


class InventorySource(StrEnum):
    TRACKED = "tracked"
    UNTRACKED = "untracked"
    DELETED = "deleted"


class WorktreeKind(StrEnum):
    REGULAR = "regular"
    SYMLINK = "symlink"
    MISSING = "missing"
    OTHER = "other"


class GitFileMode(StrEnum):
    REGULAR = "100644"
    EXECUTABLE = "100755"
    SYMLINK = "120000"
    GITLINK = "160000"


class GitObjectType(StrEnum):
    BLOB = "blob"
    TREE = "tree"
    COMMIT = "commit"


class LinkKind(StrEnum):
    NAVIGATION = "navigation"
    IMAGE = "image"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    NOTE = "note"


class RunStatus(StrEnum):
    COMPLETE = "complete"
    CONFIGURATION_ERROR = "configuration_error"
    OPERATIONAL_ERROR = "operational_error"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class ExactSelector:
    path: RepositoryPath


@dataclass(frozen=True, slots=True)
class PatternSelector:
    pattern: RepositoryPattern


Selector: TypeAlias = ExactSelector | PatternSelector


@dataclass(frozen=True, slots=True)
class RepositorySettings:
    inventory: InventoryMode
    encoding: TextEncoding
    follow_symlinks: bool


@dataclass(frozen=True, slots=True)
class OutputSettings:
    default_format: OutputFormat
    stable_sort: bool


@dataclass(frozen=True, slots=True)
class FileRule:
    name: str
    patterns: tuple[RepositoryPattern, ...]
    kind: FileKind
    scan: bool
    warn_bytes: int | None
    hard_bytes: int | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PathOverride:
    selector: Selector
    warn_bytes: int
    hard_bytes: int


@dataclass(frozen=True, slots=True)
class DocumentationSettings:
    roots: tuple[RepositoryPath, ...]
    exclude: tuple[RepositoryPattern, ...]
    require_directory_indexes: bool
    require_sibling_links: bool
    require_child_index_links: bool
    require_root_reachability: bool
    check_local_targets: bool
    check_fragments: bool
    allow_authored_symlinks: bool


@dataclass(frozen=True, slots=True)
class Entrypoint:
    path: RepositoryPath
    required_targets: tuple[RepositoryPath, ...]


@dataclass(frozen=True, slots=True)
class ContextSet:
    name: str
    paths: tuple[RepositoryPath, ...]
    patterns: tuple[RepositoryPattern, ...]
    warn_bytes: int
    hard_bytes: int


@dataclass(frozen=True, slots=True)
class RatchetSettings:
    compare_file_sizes: bool
    forbid_new_oversize: bool
    forbid_limit_increases: bool
    forbid_exclusion_expansion: bool
    forbid_removed_documentation_roots: bool
    forbid_removed_entrypoint_targets: bool


@dataclass(frozen=True, slots=True)
class IntentionalException:
    selector: Selector
    owner: str
    rationale: str
    tracking_reference: str
    created_on: date
    expires_on: date | None
    scan: bool | None
    warn_bytes: int | None
    hard_bytes: int | None


@dataclass(frozen=True, slots=True)
class ExceptionSettings:
    require_reason: bool
    require_owner: bool
    require_tracking_reference: bool
    allow_expired: bool
    records: tuple[IntentionalException, ...]


@dataclass(frozen=True, slots=True)
class Policy:
    version: int
    repository: RepositorySettings
    output: OutputSettings
    file_rules: tuple[FileRule, ...]
    path_overrides: tuple[PathOverride, ...]
    documentation: DocumentationSettings
    entrypoints: tuple[Entrypoint, ...]
    context_sets: tuple[ContextSet, ...]
    ratchet: RatchetSettings
    exceptions: ExceptionSettings


@dataclass(frozen=True, slots=True)
class GitIndexMetadata:
    mode: GitFileMode
    object_id: str
    skip_worktree: bool = False


@dataclass(frozen=True, slots=True)
class InventoryEntry:
    path: RepositoryPath
    source: InventorySource
    kind: WorktreeKind
    size_bytes: int | None = None
    symlink_target: str | None = None
    index: GitIndexMetadata | None = None


@dataclass(frozen=True, slots=True)
class BaseRevision:
    requested_ref: str
    commit_id: str


@dataclass(frozen=True, slots=True)
class BaseTreeEntry:
    path: RepositoryPath
    mode: GitFileMode
    object_type: GitObjectType
    object_id: str


@dataclass(frozen=True, slots=True)
class SourceLocation:
    path: str
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class Link:
    source: SourceLocation
    kind: LinkKind
    raw_destination: str
    target_path: RepositoryPath | None
    fragment: str | None


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    location: SourceLocation | None = None
    field_path: str | None = None
    details: tuple[tuple[str, JsonValue], ...] = ()
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class RunResult:
    status: RunStatus
    diagnostics: tuple[Diagnostic, ...]
    inventory: tuple[InventoryEntry, ...] = ()
    links: tuple[Link, ...] = ()
