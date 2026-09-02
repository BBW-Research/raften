"""Export an exact clean commit as the only permitted release source."""

from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repo_context.git_executable import resolve_git_executable
from repo_context.inventory import (
    RepositoryAccessError,
    list_base_tree,
    open_repository,
    read_base_blob,
    repository_is_clean,
    resolve_base_revision,
)
from repo_context.model import GitFileMode, GitObjectType


class ReleaseSourceError(RuntimeError):
    """The selected release source is not an exact clean commit."""


@dataclass(frozen=True, slots=True)
class ReleaseSource:
    root: Path
    commit_id: str
    commit_timestamp: int


def require_clean_release_source(
    root: Path,
    *,
    expected_commit: str | None = None,
) -> ReleaseSource:
    """Resolve HEAD and refuse tracked, staged, or nonignored untracked changes."""

    try:
        repository = open_repository(root)
        revision = resolve_base_revision(repository, "HEAD")
        clean = repository_is_clean(repository)
    except RepositoryAccessError as error:
        raise ReleaseSourceError(str(error)) from error
    if not clean:
        raise ReleaseSourceError("release source must be a clean Git worktree")
    if expected_commit is not None and revision.commit_id != expected_commit:
        raise ReleaseSourceError(
            "release source commit changed during the build: "
            f"expected={expected_commit}, actual={revision.commit_id}"
        )
    return ReleaseSource(
        repository.root,
        revision.commit_id,
        _commit_timestamp(repository.root, revision.commit_id),
    )


def export_release_source(source: ReleaseSource, destination: Path) -> None:
    """Materialize regular blobs from the exact source commit without attributes."""

    if destination.exists() or destination.is_symlink():
        raise ReleaseSourceError(f"release export destination already exists: {destination}")
    destination.mkdir(mode=0o700)
    try:
        repository = open_repository(source.root)
        revision = resolve_base_revision(repository, source.commit_id)
        entries = list_base_tree(repository, revision)
        for entry in entries:
            if entry.object_type is GitObjectType.TREE:
                continue
            if entry.object_type is not GitObjectType.BLOB or entry.mode not in {
                GitFileMode.REGULAR,
                GitFileMode.EXECUTABLE,
            }:
                raise ReleaseSourceError(
                    f"release source contains unsupported entry {entry.path!r} ({entry.mode})"
                )
            target = destination.joinpath(*entry.path.split("/"))
            target.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(read_base_blob(repository, entry))
            target.chmod(0o755 if entry.mode is GitFileMode.EXECUTABLE else 0o644)
    except RepositoryAccessError as error:
        raise ReleaseSourceError(str(error)) from error


def _commit_timestamp(root: Path, commit_id: str) -> int:
    try:
        git, safe_path = resolve_git_executable(root)
        result = subprocess.run(
            [
                git,
                "-c",
                f"core.fsmonitor={os.devnull}",
                "-c",
                f"core.hooksPath={os.devnull}",
                "show",
                "--no-patch",
                "--format=%ct",
                commit_id,
            ],
            cwd=root,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=_git_environment(safe_path),
            timeout=30,
        )
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as error:
        raise ReleaseSourceError(
            f"cannot read release commit timestamp: {type(error).__name__}"
        ) from error
    if result.returncode != 0:
        raise ReleaseSourceError(
            f"cannot read release commit timestamp: Git exited {result.returncode}"
        )
    raw_timestamp = result.stdout.strip()
    if not raw_timestamp.isdigit() or result.stdout != raw_timestamp + b"\n":
        raise ReleaseSourceError("Git returned a malformed release commit timestamp")
    return int(raw_timestamp)


def _git_environment(safe_path: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment.update(
        {
            "GIT_CONFIG_COUNT": "0",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "PATH": safe_path,
        }
    )
    return environment


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--expected-commit")
    parser.add_argument("--export", type=Path)
    options = parser.parse_args(arguments)
    try:
        source = require_clean_release_source(
            options.root,
            expected_commit=options.expected_commit,
        )
        if options.export is not None:
            export_release_source(source, options.export)
    except ReleaseSourceError as error:
        parser.exit(1, f"error: {error}\n")
    print(f"{source.commit_id} {source.commit_timestamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
