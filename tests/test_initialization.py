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


class InitializationTests(unittest.TestCase):
    def test_clean_repository_gets_canonical_policy_without_touching_source(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("clean source")
            outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, InitResult)
            assert isinstance(outcome, InitResult)
            self.assertEqual(outcome.written_paths, ("repo-context.toml",))
            self.assertEqual(repository.path("repo-context.toml").read_bytes(), render_starter_policy())
            self.assertEqual(repository.path("source.txt").read_text(encoding="utf-8"), "source\n")
            self.assertFalse(repository.path("repo-context.debt.json").exists())

    def test_dirty_repository_is_refused_before_any_write(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "uncommitted\n")
            outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(outcome.status, RunStatus.OPERATIONAL_ERROR)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT001",))
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_oversized_authored_file_requires_explicit_debt_capture(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("legacy.txt", b"x" * 30_000)
            repository.commit("legacy source")
            outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT003",))
            self.assertEqual(outcome.diagnostics[0].location.path, "legacy.txt")
            self.assertFalse(repository.path("repo-context.toml").exists())

    def test_capture_writes_exact_debt_and_an_empty_capture_is_still_versioned(self) -> None:
        for payloads, expected_paths in (
            ({"legacy.txt": b"x" * 30_000}, ("legacy.txt",)),
            ({"small.txt": b"small\n"}, ()),
        ):
            with self.subTest(expected_paths=expected_paths), RepositoryFixture() as repository:
                for path, data in payloads.items():
                    repository.write_bytes(path, data)
                repository.commit("source")
                outcome = initialization.initialize_repository(
                    repository.root,
                    capture_debt=True,
                )

                self.assertIsInstance(outcome, InitResult)
                assert isinstance(outcome, InitResult)
                self.assertEqual(
                    outcome.written_paths,
                    ("repo-context.debt.json", "repo-context.toml"),
                )
                parsed = parse_debt_manifest(repository.path("repo-context.debt.json").read_bytes())
                self.assertEqual(tuple(item.path for item in parsed.entries), expected_paths)

    def test_existing_destinations_require_force_and_force_replaces_regular_files(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", "old policy\n")
            repository.write_text("repo-context.debt.json", '{"old": true}\n')
            repository.commit("old initialization")

            refused = initialization.initialize_repository(
                repository.root,
                capture_debt=True,
            )
            self.assertIsInstance(refused, CommandFailure)
            assert isinstance(refused, CommandFailure)
            self.assertEqual(tuple(item.code for item in refused.diagnostics), ("INIT002",))
            self.assertEqual(repository.path("repo-context.toml").read_text(), "old policy\n")

            replaced = initialization.initialize_repository(
                repository.root,
                capture_debt=True,
                force=True,
            )
            self.assertIsInstance(replaced, InitResult)
            self.assertEqual(repository.path("repo-context.toml").read_bytes(), render_starter_policy())
            self.assertEqual(parse_debt_manifest(repository.path("repo-context.debt.json").read_bytes()).entries, ())

    def test_stale_manifest_is_never_silently_left_without_capture(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.debt.json", "stale\n")
            repository.commit("stale sidecar")
            outcome = initialization.initialize_repository(repository.root, force=True)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertEqual(repository.path("repo-context.debt.json").read_text(), "stale\n")

    def test_ignored_sidecar_race_is_atomically_refused_before_config_activation(self) -> None:
        with RepositoryFixture() as repository:
            repository.ignore("repo-context.debt.json")
            repository.commit("ignore sidecar")
            write_artifacts = initialization._write_artifacts

            def race_sidecar(
                root,
                artifacts,
                *,
                root_anchor_fd,
                force,
                absence_guards=(),
            ):
                repository.write_text("repo-context.debt.json", "racing stale sidecar\n")
                return write_artifacts(
                    root,
                    artifacts,
                    root_anchor_fd=root_anchor_fd,
                    force=force,
                    absence_guards=absence_guards,
                )

            with mock.patch.object(
                initialization,
                "_write_artifacts",
                side_effect=race_sidecar,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertEqual(
                repository.path("repo-context.debt.json").read_text(),
                "racing stale sidecar\n",
            )

    def test_post_preflight_destination_collisions_are_path_scoped(self) -> None:
        cases = (
            (False, "repo-context.debt.json"),
            (True, "repo-context.toml"),
        )
        for capture_debt, raced_path in cases:
            with self.subTest(capture_debt=capture_debt), RepositoryFixture() as repository:
                repository.write_text("source.txt", "source\n")
                if not capture_debt:
                    repository.ignore("repo-context.debt.json")
                repository.commit("collision fixture")
                install = transaction._install_artifact
                raced = False

                def create_destination(item, *, force):
                    nonlocal raced
                    if item.artifact.path == raced_path and not raced:
                        raced = True
                        repository.write_text(raced_path, "concurrent owner data\n")
                    return install(item, force=force)

                with mock.patch.object(
                    transaction,
                    "_install_artifact",
                    side_effect=create_destination,
                ):
                    outcome = initialization.initialize_repository(
                        repository.root,
                        capture_debt=capture_debt,
                    )

                self.assertIsInstance(outcome, CommandFailure)
                assert isinstance(outcome, CommandFailure)
                self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
                self.assertEqual(outcome.diagnostics[0].location.path, raced_path)
                self.assertEqual(repository.path(raced_path).read_text(), "concurrent owner data\n")

    def test_replaced_absence_guard_is_preserved_and_rolls_back_config(self) -> None:
        config_path = "nested/repo-context.toml"
        sidecar_path = "nested/repo-context.debt.json"
        with RepositoryFixture() as repository:
            repository.write_text("nested/source.txt", "source\n")
            repository.ignore(sidecar_path)
            repository.commit("ignore sidecar")
            install = transaction._install_artifact
            raced = False

            def replace_guard_before_config(item, *, force):
                nonlocal raced
                if item.artifact.path == config_path and not raced:
                    raced = True
                    repository.path(sidecar_path).unlink()
                    repository.write_text(
                        sidecar_path,
                        "concurrent owner data\n",
                    )
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=replace_guard_before_config,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    config_path=config_path,
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            details = dict(outcome.diagnostics[0].details)
            self.assertTrue(details["replacement_restored"])
            self.assertEqual(
                repository.path(sidecar_path).read_text(),
                "concurrent owner data\n",
            )
            self.assertTrue(details["recovery_path"].startswith("nested/"))
            self.assertTrue(repository.path(details["recovery_path"]).exists())
            self.assertFalse(repository.path(config_path).exists())

    def test_symlink_destination_and_missing_parent_are_refused(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("protected.txt", "protected\n")
            repository.symlink("repo-context.toml", "protected.txt")
            repository.commit("symlink destination")
            symlink = initialization.initialize_repository(repository.root, force=True)

            self.assertIsInstance(symlink, CommandFailure)
            assert isinstance(symlink, CommandFailure)
            self.assertEqual(tuple(item.code for item in symlink.diagnostics), ("INIT002",))
            self.assertTrue(repository.path("repo-context.toml").is_symlink())
            self.assertEqual(repository.path("protected.txt").read_text(), "protected\n")

        with RepositoryFixture() as repository:
            repository.write_text("source.txt", "source\n")
            repository.commit("source")
            missing_parent = initialization.initialize_repository(
                repository.root,
                config_path="missing/repo-context.toml",
            )

            self.assertIsInstance(missing_parent, CommandFailure)
            assert isinstance(missing_parent, CommandFailure)
            self.assertEqual(tuple(item.code for item in missing_parent.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("missing").exists())

        with RepositoryFixture() as repository:
            repository.path("real").mkdir()
            repository.symlink("linked", "real")
            repository.commit("symlink parent")
            symlink_parent = initialization.initialize_repository(
                repository.root,
                config_path="linked/repo-context.toml",
            )

            self.assertIsInstance(symlink_parent, CommandFailure)
            assert isinstance(symlink_parent, CommandFailure)
            self.assertEqual(tuple(item.code for item in symlink_parent.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("real/repo-context.toml").exists())

    def test_parent_renamed_outside_repository_before_install_is_refused(self) -> None:
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory(
            dir=repository.root.parent,
        ) as outside:
            repository.write_text("nested/source.txt", "source\n")
            repository.commit("nested destination parent")
            install = transaction._install_artifact
            moved_parent = Path(outside) / "moved-parent"
            raced = False

            def move_parent_before_config(item, *, force):
                nonlocal raced
                if item.artifact.path == "nested/repo-context.toml" and not raced:
                    raced = True
                    repository.path("nested").rename(moved_parent)
                    repository.path("nested").mkdir()
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=move_parent_before_config,
            ):
                outcome = initialization.initialize_repository(
                    repository.root,
                    config_path="nested/repo-context.toml",
                )

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("nested/repo-context.toml").exists())
            self.assertFalse((moved_parent / "repo-context.toml").exists())
            self.assertFalse((moved_parent / "repo-context.debt.json").exists())

    def test_repository_root_renamed_before_install_is_refused(self) -> None:
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory(
            dir=repository.root.parent,
        ) as outside:
            repository.write_text("source.txt", "source\n")
            repository.commit("root rename fixture")
            install = transaction._install_artifact
            moved_root = Path(outside) / "moved-root"
            raced = False

            def move_root_before_install(item, *, force):
                nonlocal raced
                if not raced:
                    raced = True
                    repository.root.rename(moved_root)
                    repository.root.mkdir()
                return install(item, force=force)

            with mock.patch.object(
                transaction,
                "_install_artifact",
                side_effect=move_root_before_install,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse((moved_root / "repo-context.toml").exists())

    def test_repository_root_replaced_before_preparation_is_refused(self) -> None:
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory(
            dir=repository.root.parent,
        ) as outside:
            repository.write_text("source.txt", "source\n")
            repository.commit("preparation root fixture")
            write_artifacts = initialization._write_artifacts
            moved_root = Path(outside) / "moved-root"

            def replace_root_before_prepare(
                root,
                artifacts,
                *,
                root_anchor_fd,
                force,
                absence_guards=(),
            ):
                repository.root.rename(moved_root)
                repository.root.mkdir()
                return write_artifacts(
                    root,
                    artifacts,
                    root_anchor_fd=root_anchor_fd,
                    force=force,
                    absence_guards=absence_guards,
                )

            with mock.patch.object(
                initialization,
                "_write_artifacts",
                side_effect=replace_root_before_prepare,
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, CommandFailure)
            assert isinstance(outcome, CommandFailure)
            self.assertEqual(tuple(item.code for item in outcome.diagnostics), ("INIT002",))
            self.assertFalse(repository.path("repo-context.toml").exists())
            self.assertFalse((moved_root / "repo-context.toml").exists())


if __name__ == "__main__":
    unittest.main()
