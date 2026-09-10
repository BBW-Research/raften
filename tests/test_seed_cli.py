from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support.repository import RepositoryFixture, isolated_environment, seed_policy
from tests.support.seed import SEED


class SeedArgumentParsingTests(unittest.TestCase):
    def test_argument_defaults_and_supplied_values(self) -> None:
        with mock.patch.object(SEED.sys, "argv", ["checker"]):
            defaults = SEED.parse_args()
        self.assertEqual(defaults.config, "config/repository_policy.v1.json")
        self.assertIsNone(defaults.base_ref)

        with mock.patch.object(
            SEED.sys,
            "argv",
            ["checker", "--config", "custom.json", "--base-ref", "base"],
        ):
            supplied = SEED.parse_args()
        self.assertEqual(supplied.config, "custom.json")
        self.assertEqual(supplied.base_ref, "base")


class SeedCliCharacterizationTests(unittest.TestCase):
    def test_default_config_clean_repository_exits_zero_on_stdout(self) -> None:
        with RepositoryFixture() as repository:
            repository.install_seed()
            repository.write_seed_policy()
            result = repository.run_seed()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        self.assertEqual(
            result.stdout,
            "repository policy passed: 2 plaintext files, 0 authored Markdown files\n",
        )

    def test_policy_violations_exit_one_with_sorted_errors_and_summary(self) -> None:
        policy = seed_policy(entrypoint_limits={"z.txt": 1, "a.txt": 1})
        with RepositoryFixture() as repository:
            repository.install_seed()
            repository.write_seed_policy(policy)
            repository.write_text("z.txt", "zz")
            repository.write_text("a.txt", "aa")
            first = repository.run_seed()
            second = repository.run_seed()
        self.assertEqual(first.returncode, 1)
        self.assertEqual(first.stdout, "")
        self.assertEqual(
            first.stderr,
            "ERROR: a.txt: 2 bytes exceeds 1; split the file\n"
            "ERROR: z.txt: 2 bytes exceeds 1; split the file\n"
            "repository policy failed with 2 error(s)\n",
        )
        self.assertEqual((second.stdout, second.stderr), (first.stdout, first.stderr))

    def test_malformed_policy_and_git_failure_exit_two_without_traceback(self) -> None:
        with RepositoryFixture() as repository:
            repository.install_seed()
            repository.write_bytes("config/repository_policy.v1.json", b"{")
            invalid_policy = repository.run_seed()
        self.assertEqual(invalid_policy.returncode, 2)
        self.assertEqual(invalid_policy.stdout, "")
        self.assertIn("repository policy error: invalid policy JSON", invalid_policy.stderr)
        self.assertNotIn("Traceback", invalid_policy.stderr)

        with RepositoryFixture(initialize_git=False) as repository:
            repository.install_seed()
            repository.write_seed_policy()
            git_failure = repository.run_seed()
        self.assertEqual(git_failure.returncode, 2)
        self.assertEqual(git_failure.stdout, "")
        self.assertIn("repository policy error:", git_failure.stderr)
        self.assertNotIn("Traceback", git_failure.stderr)

    def test_help_and_unknown_argument_follow_argparse_exit_codes(self) -> None:
        with RepositoryFixture() as repository:
            repository.install_seed()
            help_result = repository.run_seed("--help")
            unknown_result = repository.run_seed("--unknown")
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--config", help_result.stdout)
        self.assertIn("--base-ref", help_result.stdout)
        self.assertEqual(help_result.stderr, "")
        self.assertEqual(unknown_result.returncode, 2)
        self.assertIn("unrecognized arguments: --unknown", unknown_result.stderr)

    def test_base_policy_weakening_is_reported_after_current_state_checks(self) -> None:
        base_policy = seed_policy(
            max_text_bytes=100,
            entrypoint_limits={"a.txt": 1},
            documentation_roots=["docs"],
        )
        current_policy = seed_policy(
            max_text_bytes=101,
            entrypoint_limits={"a.txt": 1},
            documentation_roots=["docs"],
        )
        with RepositoryFixture() as repository:
            repository.install_seed()
            repository.write_seed_policy(base_policy)
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("docs/guide.md", "# Guide\n")
            base = repository.commit("base")
            repository.write_seed_policy(current_policy)
            repository.write_text("a.txt", "aa")
            first = repository.run_seed("--base-ref", base)
            second = repository.run_seed("--base-ref", base)
        self.assertEqual(first.returncode, 1)
        self.assertEqual((second.stdout, second.stderr), (first.stdout, first.stderr))
        size = first.stderr.index("ERROR: a.txt: 2 bytes exceeds 1")
        docs = first.stderr.index("ERROR: docs/index.md: does not directly link sibling")
        ratchet = first.stderr.index("ERROR: max_text_bytes may not increase")
        self.assertLess(size, docs)
        self.assertLess(docs, ratchet)

    def test_missing_and_all_zero_base_refs_are_silently_skipped(self) -> None:
        with RepositoryFixture() as repository:
            repository.install_seed()
            repository.write_seed_policy()
            missing = repository.run_seed("--base-ref", "missing-ref")
            zero = repository.run_seed("--base-ref", "0000000000000000")
        self.assertEqual(missing.returncode, 0)
        self.assertEqual(zero.returncode, 0)
        self.assertEqual(missing.stderr, "")
        self.assertEqual(zero.stderr, "")

    def test_seed_targets_the_checker_location_not_the_current_directory(self) -> None:
        policy = seed_policy(entrypoint_limits={"failure.txt": 1})
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory() as outside:
            repository.install_seed()
            repository.write_seed_policy(policy)
            repository.write_text("failure.txt", "too large")
            result = repository.run_seed(cwd=Path(outside))
        self.assertEqual(result.returncode, 1)
        self.assertIn("ERROR: failure.txt", result.stderr)

    def test_seed_has_no_explicit_repository_argument(self) -> None:
        with RepositoryFixture() as repository:
            repository.install_seed()
            result = repository.run_seed("--repo", repository.root.as_posix())
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments: --repo", result.stderr)

    def test_unsafe_config_path_escapes_seed_operational_error_handling(self) -> None:
        with RepositoryFixture() as repository:
            repository.install_seed()
            result = repository.run_seed("--config", "../policy.json")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Traceback", result.stderr)
        self.assertIn("unsafe or non-canonical repository path", result.stderr)


class RepositoryFixtureContractTests(unittest.TestCase):
    def test_fixture_environment_drops_ambient_git_control_variables(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.hooksPath",
                "GIT_CONFIG_VALUE_0": "/untrusted/hooks",
                "GIT_DIR": "/untrusted/repository",
            },
        ):
            environment = isolated_environment()
        self.assertEqual(environment["GIT_CONFIG_COUNT"], "0")
        self.assertEqual(environment["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(environment["GIT_DEFAULT_HASH"], "sha1")
        self.assertNotIn("GIT_CONFIG_KEY_0", environment)
        self.assertNotIn("GIT_CONFIG_VALUE_0", environment)
        self.assertNotIn("GIT_DIR", environment)

    def test_fixture_commits_deterministically_and_mutates_real_repository(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("old.txt", "old\n")
            base = repository.commit("base")
            repository.rename("old.txt", "new.txt")
            repository.write_bytes("raw.bin", b"a\r\nb\r\n")
            status = repository.git("status", "--short").stdout
        with RepositoryFixture() as matching_repository:
            matching_repository.write_text("old.txt", "old\n")
            matching_base = matching_repository.commit("base")
        self.assertRegex(base, r"^[0-9a-f]+$")
        self.assertEqual(matching_base, base)
        self.assertIn("old.txt", status)
        self.assertIn("new.txt", status)
        self.assertIn("raw.bin", status)

    def test_fixture_can_run_target_cli_without_installation(self) -> None:
        with RepositoryFixture() as repository:
            result = repository.run_target("--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("raften", result.stdout)
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
