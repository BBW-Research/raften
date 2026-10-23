"""Validate Git administration ownership without invoking Git or reading objects."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from raften import resource_limits as limits
from raften.diagnostics import GIT_PATH_CHANGED, GIT_INVALID_ROOT
from raften.init_namespace import bind_namespace
from raften.init_safety import InitializationError
from raften.repository_errors import RepositoryAccessError, fail_repository


MAX_POINTER_BYTES = 8192
MAX_ADMIN_ENTRIES = 250_000
MAX_ADMIN_DIRECTORIES = 4096
MAX_ADMIN_METADATA_FILES = 4096
INPUT_DIRECTORIES = frozenset({"objects", "refs", "info", "logs", "reftable"})


def _fail(path: Path, reason: str, code: str = GIT_INVALID_ROOT) -> None:
    fail_repository(code, "Git administration is unsafe or changed",
                    path=os.fspath(path), details=(("reason", reason),))


def _identity(value: os.stat_result, timestamps: bool) -> tuple[int, ...]:
    result = (value.st_dev, value.st_ino, value.st_mode)
    if timestamps:
        return result + (value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    return result + (value.st_size,) if stat.S_ISREG(value.st_mode) else result


def _is_link(value: os.stat_result) -> bool:
    return stat.S_ISLNK(value.st_mode) or bool(getattr(value, "st_file_attributes", 0) & 0x400)


@dataclass(frozen=True, slots=True)
class _Witness:
    path: Path
    identity: tuple[int, ...]
    timestamps: bool = True

    def verify(self, code: str) -> None:
        try:
            value = self.path.lstat()
        except (OSError, ValueError):
            _fail(self.path, "administration entry unavailable", code)
        if _is_link(value) or _identity(value, self.timestamps) != self.identity:
            _fail(self.path, "administration identity changed", code)


@dataclass(frozen=True, slots=True)
class GitAdministration:
    root: Path
    gitdir: Path
    common: Path
    witnesses: tuple[_Witness, ...]

    def verify(self, code: str = GIT_PATH_CHANGED) -> None:
        for witness in self.witnesses:
            witness.verify(code)


@contextmanager
def administration_command(root: Path, administration: GitAdministration) -> Iterator[None]:
    """Observe ancestor restoration while a child can consume Git input."""
    if root != administration.root:
        _fail(root, "repository handle does not match its bound administration")
    try:
        with ExitStack() as stack:
            paths = (root,) if administration.common.is_relative_to(root) else (root, administration.common)
            guards = tuple(stack.enter_context(bind_namespace(path)) for path in paths)
            try:
                administration.verify()
                yield
            finally:
                for guard in guards:
                    guard.verify()
                administration.verify()
    except InitializationError:
        _fail(root, "Git command namespace changed or could not be anchored", GIT_PATH_CHANGED)


def _directory_chain(path: Path, witnesses: dict[Path, _Witness]) -> None:
    for current in (*reversed(path.parents), path):
        value = current.lstat()
        if _is_link(value) or not stat.S_ISDIR(value.st_mode):
            _fail(current, "directory component is not a real directory")
        witnesses.setdefault(current, _Witness(current, _identity(value, False), False))


def _read_pointer(path: Path, witnesses: dict[Path, _Witness]) -> bytes:
    value = path.lstat()
    if _is_link(value) or not stat.S_ISREG(value.st_mode):
        _fail(path, "pointer is not a regular no-follow file")
    limits.require_resource("git_pointer_bytes", value.st_size, MAX_POINTER_BYTES,
                            operation="bind-administration")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(path, flags)
    try:
        if _identity(os.fstat(descriptor), True) != _identity(value, True):
            _fail(path, "pointer changed while opening")
        data = bytearray()
        while len(data) <= MAX_POINTER_BYTES:
            part = os.read(descriptor, MAX_POINTER_BYTES + 1 - len(data))
            if not part:
                break
            data.extend(part)
        limits.require_resource("git_pointer_bytes", len(data), MAX_POINTER_BYTES,
                                operation="bind-administration")
        if _identity(os.fstat(descriptor), True) != _identity(value, True):
            _fail(path, "pointer changed while reading")
    finally:
        os.close(descriptor)
    witnesses[path] = _Witness(path, _identity(value, True))
    return bytes(data)


def _pointer_target(base: Path, data: bytes, source: Path) -> Path:
    raw = data.removesuffix(b"\n").removesuffix(b"\r")
    if not raw or any(character in raw for character in (b"\0", b"\n", b"\r")):
        _fail(source, "malformed administration pointer")
    return Path(os.path.abspath(base / os.fsdecode(raw)))


class _AdministrationScan:
    def __init__(self, witnesses: dict[Path, _Witness]) -> None:
        self.witnesses = witnesses
        self.entries = self.directories = self.metadata_files = 0

    def walk(self, root: Path) -> None:
        pending = [(root, True, True)]
        while pending:
            path, metadata, witness_files = pending.pop()
            if path in self.witnesses and self.witnesses[path].timestamps:
                continue
            self.directories += 1
            limits.require_resource("git_admin_directories", self.directories,
                                    MAX_ADMIN_DIRECTORIES, operation="bind-administration")
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                value = os.fstat(descriptor)
                self.witnesses[path] = _Witness(path, _identity(value, True))
                names = []
                with os.scandir(descriptor) as children:
                    for child in children:
                        self.entries += 1
                        limits.require_resource("git_admin_entries", self.entries,
                                                MAX_ADMIN_ENTRIES, operation="bind-administration")
                        names.append(child.name)
                for name in sorted(names):
                    child_path = path / name
                    # These root namespaces are not consumed by our Git commands.
                    if metadata and name in {"hooks", "modules", "worktrees", "rr-cache"}:
                        continue
                    child = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if _is_link(child) or not (stat.S_ISREG(child.st_mode) or stat.S_ISDIR(child.st_mode)):
                        _fail(child_path, "Git input is a symlink or special file")
                    if stat.S_ISDIR(child.st_mode):
                        if not metadata or name in INPUT_DIRECTORIES:
                            # Object payloads have separate content-addressed checks;
                            # refs, reflogs and reftables remain mutable Git inputs.
                            retain = name != "objects" if metadata else witness_files
                            pending.append((child_path, False, retain))
                    elif witness_files or path.name == "info":
                        self.metadata_files += 1
                        limits.require_resource("git_admin_metadata_files", self.metadata_files,
                                                MAX_ADMIN_METADATA_FILES, operation="bind-administration")
                        # Git freshens split-index timestamps even on read-only commands.
                        suffix = name.removeprefix("sharedindex.")
                        shared = (metadata and name.startswith("sharedindex.")
                                  and len(suffix) in {40, 64}
                                  and all(c in "0123456789abcdef" for c in suffix))
                        stamp = _identity(child, not shared)
                        self.witnesses.setdefault(child_path, _Witness(child_path, stamp, not shared))
            finally:
                os.close(descriptor)


def bind_administration(root: Path) -> GitAdministration:
    """Accept in-root administration or an exact common/worktrees registration."""
    entry = root / ".git"
    witnesses: dict[Path, _Witness] = {}
    try:
        if not all(hasattr(os, name) for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY")):
            _fail(entry, "secure administration primitives unavailable")
        _directory_chain(root, witnesses)
        value = entry.lstat()
        if _is_link(value):
            _fail(entry, "selected .git entry is a symlink")
        if stat.S_ISDIR(value.st_mode):
            gitdir = common = entry
            if os.path.lexists(common / "commondir"):
                _fail(common / "commondir", "in-root administration has common indirection")
        elif stat.S_ISREG(value.st_mode):
            data = _read_pointer(entry, witnesses)
            if not data.startswith(b"gitdir: "):
                _fail(entry, "malformed gitfile")
            gitdir = _pointer_target(root, data[8:], entry)
            _directory_chain(gitdir, witnesses)
            common = _pointer_target(gitdir, _read_pointer(gitdir / "commondir", witnesses),
                                     gitdir / "commondir")
            _directory_chain(common, witnesses)
            if gitdir.parent != common / "worktrees" or gitdir.name in {"", ".", ".."}:
                _fail(entry, "gitfile is not a linked-worktree registration")
            backlink = _pointer_target(gitdir, _read_pointer(gitdir / "gitdir", witnesses),
                                       gitdir / "gitdir")
            if backlink != entry:
                _fail(gitdir / "gitdir", "linked-worktree backlink does not name selected .git")
            if os.path.lexists(common / "commondir"):
                _fail(common / "commondir", "nested common-directory indirection")
        else:
            _fail(entry, "selected .git entry is not a directory or regular gitfile")
        _directory_chain(common / "objects", witnesses)
        alternates = common / "objects/info/alternates"
        if os.path.lexists(alternates) and _read_pointer(alternates, witnesses).strip():
            _fail(alternates, "alternate object databases are unsupported")
        scan = _AdministrationScan(witnesses)
        scan.walk(common)
        if gitdir != common:
            scan.walk(gitdir)
            # Register directory-entry changes around the selected backlink as well.
            registration = gitdir.parent
            witnesses[registration] = _Witness(registration, _identity(registration.lstat(), True))
        identity = GitAdministration(root, gitdir, common, tuple(witnesses[p] for p in sorted(witnesses)))
        identity.verify(GIT_INVALID_ROOT)
        return identity
    except RepositoryAccessError:
        raise
    except (OSError, RuntimeError, ValueError) as error:
        _fail(entry, f"administration unavailable: {type(error).__name__}")
