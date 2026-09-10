"""Trusted Git executable discovery for the repository process boundary."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def resolve_git_executable(root: Path) -> tuple[str, str]:
    """Return an absolute Git executable and a repository-safe child PATH."""

    canonical_root = root.resolve(strict=True)
    directories: list[Path] = []
    raw_path = os.environ.get("PATH", os.defpath)
    for raw_directory in raw_path.split(os.pathsep):
        if not raw_directory:
            continue
        directory = Path(raw_directory)
        if not directory.is_absolute():
            continue
        try:
            directory = directory.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if not directory.is_dir() or directory.is_relative_to(canonical_root):
            continue
        if directory not in directories:
            directories.append(directory)

    safe_path = os.pathsep.join(os.fspath(item) for item in directories)
    for directory in directories:
        # An absolute directory component prevents shutil.which() from adding
        # the current directory on Windows while retaining PATHEXT handling.
        discovered = shutil.which(os.fspath(directory / "git"))
        if discovered is None:
            continue
        try:
            executable = Path(discovered).resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            continue
        if not executable.is_relative_to(canonical_root):
            return os.fspath(executable), safe_path
    raise FileNotFoundError("no Git executable is available on the trusted PATH")
