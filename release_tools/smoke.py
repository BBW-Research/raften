"""Run every public command through one installed or vendored executable."""

from __future__ import annotations

import argparse
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence


class SmokeFailure(RuntimeError):
    """A distribution command did not satisfy the public smoke contract."""


def smoke(command: Sequence[str], *, expected_version: str) -> None:
    if not command:
        raise ValueError("distribution smoke command may not be empty")
    with tempfile.TemporaryDirectory(prefix="repo-context-distribution-") as directory:
        workspace = Path(directory)
        repository = workspace / "repository"
        environment = _environment()
        version = _run(command, "--version", environment=environment, cwd=workspace)
        expected = f"repo-context {expected_version}\n"
        if version.stdout != expected:
            raise SmokeFailure(f"unexpected version output: {version.stdout!r}")
        _install_repository(repository, environment)
        initialized = _run(
            command,
            "init",
            "--repo",
            str(repository),
            environment=environment,
            cwd=workspace,
        )
        if 'Wrote "repo-context.toml".' not in initialized.stdout:
            raise SmokeFailure(f"init did not report activation: {initialized.stdout!r}")
        _git(repository, environment, "add", "repo-context.toml")
        _git(repository, environment, "commit", "-m", "adopt policy")

        checked = _run(
            command,
            "check",
            "--repo",
            str(repository),
            "--base-ref",
            "HEAD",
            "--evaluation-date",
            "2026-09-02",
            environment=environment,
            cwd=workspace,
        )
        if "Summary: 0 errors" not in checked.stdout:
            raise SmokeFailure(f"check did not pass: {checked.stdout!r}")
        audited = _run(
            command,
            "audit",
            "--repo",
            str(repository),
            "--base-ref",
            "HEAD",
            "--evaluation-date",
            "2026-09-02",
            environment=environment,
            cwd=workspace,
        )
        if "Audit:" not in audited.stdout:
            raise SmokeFailure(f"audit did not report metrics: {audited.stdout!r}")
        explained = _run(
            command,
            "explain",
            "README.md",
            "--repo",
            str(repository),
            "--base-ref",
            "HEAD",
            "--evaluation-date",
            "2026-09-02",
            environment=environment,
            cwd=workspace,
        )
        if 'Path: "README.md".' not in explained.stdout:
            raise SmokeFailure(f"explain did not select README.md: {explained.stdout!r}")


def _run(
    command: Sequence[str],
    *arguments: str,
    environment: dict[str, str],
    cwd: Path,
):
    result = subprocess.run(
        [*command, *arguments],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=environment,
        cwd=cwd,
        timeout=30,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            f"command {arguments!r} exited {result.returncode}: "
            f"stdout={result.stdout!r}, stderr={result.stderr!r}"
        )
    return result


def _install_repository(repository: Path, environment: dict[str, str]) -> None:
    repository.mkdir()
    _git(repository, environment, "init", "--quiet")
    _git(repository, environment, "config", "user.name", "Repo Context Release")
    _git(repository, environment, "config", "user.email", "release@example.invalid")
    files = {
        "AGENTS.md": "[Documentation](docs/index.md)\n",
        "ARCHITECTURE.md": "[Architecture](docs/architecture/index.md)\n",
        "README.md": "[Documentation](docs/index.md)\n",
        "docs/architecture/index.md": "# Architecture\n",
        "docs/index.md": "# Documentation\n\n[Architecture](architecture/)\n",
    }
    for name, text in files.items():
        path = repository / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    _git(repository, environment, "add", ".")
    _git(repository, environment, "commit", "-m", "initial repository")


def _git(repository: Path, environment: dict[str, str], *arguments: str) -> None:
    result = subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgSign=false",
            "-c",
            "tag.gpgSign=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            "-C",
            str(repository),
            *arguments,
        ],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        timeout=30,
    )
    if result.returncode != 0:
        raise SmokeFailure(
            f"Git {arguments!r} exited {result.returncode}: {result.stderr.decode(errors='replace')}"
        )


def _environment() -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith("PYTHON") or name in {
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "VIRTUAL_ENV",
        } or name.startswith("GIT_CONFIG_"):
            environment.pop(name, None)
    environment.update(
        {
            "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }
    )
    return environment


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    command = options.command[1:] if options.command[:1] == ["--"] else options.command
    smoke(command, expected_version=options.expected_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
