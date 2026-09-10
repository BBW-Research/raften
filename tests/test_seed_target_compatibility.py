from __future__ import annotations

import unittest

from raften.config import render_starter_policy
from tests.support.config import replace_once
from tests.support.repository import RepositoryFixture, seed_policy
from tests.support.target import install_clean_target


EVALUATION = ("--evaluation-date", "2026-09-02")


def _seed_policy(**overrides):
    policy = seed_policy(
        max_text_bytes=25_600,
        index_max_bytes=12_288,
        entrypoint_limits={
            "AGENTS.md": 12_288,
            "ARCHITECTURE.md": 8_192,
            "README.md": 16_384,
        },
        documentation_roots=["docs"],
        required_entrypoint_links={
            "AGENTS.md": ["docs/index.md"],
            "ARCHITECTURE.md": ["docs/architecture/index.md"],
            "README.md": ["docs/index.md"],
        },
    )
    policy.update(overrides)
    return policy


def _install_pair(repository: RepositoryFixture, *, seed_overrides=None) -> None:
    repository.install_seed()
    repository.write_seed_policy(
        _seed_policy(**({} if seed_overrides is None else seed_overrides))
    )
    install_clean_target(repository)


def _target_with_override(path: str, *, warn_bytes: int, hard_bytes: int) -> str:
    policy = render_starter_policy().decode("utf-8")
    return replace_once(
        policy,
        "\n[documentation]\n",
        f'''\n[[path_override]]
path = "{path}"
warn_bytes = {warn_bytes}
hard_bytes = {hard_bytes}

[documentation]
''',
    )


class EquivalentBehaviorCompatibilityTests(unittest.TestCase):
    def test_clean_repository_is_an_equivalent_success(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            seed = repository.run_seed()
            target = repository.run_target("check", *EVALUATION)

        self.assertEqual(seed.returncode, 0)
        self.assertIn("repository policy passed", seed.stdout)
        self.assertEqual(target.returncode, 0)
        self.assertIn("Summary: 0 errors", target.stdout)

    def test_hard_file_limit_is_an_equivalent_diagnostic(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(
                repository,
                seed_overrides={
                    "entrypoint_limits": {
                        "AGENTS.md": 12_288,
                        "ARCHITECTURE.md": 8_192,
                        "README.md": 16_384,
                        "large.txt": 10,
                    }
                },
            )
            repository.write_text(
                "raften.toml",
                _target_with_override("large.txt", warn_bytes=5, hard_bytes=10),
            )
            repository.write_text("large.txt", "eleven bytes")
            seed = repository.run_seed()
            target = repository.run_target("check", *EVALUATION)

        self.assertEqual(seed.returncode, 1)
        self.assertIn("ERROR: large.txt: 12 bytes exceeds 10", seed.stderr)
        self.assertEqual(target.returncode, 1)
        self.assertIn('ERROR CTX002 "large.txt"', target.stderr)

    def test_missing_entrypoint_is_an_equivalent_diagnostic(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            repository.delete("README.md")
            seed = repository.run_seed()
            target = repository.run_target("check", *EVALUATION)

        self.assertEqual(seed.returncode, 1)
        self.assertIn("README.md: required entrypoint is missing", seed.stderr)
        self.assertEqual(target.returncode, 1)
        self.assertIn('ERROR DOC006 "README.md"', target.stderr)

    def test_limit_weakening_is_an_equivalent_diagnostic(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            base = repository.commit("base policies")
            repository.write_seed_policy(_seed_policy(max_text_bytes=26_000))
            target_policy = replace_once(
                render_starter_policy().decode("utf-8"),
                "warn_bytes = 20480\nhard_bytes = 25600",
                "warn_bytes = 20480\nhard_bytes = 26000",
            )
            repository.write_text("raften.toml", target_policy)
            seed = repository.run_seed("--base-ref", base)
            target = repository.run_target(
                "check",
                "--base-ref",
                base,
                *EVALUATION,
            )

        self.assertEqual(seed.returncode, 1)
        self.assertIn("max_text_bytes may not increase", seed.stderr)
        self.assertEqual(target.returncode, 1)
        self.assertIn("RAT006", target.stderr)


class IntendedImprovementCompatibilityTests(unittest.TestCase):
    def test_intermediate_documentation_ancestor_is_target_only(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            repository.write_text("docs/a/b/index.md", "[Topic](topic.md)\n")
            repository.write_text("docs/a/b/topic.md", "# Topic\n")
            seed = repository.run_seed()
            target = repository.run_target("check", *EVALUATION)

        self.assertEqual(seed.returncode, 0)
        self.assertEqual(target.returncode, 1)
        self.assertIn('ERROR DOC003 "docs/a/index.md"', target.stderr)
        self.assertIn("DOC011", target.stderr)

    def test_missing_local_target_is_target_only(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            repository.write_text(
                "docs/index.md",
                "[Architecture](architecture/)\n[Missing](missing.md#heading)\n",
            )
            seed = repository.run_seed()
            target = repository.run_target("check", *EVALUATION)

        self.assertEqual(seed.returncode, 0)
        self.assertEqual(target.returncode, 1)
        self.assertIn('ERROR DOC009 "docs/index.md"', target.stderr)

    def test_missing_requested_base_is_a_target_operational_failure(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            seed = repository.run_seed("--base-ref", "missing-ref")
            target = repository.run_target(
                "check",
                "--base-ref",
                "missing-ref",
                *EVALUATION,
            )

        self.assertEqual(seed.returncode, 0)
        self.assertEqual(target.returncode, 2)
        self.assertIn("GIT006", target.stderr)
        self.assertNotIn("Traceback", target.stderr)

    def test_unsafe_config_is_a_bounded_target_failure(self) -> None:
        with RepositoryFixture() as repository:
            _install_pair(repository)
            seed = repository.run_seed("--config", "../policy.json")
            target = repository.run_target(
                "check",
                "--config",
                "../policy.toml",
                *EVALUATION,
            )

        self.assertEqual(seed.returncode, 1)
        self.assertIn("Traceback", seed.stderr)
        self.assertEqual(target.returncode, 2)
        self.assertIn("CFG006", target.stderr)
        self.assertNotIn("Traceback", target.stderr)


if __name__ == "__main__":
    unittest.main()
