from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import repo_context.initialization as initialization
import repo_context.init_transaction as transaction
from repo_context.config import render_starter_policy
from repo_context.debt import parse_debt_manifest
from repo_context.run_model import CommandFailure, InitResult, RunStatus
from tests.support.repository import RepositoryFixture



class InitializationTransactionTests(unittest.TestCase):
    def test_transaction_name_collisions_preserve_preexisting_files(self) -> None:
        token = "fixed-token"
        temporary = f".repo-context.toml.repo-context-{token}.tmp"
        backup = f".repo-context.toml.repo-context-{token}.bak"
        rollback = f".repo-context.toml.repo-context-{token}.rollback"

        with RepositoryFixture() as repository:
            repository.write_text(temporary, "owned temporary collision\n")
            repository.commit("temporary collision")
            with mock.patch.object(transaction.secrets, "token_hex", return_value=token):
                temp_outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(temp_outcome, CommandFailure)
            self.assertEqual(repository.path(temporary).read_text(), "owned temporary collision\n")
            self.assertFalse(repository.path("repo-context.toml").exists())

        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text(backup, "owned backup collision\n")
            repository.commit("backup collision")
            with mock.patch.object(transaction.secrets, "token_hex", return_value=token):
                backup_outcome = initialization.initialize_repository(
                    repository.root,
                    force=True,
                )

            self.assertIsInstance(backup_outcome, CommandFailure)
            self.assertEqual(repository.path(backup).read_text(), "owned backup collision\n")
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")

        with RepositoryFixture() as repository:
            repository.write_text(rollback, "owned rollback collision\n")
            repository.commit("rollback collision")
            with mock.patch.object(transaction.secrets, "token_hex", return_value=token):
                rollback_outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(rollback_outcome, CommandFailure)
            self.assertEqual(repository.path(rollback).read_text(), "owned rollback collision\n")
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_force_refuses_a_destination_changed_to_a_symlink_before_install(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text("protected.txt", "protected\n")
            repository.commit("existing policy")
            install = transaction._install_artifact
            raced = False

            def race_destination(item, *, force):
                nonlocal raced
                if item.artifact.path == "repo-context.toml" and not raced:
                    raced = True
                    repository.path("repo-context.toml").unlink()
                    repository.symlink("repo-context.toml", "protected.txt")
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=race_destination,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(dict(outcome.diagnostics[0].details)["state"], "symlink")
            self.assertTrue(repository.path("repo-context.toml").is_symlink())
            self.assertEqual(repository.path("protected.txt").read_text(), "protected\n")

    def test_final_cleanliness_recheck_prevents_racing_writes(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            with mock.patch.object(
                initialization,
                "repository_is_clean",
                side_effect=(True, False),
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT001",))
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_group_write_rolls_back_a_new_manifest_when_config_install_fails(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            install = transaction._install_artifact

            def fail_config(item, *, force):
                if item.artifact.path == "repo-context.toml":
                    raise OSError("injected failure")
                return install(item, force=force)

            with mock.patch.object(transaction, "_install_artifact", side_effect=fail_config):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_unexpected_install_exception_still_cleans_prepared_artifacts(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            install = transaction._install_artifact

            def unsupported_config_install(item, *, force):
                if item.artifact.path == "repo-context.toml":
                    raise NotImplementedError("injected unsupported primitive")
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=unsupported_config_install,
            ):
                with self.assertRaises(NotImplementedError):
                    initialization.initialize_repository(
                        repository.root,
                        capture_debt=True,
                    )

            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse(repository.path("repo-context.debt.json").exists())
            self.assertEqual(
                tuple(repository.root.glob(".*.repo-context-*")),
                (),
            )

    def test_group_force_write_restores_existing_artifacts_when_install_fails(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text("repo-context.debt.json", '{"old": true}\n')
            repository.commit("old initialization")
            install = transaction._install_artifact

            def fail_config(item, *, force):
                if item.artifact.path == "repo-context.toml":
                    raise OSError("injected failure")
                return install(item, force=force)

            with mock.patch.object(transaction, "_install_artifact", side_effect=fail_config):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")
            self.assertEqual(repository.path("repo-context.debt.json").read_text(), '{"old": true}\n')
            self.assertEqual(
                tuple(path.name for path in repository.root.glob(".*.repo-context-*.bak")),
                (),
            )

    def test_forced_rollback_preserves_old_and_concurrent_sidecar_data(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text("repo-context.debt.json", "old sidecar\n")
            repository.commit("old initialization")
            install = transaction._install_artifact

            def replace_sidecar_then_fail_config(item, *, force):
                if item.artifact.path == "repo-context.toml":
                    repository.path("repo-context.debt.json").unlink()
                    repository.write_text(
                        "repo-context.debt.json",
                        "concurrent owner data\n",
                    )
                    raise OSError("injected config failure")
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=replace_sidecar_then_fail_config,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")
            self.assertEqual(
                repository.path("repo-context.debt.json").read_text(),
                "concurrent owner data\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            recovery_data = {
                repository.path(path).read_text()
                for path in recovery_paths
                if repository.path(path).is_file()
            }
            self.assertIn("old sidecar\n", recovery_data)
            self.assertIn("concurrent owner data\n", recovery_data)

    def test_directory_sync_failure_rolls_back_an_installed_artifact(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            sync = transaction.os.fsync

            def fail_directory(descriptor):
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise OSError("injected directory sync failure")
                return sync(descriptor)

            with mock.patch.object(transaction.os, "fsync", side_effect=fail_directory):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_backup_cleanup_failure_never_rolls_back_committed_replacements(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text("repo-context.debt.json", '{"old": true}\n')
            repository.commit("old initialization")
            with mock.patch.object(
                transaction,
                "_remove_backups",
                side_effect=OSError("injected cleanup failure"),
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertEqual(repository.path("repo-context.toml").read_bytes(), render_starter_policy())
            self.assertEqual(parse_debt_manifest(repository.path("repo-context.debt.json").read_bytes()).entries, ())
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            self.assertEqual(len(recovery_paths), 4)
            self.assertTrue(all(repository.path(path).exists() for path in recovery_paths))
            recovery_data = {
                repository.path(path).read_text()
                for path in recovery_paths
                if repository.path(path).stat().st_size
            }
            self.assertEqual(recovery_data, {"old policy\n", '{"old": true}\n'})

    def test_initialization_fails_closed_without_no_follow_primitives(self) -> None:
        with RepositoryFixture() as repository:
            with mock.patch.object(transaction.os, "supports_dir_fd", frozenset()):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_ignored_untracked_files_do_not_make_repository_dirty(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text(".gitignore", "scratch.tmp\n")
            repository.commit("ignore policy")
            repository.write_text("scratch.tmp", "ignored\n")
            outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, InitResult)


if __name__ == "__main__":
    unittest.main()
