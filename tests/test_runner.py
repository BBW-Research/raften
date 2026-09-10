from __future__ import annotations

import hashlib
import unittest
from collections import Counter
from datetime import date
from unittest import mock

import raften.runner as runner
from raften.config import render_starter_policy
from raften.debt import render_debt_manifest
from raften.model import MigrationDebtEntry, MigrationDebtManifest, MigrationStatus
from raften.run_model import CommandFailure, RepositoryRun, RunStatus
from raften.runner import explain_repository_path, run_repository
from tests.support.repository import RepositoryFixture
from tests.support.config import append_exception_record
from tests.support.target import install_clean_target, install_runtime_configuration_failure


TODAY = date(2026, 9, 2)


class RepositoryRunnerTests(unittest.TestCase):
    def test_content_cache_retains_only_reused_command_artifacts(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            handle = runner.open_repository(repository.root)
            snapshot = runner.inventory_worktree(handle)
            entries = {item.path: item for item in snapshot.entries}
            content = runner._ContentCache(
                handle,
                frozenset({"raften.toml", "raften.debt.json"}),
            )
            content.read(entries["raften.toml"])
            content.read(entries["README.md"])

        self.assertEqual(tuple(content.values), ("raften.toml",))

    def test_clean_current_repository_runs_every_engine_from_an_explicit_root(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            with mock.patch.object(
                runner,
                "read_worktree_bytes",
                wraps=runner.read_worktree_bytes,
            ) as read:
                outcome = run_repository(repository.root, evaluation_date=TODAY)

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertEqual(outcome.status, RunStatus.COMPLETE)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("RAT001",))
        self.assertEqual(outcome.documentation.governed_paths, (
            "docs/architecture/index.md",
            "docs/index.md",
        ))
        self.assertEqual(outcome.ratchet.baseline_source.value, "unavailable")
        counts = Counter(call.args[1].path for call in read.call_args_list)
        self.assertTrue(counts)
        self.assertEqual(set(counts.values()), {1})
        self.assertEqual(counts["raften.toml"], 1)

    def test_base_policy_and_blobs_produce_policy_and_file_ratchet_findings(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            base = repository.commit("clean policy")
            repository.write_bytes("new.txt", b"x" * 25_601)
            outcome = run_repository(
                repository.root,
                base_ref=base,
                evaluation_date=TODAY,
            )

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertEqual(outcome.base_commit_id, base)
        self.assertEqual(
            tuple(item.code for item in outcome.diagnostics if item.location and item.location.path == "new.txt"),
            ("CTX002", "RAT002"),
        )

    def test_oversized_policy_reuses_its_already_parsed_base_blob(self) -> None:
        padded_policy = (
            render_starter_policy()
            + b"\n# "
            + b"x" * 26_000
            + b"\n"
        )
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("raften.toml", padded_policy)
            base = repository.commit("oversized policy")
            with mock.patch.object(
                runner,
                "read_base_blob",
                wraps=runner.read_base_blob,
            ) as read:
                outcome = run_repository(
                    repository.root,
                    base_ref=base,
                    evaluation_date=TODAY,
                )

        self.assertIsInstance(outcome, RepositoryRun)
        config_reads = [
            call
            for call in read.call_args_list
            if call.args[1].path == "raften.toml"
        ]
        self.assertEqual(len(config_reads), 1)

    def test_base_without_policy_uses_exact_current_first_adoption_manifest(self) -> None:
        payload = b"x" * 30_000
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "base\n")
            base = repository.commit("before policy")
            install_clean_target(repository)
            repository.write_bytes("legacy.txt", payload)
            manifest = MigrationDebtManifest(
                1,
                (
                    MigrationDebtEntry(
                        "legacy.txt",
                        len(payload),
                        "sha256:" + hashlib.sha256(payload).hexdigest(),
                    ),
                ),
            )
            repository.write_bytes("raften.debt.json", render_debt_manifest(manifest))
            with mock.patch.object(
                runner,
                "read_worktree_bytes",
                wraps=runner.read_worktree_bytes,
            ) as read:
                outcome = run_repository(
                    repository.root,
                    base_ref=base,
                    evaluation_date=TODAY,
                )

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertNotIn("CTX002", {item.code for item in outcome.diagnostics})
        self.assertEqual(outcome.ratchet.files[0].migration_status, MigrationStatus.DEBT)
        self.assertEqual(outcome.ratchet.baseline_source.value, "manifest")
        counts = Counter(call.args[1].path for call in read.call_args_list)
        self.assertEqual(counts["raften.toml"], 1)
        self.assertEqual(counts["raften.debt.json"], 1)

    def test_missing_manifest_for_base_without_policy_is_operational_failure(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "base\n")
            base = repository.commit("before policy")
            install_clean_target(repository)
            outcome = run_repository(
                repository.root,
                base_ref=base,
                evaluation_date=TODAY,
            )

        self.assertIsInstance(outcome, CommandFailure)
        assert isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.status, RunStatus.OPERATIONAL_ERROR)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("GIT007",))

    def test_base_policy_symlink_is_not_parsed_as_policy_blob(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("policy-target.toml", render_starter_policy())
            repository.symlink("raften.toml", "policy-target.toml")
            base = repository.commit("symlink policy")
            repository.path("raften.toml").unlink()
            install_clean_target(repository)
            outcome = run_repository(
                repository.root,
                base_ref=base,
                evaluation_date=TODAY,
            )

        self.assertIsInstance(outcome, CommandFailure)
        assert isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.status, RunStatus.OPERATIONAL_ERROR)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("GIT007",))
        self.assertEqual(
            dict(outcome.diagnostics[0].details),
            {
                "base_commit_id": base,
                "mode": "120000",
                "object_type": "blob",
            },
        )

    def test_disabled_file_comparison_needs_no_manifest_when_base_has_no_policy(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "base\n")
            base = repository.commit("before policy")
            install_clean_target(repository)
            repository.write_bytes(
                "raften.toml",
                render_starter_policy().replace(
                    b"compare_file_sizes = true",
                    b"compare_file_sizes = false",
                ).replace(
                    b"forbid_new_oversize = true",
                    b"forbid_new_oversize = false",
                ),
            )
            outcome = run_repository(
                repository.root,
                base_ref=base,
                evaluation_date=TODAY,
            )

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertEqual(outcome.base_commit_id, base)
        self.assertEqual(outcome.ratchet.baseline_source.value, "disabled")
        self.assertEqual(outcome.diagnostics, ())

    def test_config_need_not_be_git_visible_but_must_be_repo_contained_regular(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.ignore("raften.toml")
            outcome = run_repository(repository.root, evaluation_date=TODAY)

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertNotIn("raften.toml", {item.path for item in outcome.inventory})

    def test_invalid_current_config_is_a_structured_configuration_failure(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("raften.toml", render_starter_policy().replace(b"version = 1", b"version = 2"))
            outcome = run_repository(repository.root, evaluation_date=TODAY)

        self.assertIsInstance(outcome, CommandFailure)
        assert isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.status, RunStatus.CONFIGURATION_ERROR)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("CFG005",))

    def test_runtime_configuration_failure_precedes_base_resolution(self) -> None:
        with RepositoryFixture() as repository:
            install_runtime_configuration_failure(repository)
            with mock.patch.object(runner, "resolve_base_revision") as resolve:
                outcome = run_repository(
                    repository.root,
                    base_ref="definitely-missing-ref",
                    evaluation_date=TODAY,
                )

        self.assertIsInstance(outcome, CommandFailure)
        assert isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.status, RunStatus.CONFIGURATION_ERROR)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("CFG015",))
        resolve.assert_not_called()

    def test_explain_projects_policy_graph_context_and_migration_for_nonexistent_path(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            outcome = explain_repository_path(
                repository.root,
                "docs/future.md",
                evaluation_date=TODAY,
            )

        self.assertNotIsInstance(outcome, CommandFailure)
        assert not isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.file.path, "docs/future.md")
        self.assertEqual(outcome.file.policy.kind.value, "authored")
        self.assertIsNone(outcome.file.assessment)
        self.assertFalse(outcome.documentation.governed)
        self.assertIsNone(outcome.migration)

    def test_explain_accepts_literal_git_filename_data(self) -> None:
        paths = ("literal[1].txt", "literal\\name.txt", "control\x01name.txt")
        for path in paths:
            with self.subTest(path=repr(path)), RepositoryFixture() as repository:
                install_clean_target(repository)
                repository.write_text(path, "candidate filename\n")
                outcome = explain_repository_path(
                    repository.root,
                    path,
                    evaluation_date=TODAY,
                )

                self.assertNotIsInstance(outcome, CommandFailure)
                assert not isinstance(outcome, CommandFailure)
                self.assertEqual(outcome.file.path, path)
                self.assertIsNotNone(outcome.file.assessment)

    def test_explain_rejects_invalid_effective_policy_for_an_absent_path(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            policy = append_exception_record(
                render_starter_policy().decode("utf-8"),
                '''path = "uv.lock"
owner = "dependencies"
rationale = "Invalid threshold relief on an unscanned path"
tracking_reference = "ADR-42"
created_on = 2026-08-01
warn_bytes = 30000
hard_bytes = 40000''',
            )
            repository.write_text("raften.toml", policy)
            outcome = explain_repository_path(
                repository.root,
                "uv.lock",
                evaluation_date=TODAY,
            )

        self.assertIsInstance(outcome, CommandFailure)
        assert isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.status, RunStatus.CONFIGURATION_ERROR)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("CFG015",))
        self.assertEqual(outcome.diagnostics[0].location.path, "uv.lock")

    def test_unsafe_command_paths_fail_without_opening_a_repository(self) -> None:
        outcome = run_repository(
            "/does/not/exist",
            config_path="../outside.toml",
            evaluation_date=TODAY,
        )

        self.assertIsInstance(outcome, CommandFailure)
        assert isinstance(outcome, CommandFailure)
        self.assertEqual(outcome.status, RunStatus.CONFIGURATION_ERROR)
        self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("CFG006",))


if __name__ == "__main__":
    unittest.main()
