"""Retain namespace change witnesses until initialization starts publication."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path

from raften.diagnostics import INIT_DESTINATION
from raften.init_safety import _directory_flags, _fail, _require_selected_root


def _stamp(status: os.stat_result) -> tuple[int, int, int, int]:
    return status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns


@dataclass(frozen=True, slots=True)
class NamespaceGuard:
    root: Path
    root_fd: int
    witnesses: tuple[tuple[int, tuple[int, int, int, int]], ...]

    def verify(self) -> None:
        """A rename restored between phases must still invalidate preflight."""

        try:
            for descriptor, expected in self.witnesses:
                if _stamp(os.fstat(descriptor)) != expected:
                    _fail(
                        INIT_DESTINATION, "repository namespace changed during initialization",
                        details=(("state", "namespace_changed"),),
                        hint="retry after concurrent directory changes have stopped",
                    )
            _require_selected_root(self.root, self.root_fd, None)
        except OSError as error:
            _fail(
                INIT_DESTINATION, "repository namespace could not be revalidated",
                details=(("error_type", type(error).__name__),),
            )


@contextmanager
def bind_namespace(root: Path) -> Iterator[NamespaceGuard]:
    """Anchor canonical ancestry before Git validation; never follow a new symlink."""

    descriptors: list[int] = []
    witnesses: list[tuple[int, tuple[int, int, int, int]]] = []
    flags = _directory_flags() | getattr(os, "O_CLOEXEC", 0)
    try:
        try:
            descriptor = os.open(root.anchor, flags)
            descriptors.append(descriptor)
            for component in root.parts[1:]:
                descriptor = os.open(component, flags, dir_fd=descriptor)
                descriptors.append(descriptor)
                witnesses.append((descriptor, _stamp(os.fstat(descriptor))))
        except OSError as error:
            _fail(
                INIT_DESTINATION, "repository namespace could not be anchored safely",
                details=(("error_type", type(error).__name__),),
            )
        guard = NamespaceGuard(root, descriptor, tuple(witnesses))
        guard.verify()
        yield guard
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
