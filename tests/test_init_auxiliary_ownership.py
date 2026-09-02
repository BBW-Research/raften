from __future__ import annotations

import unittest
from unittest import mock

import repo_context.initialization as initialization
import repo_context.init_transaction as transaction
from repo_context.run_model import CommandFailure
from tests.support.repository import RepositoryFixture


class InitializationAuxiliaryOwnershipTests(unittest.TestCase):
    def test_install_refuses_replaced_auxiliary_files(self) -> None:
        attributes = ("temporary_name", "backup_name", "removal_name")
        for attribute in attributes:
            with self.subTest(attribute=attribute), RepositoryFixture() as repository:
                repository.write_text("repo-context.toml", "old policy\n")
                repository.commit("existing policy")
                install = transaction._install_artifact
                replacement_path: str | None = None

                def replace_auxiliary(item, *, force):
                    nonlocal replacement_path
                    if item.artifact.path == "repo-context.toml":
                        replacement_path = getattr(item, attribute)
                        assert replacement_path is not None
                        repository.path(replacement_path).unlink()
                        repository.write_text(
                            replacement_path,
                            f"concurrent {attribute}\n",
                        )
                    return install(item, force=force)

                with mock.patch.object(
                    transaction,
                    "_install_artifact",
                    side_effect=replace_auxiliary,
                ):
                    outcome = initialization.initialize_repository(
                        repository.root,
                        force=True,
                    )

                self.assertIsInstance(outcome, CommandFailure)
                assert isinstance(outcome, CommandFailure)
                assert replacement_path is not None
                self.assertEqual(
                    tuple(item.code for item in outcome.diagnostics),
                    ("INIT002",),
                )
                self.assertEqual(
                    repository.path(replacement_path).read_text(),
                    f"concurrent {attribute}\n",
                )
                self.assertIn(
                    replacement_path,
                    dict(outcome.diagnostics[0].details)["recovery_paths"],
                )
                self.assertEqual(
                    repository.path("repo-context.toml").read_text(),
                    "old policy\n",
                )
                self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_forced_activation_preserves_a_temp_replaced_after_preflight(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.commit("existing policy")
            require_target = transaction._require_unchanged_force_target
            replacement_path: str | None = None

            def replace_temporary(item):
                nonlocal replacement_path
                require_target(item)
                replacement_path = item.temporary_name
                repository.path(replacement_path).unlink()
                repository.write_text(replacement_path, "concurrent temporary\n")

            with mock.patch.object(
                transaction,
                "_require_unchanged_force_target",
                side_effect=replace_temporary,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            assert replacement_path is not None
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")
            self.assertEqual(
                repository.path(replacement_path).read_text(),
                "concurrent temporary\n",
            )
            self.assertIn(
                replacement_path,
                dict(outcome.diagnostics[0].details)["recovery_paths"],
            )

    def test_forced_activation_reports_a_backup_replaced_after_preflight(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.commit("existing policy")
            require_target = transaction._require_unchanged_force_target
            replacement_path: str | None = None

            def replace_backup(item):
                nonlocal replacement_path
                require_target(item)
                assert item.backup_name is not None
                replacement_path = item.backup_name
                repository.path(replacement_path).unlink()
                repository.write_text(replacement_path, "concurrent backup\n")

            with mock.patch.object(
                transaction,
                "_require_unchanged_force_target",
                side_effect=replace_backup,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            assert replacement_path is not None
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT004",))
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")
            self.assertEqual(
                repository.path(replacement_path).read_text(),
                "concurrent backup\n",
            )
            self.assertIn(
                replacement_path,
                dict(outcome.diagnostics[0].details)["recovery_paths"],
            )

    def test_forced_activation_quarantines_a_target_replaced_after_preflight(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.commit("existing policy")
            require_target = transaction._require_unchanged_force_target

            def replace_target(item):
                require_target(item)
                repository.path(item.artifact.path).unlink()
                repository.write_text(item.artifact.path, "concurrent policy\n")

            with mock.patch.object(
                transaction,
                "_require_unchanged_force_target",
                side_effect=replace_target,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    force=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                repository.path("repo-context.toml").read_text(),
                "concurrent policy\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            recovery_data = {
                repository.path(path).read_text()
                for path in recovery_paths
                if repository.path(path).is_file()
            }
            self.assertIn("old policy\n", recovery_data)
            self.assertIn("concurrent policy\n", recovery_data)

    def test_post_publish_check_preserves_a_concurrent_target(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            require_installed = transaction._require_installed_artifact
            raced = False

            def replace_published_target(item):
                nonlocal raced
                if item.artifact.path == "repo-context.toml" and not raced:
                    raced = True
                    repository.path(item.artifact.path).unlink()
                    repository.write_text(item.artifact.path, "concurrent policy\n")
                return require_installed(item)

            with mock.patch.object(
                transaction,
                "_require_installed_artifact",
                side_effect=replace_published_target,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                repository.path("repo-context.toml").read_text(),
                "concurrent policy\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            recovery_data = {
                repository.path(path).read_text()
                for path in recovery_paths
                if repository.path(path).is_file()
            }
            self.assertIn("concurrent policy\n", recovery_data)
            self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_group_commit_rechecks_an_earlier_capture_artifact(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            install = transaction._install_artifact

            def replace_sidecar_before_config(item, *, force):
                if item.artifact.path == "repo-context.toml":
                    repository.path("repo-context.debt.json").unlink()
                    repository.write_text(
                        "repo-context.debt.json",
                        "concurrent sidecar\n",
                    )
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=replace_sidecar_before_config,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                repository.path("repo-context.debt.json").read_text(),
                "concurrent sidecar\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            self.assertTrue(any(repository.path(path).exists() for path in recovery_paths))
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_group_commit_rechecks_config_after_guard_cleanup(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            remove_guard = transaction._remove_absence_guard

            def replace_config_before_guard_cleanup(item):
                repository.path("repo-context.toml").unlink()
                repository.write_text("repo-context.toml", "concurrent policy\n")
                return remove_guard(item)

            with mock.patch.object(
                transaction,
                "_remove_absence_guard",
                side_effect=replace_config_before_guard_cleanup,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                repository.path("repo-context.toml").read_text(),
                "concurrent policy\n",
            )
            recovery_paths = dict(outcome.diagnostics[0].details)["recovery_paths"]
            self.assertTrue(any(repository.path(path).exists() for path in recovery_paths))
            self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_group_commit_rechecks_sidecar_absence_after_guard_cleanup(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            remove_guard = transaction._remove_absence_guard

            def create_sidecar_after_guard_cleanup(item):
                remove_guard(item)
                repository.write_text(
                    "repo-context.debt.json",
                    "concurrent sidecar\n",
                )

            with mock.patch.object(
                transaction,
                "_remove_absence_guard",
                side_effect=create_sidecar_after_guard_cleanup,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertEqual(
                outcome.diagnostics[0].location.path,
                "repo-context.debt.json",
            )
            self.assertEqual(
                repository.path("repo-context.debt.json").read_text(),
                "concurrent sidecar\n",
            )
            self.assertFalse(repository.path("repo-context.toml").exists())


if __name__ == "__main__":
    unittest.main()
