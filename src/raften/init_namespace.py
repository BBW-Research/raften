"""Retain namespace change witnesses until initialization starts publication."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import select

from raften.diagnostics import INIT_DESTINATION
from raften.init_safety import _directory_flags, _fail, _require_selected_root


def _stamp(status: os.stat_result) -> tuple[int, int, int, int]:
    return status.st_dev, status.st_ino, status.st_mtime_ns, status.st_ctime_ns


@dataclass(frozen=True, slots=True)
class NamespaceGuard:
    root: Path
    root_fd: int
    witnesses: tuple[tuple[int, tuple[int, int, int, int]], ...]
    rename_events: select.kqueue | None

    def verify(self) -> None:
        """A rename restored between phases must still invalidate preflight."""

        try:
            if self.rename_events is not None and self.rename_events.control(None, 1, 0):
                _fail_changed()
            for descriptor, expected in self.witnesses:
                # A vnode watch observes this directory's rename, not activity
                # in its unrelated children. Keep the root's content witness.
                if self.rename_events is not None and descriptor != self.root_fd:
                    continue
                if _stamp(os.fstat(descriptor)) != expected:
                    _fail_changed()
            _require_selected_root(self.root, self.root_fd, None)
        except OSError as error:
            _fail(
                INIT_DESTINATION, "repository namespace could not be revalidated",
                details=(("error_type", type(error).__name__),),
            )


def _fail_changed() -> None:
    _fail(
        INIT_DESTINATION, "repository namespace changed during initialization",
        details=(("state", "namespace_changed"),),
        hint="retry after concurrent directory changes have stopped",
    )


@contextmanager
def bind_namespace(root: Path) -> Iterator[NamespaceGuard]:
    """Anchor canonical ancestry before Git validation; never follow a new symlink."""

    descriptors: list[int] = []
    witnesses: list[tuple[int, tuple[int, int, int, int]]] = []
    flags = _directory_flags() | getattr(os, "O_CLOEXEC", 0)
    rename_events = None
    try:
        try:
            queue_factory = getattr(select, "kqueue", None)
            if queue_factory is not None:
                rename_events = queue_factory()
            descriptor = os.open(root.anchor, flags)
            descriptors.append(descriptor)
            for component in root.parts[1:]:
                descriptor = os.open(component, flags, dir_fd=descriptor)
                descriptors.append(descriptor)
                witnesses.append((descriptor, _stamp(os.fstat(descriptor))))
                if rename_events is not None:
                    event = select.kevent(
                        descriptor, filter=select.KQ_FILTER_VNODE,
                        flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                        fflags=select.KQ_NOTE_RENAME | select.KQ_NOTE_DELETE | select.KQ_NOTE_REVOKE,
                    )
                    # Registration must not drain a rename already queued for
                    # an earlier ancestor. Any registration error aborts.
                    rename_events.control([event], 0, 0)
        except OSError as error:
            _fail(
                INIT_DESTINATION, "repository namespace could not be anchored safely",
                details=(("error_type", type(error).__name__),),
            )
        guard = NamespaceGuard(root, descriptor, tuple(witnesses), rename_events)
        guard.verify()
        yield guard
    finally:
        try:
            if rename_events is not None:
                rename_events.close()
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
