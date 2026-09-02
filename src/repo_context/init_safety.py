"""No-follow root and parent anchoring for initialization transactions."""

from __future__ import annotations

import os
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Never

from repo_context.diagnostics import (
    INIT_DESTINATION,
    diagnostic_sort_key,
    operational_diagnostic,
)
from repo_context.model import Diagnostic


class InitializationError(RuntimeError):
    """One or more deterministic initialization failures."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = tuple(sorted(diagnostics, key=diagnostic_sort_key))
        super().__init__(self.diagnostics[0].message)


def _open_parent(
    root: Path,
    root_anchor_fd: int,
    components: Sequence[str],
    path: str,
) -> tuple[int, int]:
    flags = _directory_flags()
    root_descriptor: int | None = None
    descriptor: int | None = None
    try:
        root_descriptor = os.dup(root_anchor_fd)
        _require_selected_root(root, root_descriptor, path)
        descriptor = os.dup(root_descriptor)
        for component in components:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
        return root_descriptor, descriptor
    except InitializationError:
        _close_optional(descriptor)
        _close_optional(root_descriptor)
        raise
    except OSError as error:
        _close_optional(descriptor)
        _close_optional(root_descriptor)
        _fail_parent(path, error)


def _open_root_anchor(root: Path) -> int:
    descriptor: int | None = None
    try:
        descriptor = os.open(root, _directory_flags())
        _require_selected_root(root, descriptor, None)
        return descriptor
    except InitializationError:
        _close_optional(descriptor)
        raise
    except OSError as error:
        _close_optional(descriptor)
        _fail(
            INIT_DESTINATION,
            "selected repository root could not be anchored safely",
            details=(("error_type", type(error).__name__),),
        )


def _require_unchanged_parent(
    *,
    root_path: Path,
    root_fd: int,
    parent_fd: int,
    parent_components: Sequence[str],
    path: str,
) -> None:
    descriptor: int | None = None
    try:
        _require_selected_root(root_path, root_fd, path)
        descriptor = os.dup(root_fd)
        for component in parent_components:
            next_descriptor = os.open(
                component,
                _directory_flags(),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = next_descriptor
        expected = os.fstat(parent_fd)
        actual = os.fstat(descriptor)
    except OSError as error:
        _fail(
            INIT_DESTINATION,
            "initialization destination parent changed after preflight",
            path=path,
            details=(("error_type", type(error).__name__),),
        )
    finally:
        _close_optional(descriptor)
    if (
        not stat.S_ISDIR(actual.st_mode)
        or actual.st_dev != expected.st_dev
        or actual.st_ino != expected.st_ino
    ):
        _fail(
            INIT_DESTINATION,
            "initialization destination parent changed after preflight",
            path=path,
            details=(("state", "identity_changed"),),
        )


def _require_safe_install_primitives() -> None:
    dir_fd_operations = (os.open, os.stat, os.link, os.unlink, os.rename)
    safe = (
        hasattr(os, "O_NOFOLLOW")
        and all(item in os.supports_dir_fd for item in dir_fd_operations)
        and os.stat in os.supports_follow_symlinks
        and os.link in os.supports_follow_symlinks
    )
    if not safe:
        _fail(
            INIT_DESTINATION,
            "platform lacks required no-follow initialization primitives",
        )


def _require_selected_root(
    root: Path,
    root_fd: int,
    path: str | None,
) -> None:
    selected = os.stat(root, follow_symlinks=False)
    opened = os.fstat(root_fd)
    if (
        not stat.S_ISDIR(selected.st_mode)
        or selected.st_dev != opened.st_dev
        or selected.st_ino != opened.st_ino
    ):
        _fail(
            INIT_DESTINATION,
            "selected repository root changed after validation",
            path=path,
            details=(("state", "identity_changed"),),
        )


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return flags


def _close_optional(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _fail_parent(path: str, error: OSError) -> Never:
    _fail(
        INIT_DESTINATION,
        "initialization destination parent must be an existing real directory",
        path=path,
        details=(("error_type", type(error).__name__),),
    )


def _fail(
    code: str,
    message: str,
    *,
    path: str | None = None,
    details=(),
    hint: str | None = None,
) -> Never:
    raise InitializationError(
        (
            operational_diagnostic(
                code,
                message,
                path=path,
                details=details,
                hint=hint,
            ),
        )
    )
