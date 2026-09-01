from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Sequence

from tests.support.seed import BOOTSTRAP_POLICY_PATH, ROOT, SEED_PATH


FIXED_GIT_ENV = {
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_AUTHOR_EMAIL": "repo-context@example.invalid",
    "GIT_AUTHOR_NAME": "Repo Context Tests",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+00:00",
    "GIT_COMMITTER_EMAIL": "repo-context@example.invalid",
    "GIT_COMMITTER_NAME": "Repo Context Tests",
    "GIT_ATTR_NOSYSTEM": "1",
    "GIT_CONFIG_COUNT": "0",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_DEFAULT_HASH": "sha1",
    "GIT_TERMINAL_PROMPT": "0",
    "LC_ALL": "C",
    "TZ": "UTC",
}


def isolated_environment(**overrides: str) -> dict[str, str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("GIT_")
    }
    environment.update(FIXED_GIT_ENV)
    environment.update(overrides)
    return environment


@contextmanager
def isolated_process_environment(**overrides: str) -> Iterator[None]:
    previous = dict(os.environ)
    replacement = isolated_environment(**overrides)
    os.environ.clear()
    os.environ.update(replacement)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def seed_policy(**overrides: Any) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "policy_version": 1,
        "max_text_bytes": 100_000,
        "index_max_bytes": 50_000,
        "entrypoint_limits": {},
        "documentation_roots": [],
        "documentation_excluded_globs": [],
        "text_excluded_globs": [],
        "required_entrypoint_links": {},
        "legacy_oversize": {},
    }
    policy.update(overrides)
    return policy


class RepositoryFixture:
    """A disposable real Git repository for integration behavior."""

    def __init__(self, *, initialize_git: bool = True) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="repo-context-fixture-",
        )
        self.root = Path(self._temporary_directory.name)
        if initialize_git:
            self.git("init", "--quiet", "--initial-branch=main")
            self.git("config", "user.name", "Repo Context Tests")
            self.git("config", "user.email", "repo-context@example.invalid")
            self.git("config", "commit.gpgsign", "false")
            self.git("config", "core.autocrlf", "false")

    def cleanup(self) -> None:
        self._temporary_directory.cleanup()

    def __enter__(self) -> RepositoryFixture:
        return self

    def __exit__(self, *_args: object) -> None:
        self.cleanup()

    def path(self, relative: str) -> Path:
        return self.root / relative

    def write_bytes(self, relative: str, data: bytes) -> Path:
        destination = self.path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        return destination

    def write_text(self, relative: str, text: str) -> Path:
        return self.write_bytes(relative, text.encode("utf-8"))

    def write_json(self, relative: str, value: object) -> Path:
        return self.write_text(
            relative,
            json.dumps(value, indent=2, sort_keys=True) + "\n",
        )

    def ignore(self, *patterns: str) -> Path:
        return self.write_text(".gitignore", "".join(f"{item}\n" for item in patterns))

    def install_seed(self) -> Path:
        destination = self.path("tools/check_repository_policy.py")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SEED_PATH, destination)
        return destination

    def write_seed_policy(self, policy: dict[str, Any] | None = None) -> Path:
        return self.write_json(
            "config/repository_policy.v1.json",
            seed_policy() if policy is None else policy,
        )

    def git(
        self,
        *arguments: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *arguments],
            cwd=self.root,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=isolated_environment(),
            timeout=30,
        )

    def commit(self, message: str = "fixture state") -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", message)
        return self.git("rev-parse", "HEAD").stdout.strip()

    def delete(self, relative: str) -> None:
        self.path(relative).unlink()

    def rename(self, source: str, destination: str) -> None:
        target = self.path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        self.path(source).rename(target)

    def symlink(self, relative: str, target: str) -> Path:
        destination = self.path(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.symlink_to(target)
        return destination

    def run_seed(
        self,
        *arguments: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        script = self.path("tools/check_repository_policy.py")
        return self._run_python([str(script), *arguments], cwd=cwd)

    def run_target(
        self,
        *arguments: str,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        environment = isolated_environment(PYTHONPATH=str(ROOT / "src"))
        return subprocess.run(
            [sys.executable, "-m", "repo_context", *arguments],
            cwd=self.root if cwd is None else cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=environment,
            timeout=30,
        )

    def _run_python(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, *arguments],
            cwd=self.root if cwd is None else cwd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=isolated_environment(),
            timeout=30,
        )


def bootstrap_policy() -> dict[str, Any]:
    return json.loads(BOOTSTRAP_POLICY_PATH.read_text(encoding="utf-8"))


def normalize_temporary_path(output: str, repository: RepositoryFixture) -> str:
    return output.replace(repository.root.as_posix(), "<repo>")
