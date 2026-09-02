from __future__ import annotations

import unittest
from unittest import mock

import repo_context.initialization as initialization
import repo_context.init_transaction as transaction
from repo_context.run_model import CommandFailure
from tests.support.repository import RepositoryFixture


class InitializationRecoveryTests(unittest.TestCase):
    def test_rollback_preserves_a_concurrent_replacement_of_an_installed_sidecar(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
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
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertEqual(
                repository.path("repo-context.debt.json").read_text(),
                "concurrent owner data\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            self.assertTrue(any(repository.path(path).exists() for path in recovery_paths))
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_destination_failure_reports_every_rollback_recovery_path(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text("repo-context.debt.json", "old sidecar\n")
            repository.commit("old initialization")
            install = transaction._install_artifact

            def race_both_destinations(item, *, force):
                if item.artifact.path == "repo-context.toml":
                    repository.path("repo-context.debt.json").unlink()
                    repository.write_text(
                        "repo-context.debt.json",
                        "concurrent sidecar\n",
                    )
                    repository.path("repo-context.toml").unlink()
                    repository.write_text("repo-context.toml", "concurrent policy\n")
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=race_both_destinations,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                repository.path("repo-context.toml").read_text(),
                "concurrent policy\n",
            )
            self.assertEqual(
                repository.path("repo-context.debt.json").read_text(),
                "concurrent sidecar\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            recovery_data = {
                repository.path(path).read_text()
                for path in recovery_paths
                if repository.path(path).is_file()
            }
            self.assertIn("old policy\n", recovery_data)
            self.assertIn("old sidecar\n", recovery_data)
            self.assertIn("concurrent sidecar\n", recovery_data)

    def test_preparation_cleanup_preserves_a_replaced_temporary_file(self) -> None:
        token = "preparation-race"
        temporary = f".repo-context.toml.repo-context-{token}.tmp"

        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.commit("existing policy")
            write_all = transaction._write_all

            def replace_temporary_during_write(descriptor, data):
                write_all(descriptor, data)
                if repository.path(temporary).exists():
                    repository.path(temporary).unlink()
                    repository.write_text(temporary, "concurrent temporary\n")
                    raise OSError("injected write failure")

            with (
                mock.patch.object(transaction.secrets, "token_hex", return_value=token),
                mock.patch.object(
                    transaction,
                    "_write_all",
                    side_effect=replace_temporary_during_write,
                ),
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertEqual(
                repository.path(temporary).read_text(),
                "concurrent temporary\n",
            )
            self.assertIn(
                temporary,
                dict(outcome.diagnostics[0].details)["recovery_paths"],
            )
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")

    def test_guard_cleanup_preserves_a_replaced_rollback_quarantine(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            remove_guard = transaction._remove_absence_guard
            replaced_path: str | None = None

            def replace_quarantine(item):
                nonlocal replaced_path
                assert item.removal_name is not None
                replaced_path = item.removal_name
                repository.path(replaced_path).unlink()
                repository.write_text(replaced_path, "concurrent quarantine\n")
                return remove_guard(item)

            with mock.patch.object(
                transaction,
                "_remove_absence_guard",
                side_effect=replace_quarantine,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            assert replaced_path is not None
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                repository.path(replaced_path).read_text(),
                "concurrent quarantine\n",
            )
            self.assertIn(
                replaced_path,
                dict(outcome.diagnostics[0].details)["recovery_paths"],
            )
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_rollback_preserves_a_replaced_rollback_quarantine(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            install = transaction._install_artifact
            replaced_path: str | None = None
            installed = []

            def replace_quarantine_then_fail(item, *, force):
                nonlocal replaced_path
                if item.artifact.path == "repo-context.toml":
                    sidecar = next(
                        prepared
                        for prepared in installed
                        if prepared.artifact.path == "repo-context.debt.json"
                    )
                    assert sidecar.removal_name is not None
                    replaced_path = sidecar.removal_name
                    repository.path(replaced_path).unlink()
                    repository.write_text(replaced_path, "concurrent quarantine\n")
                    raise OSError("injected config failure")
                installed.append(item)
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=replace_quarantine_then_fail,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            assert replaced_path is not None
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertEqual(
                repository.path(replaced_path).read_text(),
                "concurrent quarantine\n",
            )
            self.assertIn(
                replaced_path,
                dict(outcome.diagnostics[0].details)["recovery_paths"],
            )
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse(repository.path("repo-context.debt.json").exists())


if __name__ == "__main__":
    unittest.main()
