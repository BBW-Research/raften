"""Small valid target-policy repositories for CLI and runner tests."""

from __future__ import annotations

from repo_context.config import render_starter_policy
from tests.support.config import append_exception_record
from tests.support.repository import RepositoryFixture


def install_clean_target(repository: RepositoryFixture) -> None:
    repository.write_bytes("repo-context.toml", render_starter_policy())
    repository.write_text("AGENTS.md", "[Documentation](docs/index.md)\n")
    repository.write_text("README.md", "[Documentation](docs/index.md)\n")
    repository.write_text(
        "ARCHITECTURE.md",
        "[Architecture](docs/architecture/index.md)\n",
    )
    repository.write_text("docs/index.md", "[Architecture](architecture/)\n")
    repository.write_text("docs/architecture/index.md", "# Architecture\n")


def install_runtime_configuration_failure(repository: RepositoryFixture) -> None:
    """Install a valid policy whose path-specific resolution produces CFG015."""

    install_clean_target(repository)
    policy = append_exception_record(
        render_starter_policy().decode("utf-8"),
        '''path = "uv.lock"
owner = "dependencies"
rationale = "Exercise dynamic effective-policy validation"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = true''',
    )
    repository.write_text("repo-context.toml", policy)
    repository.write_text("uv.lock", "runtime configuration fixture\n")
