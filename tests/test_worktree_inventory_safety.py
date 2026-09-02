from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import repo_context.worktree as worktree_module
from repo_context.inventory import (
    RepositoryAccessError,
    RepositoryHandle,
    inventory_worktree,
    open_repository,
    worktree_path,
)
from tests.support.repository import RepositoryFixture


class WorktreeRaceAndSafetyTests(unittest.TestCase):
    def test_worktree_join_rejects_nested_drive_components_on_every_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            for path in ("dir/C:relative", "dir/C:/absolute"):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        worktree_path(handle, path)

    def test_untracked_path_disappearing_after_listing_is_git005(self) -> None:
        with RepositoryFixture() as repository:
            disappearing = repository.write_text("disappearing.txt", "content\n")
            original_lstat = worktree_module._lstat

            def fail_one(path: Path) -> os.stat_result:
                if path.name == disappearing.name:
                    raise FileNotFoundError(path)
                return original_lstat(path)

            with patch("repo_context.worktree._lstat", side_effect=fail_one):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(open_repository(repository.root))
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")
            self.assertEqual(raised.exception.diagnostics[0].location.path, "disappearing.txt")

    def test_filesystem_inspection_failure_is_git009(self) -> None:
        with RepositoryFixture() as repository:
            unreadable = repository.write_text("unreadable.txt", "content\n")
            original_lstat = worktree_module._lstat

            def fail_one(path: Path) -> os.stat_result:
                if path.name == unreadable.name:
                    raise PermissionError(path)
                return original_lstat(path)

            with patch("repo_context.worktree._lstat", side_effect=fail_one):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(open_repository(repository.root))
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT009")

    def test_symlink_target_permission_failure_is_git009_not_a_race(self) -> None:
        with RepositoryFixture() as repository:
            try:
                repository.symlink("link", "target")
            except OSError as error:
                self.skipTest(f"symlink creation is unavailable: {error}")
            handle = open_repository(repository.root)
            with patch("repo_context.worktree.os.readlink", side_effect=PermissionError()):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
            diagnostic = raised.exception.diagnostics[0]
            self.assertEqual(diagnostic.code, "GIT009")
            self.assertEqual(dict(diagnostic.details)["operation"], "readlink")

    def test_intermediate_symlink_is_never_followed_outside_the_repository(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("parent/file.txt", "inside\n")
            repository.commit()
            repository.delete("parent/file.txt")
            repository.path("parent").rmdir()
            with tempfile.TemporaryDirectory() as external:
                Path(external, "file.txt").write_text("outside\n", encoding="utf-8")
                try:
                    repository.path("parent").symlink_to(external, target_is_directory=True)
                except OSError as error:
                    self.skipTest(f"symlink creation is unavailable: {error}")
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(open_repository(repository.root))
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")
            self.assertEqual(raised.exception.diagnostics[0].location.path, "parent/file.txt")

    def test_intermediate_windows_junction_shape_is_rejected_before_leaf_access(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("parent/file.txt", "inside\n")
            repository.commit()
            handle = open_repository(repository.root)
            with patch(
                "repo_context.worktree._is_junction",
                side_effect=lambda path: path.name == "parent",
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")
            self.assertEqual(raised.exception.diagnostics[0].location.path, "parent/file.txt")

    def test_tracked_missing_path_is_a_deletion_not_a_race(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("deleted.txt", "content\n")
            repository.commit()
            repository.delete("deleted.txt")
            entry = next(
                item
                for item in inventory_worktree(open_repository(repository.root)).entries
                if item.path == "deleted.txt"
            )
            self.assertEqual(entry.source.value, "deleted")
            self.assertEqual(entry.kind.value, "missing")


if __name__ == "__main__":
    unittest.main()
