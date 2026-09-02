from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from release_tools.source_guard import (
    ReleaseSourceError,
    export_release_source,
    require_clean_release_source,
)
from tests.support.repository import RepositoryFixture


class ReleaseSourceGuardTests(unittest.TestCase):
    def test_clean_commit_exports_exact_blobs_and_omits_ignored_state(self) -> None:
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory() as directory:
            repository.write_text("tracked.txt", "tracked\n")
            repository.ignore("ignored.txt")
            commit_id = repository.commit("release source")
            repository.write_text("ignored.txt", "ignored live state\n")

            source = require_clean_release_source(repository.root)
            destination = Path(directory) / "source"
            export_release_source(source, destination)

            self.assertEqual(source.commit_id, commit_id)
            self.assertGreater(source.commit_timestamp, 0)
            self.assertEqual((destination / "tracked.txt").read_text(), "tracked\n")
            self.assertFalse((destination / "ignored.txt").exists())
            self.assertFalse((destination / ".git").exists())

    def test_dirty_or_changed_source_is_refused(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "base\n")
            commit_id = repository.commit("base")
            with self.assertRaisesRegex(ReleaseSourceError, "commit changed"):
                require_clean_release_source(repository.root, expected_commit="0" * len(commit_id))

            repository.write_text("tracked.txt", "dirty\n")
            with self.assertRaisesRegex(ReleaseSourceError, "clean Git worktree"):
                require_clean_release_source(repository.root)

    def test_non_repository_and_symlink_entries_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ReleaseSourceError):
                require_clean_release_source(Path(directory))

        with RepositoryFixture() as repository, tempfile.TemporaryDirectory() as directory:
            repository.write_text("target.txt", "target\n")
            repository.symlink("linked.txt", "target.txt")
            repository.commit("symlink source")
            source = require_clean_release_source(repository.root)
            with self.assertRaisesRegex(ReleaseSourceError, "unsupported entry"):
                export_release_source(source, Path(directory) / "source")


if __name__ == "__main__":
    unittest.main()
