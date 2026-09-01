from __future__ import annotations

import contextlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repo_context.inventory import (
    RepositoryAccessError,
    find_base_entry,
    inventory_worktree,
    list_base_tree,
    open_repository,
    read_base_blob,
    resolve_base_revision,
)
from repo_context.model import GitFileMode, GitObjectType, InventorySource, WorktreeKind
from tests.support.repository import RepositoryFixture


class RepositoryRootTests(unittest.TestCase):
    def test_explicit_root_works_from_an_unrelated_current_directory(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.commit()
            with tempfile.TemporaryDirectory() as unrelated:
                with contextlib.chdir(unrelated):
                    handle = open_repository(repository.root)
                    snapshot = inventory_worktree(handle)
            self.assertEqual(handle.root, repository.root.resolve())
            self.assertIn("tracked.txt", tuple(entry.path for entry in snapshot.entries))

    def test_root_symlink_is_accepted_and_canonicalized(self) -> None:
        with RepositoryFixture() as repository:
            try:
                link = repository.symlink("repository-link", ".")
            except OSError as error:
                self.skipTest(f"symlink creation is unavailable: {error}")
            handle = open_repository(link)
            self.assertEqual(handle.root, repository.root.resolve())

    def test_nonexistent_file_subdirectory_and_bare_roots_are_rejected(self) -> None:
        with RepositoryFixture() as repository:
            regular_file = repository.write_text("file.txt", "data")
            subdirectory = repository.path("nested")
            subdirectory.mkdir()
            candidates = (
                repository.path("missing"),
                regular_file,
                subdirectory,
            )
            for candidate in candidates:
                with self.subTest(candidate=candidate):
                    with self.assertRaises(RepositoryAccessError) as raised:
                        open_repository(candidate)
                    self.assertEqual(raised.exception.diagnostics[0].code, "GIT001")

            for invalid_text in ("", "root\x00name"):
                with self.subTest(candidate=invalid_text):
                    with self.assertRaises(RepositoryAccessError) as raised:
                        open_repository(invalid_text)
                    self.assertEqual(raised.exception.diagnostics[0].code, "GIT001")

        with RepositoryFixture(initialize_git=False) as bare:
            bare.git("init", "--quiet", "--bare")
            with self.assertRaises(RepositoryAccessError) as raised:
                open_repository(bare.root)
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT001")

    def test_linked_worktree_is_an_accepted_explicit_root(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.commit()
            with tempfile.TemporaryDirectory(prefix="repo-context-worktree-") as parent:
                linked = Path(parent) / "linked"
                repository.git("worktree", "add", "--quiet", "--detach", str(linked))
                handle = open_repository(linked)
                snapshot = inventory_worktree(handle)
                self.assertEqual(handle.root, linked.resolve())
                self.assertIn("tracked.txt", tuple(entry.path for entry in snapshot.entries))


class WorktreeInventoryTests(unittest.TestCase):
    def test_inventory_models_tracked_untracked_deleted_and_ignored_states(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.write_text("rename-me.txt", "renamed\n")
            repository.write_text("ignored/tracked.txt", "still governed\n")
            repository.commit("tracked state")
            repository.ignore("ignored/", "*.tmp")
            repository.commit("ignore policy")

            repository.delete("tracked.txt")
            repository.rename("rename-me.txt", "moved.txt")
            repository.write_text("visible.txt", "visible\n")
            repository.write_text("ignored/untracked.txt", "ignored\n")
            repository.write_text("ignored.tmp", "ignored\n")
            repository.write_text(".env", "value=1\n")
            repository.write_text("docs/中文.md", "unicode\n")

            snapshot = inventory_worktree(open_repository(repository.root))
            entries = {entry.path: entry for entry in snapshot.entries}

            self.assertEqual(
                tuple(entry.path for entry in snapshot.entries),
                tuple(sorted(entries)),
            )
            self.assertEqual(entries["tracked.txt"].source, InventorySource.DELETED)
            self.assertEqual(entries["tracked.txt"].kind, WorktreeKind.MISSING)
            self.assertEqual(entries["rename-me.txt"].source, InventorySource.DELETED)
            self.assertEqual(entries["moved.txt"].source, InventorySource.UNTRACKED)
            self.assertEqual(entries["visible.txt"].kind, WorktreeKind.REGULAR)
            self.assertEqual(entries["visible.txt"].size_bytes, len(b"visible\n"))
            self.assertEqual(entries["ignored/tracked.txt"].source, InventorySource.TRACKED)
            self.assertIsNotNone(entries["ignored/tracked.txt"].index)
            self.assertIsNone(entries["moved.txt"].index)
            self.assertIn(".env", entries)
            self.assertIn("docs/中文.md", entries)
            self.assertNotIn("ignored/untracked.txt", entries)
            self.assertNotIn("ignored.tmp", entries)

    def test_staged_rename_uses_index_identity_without_rename_heuristics(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("old.txt", "content\n")
            repository.commit()
            repository.git("mv", "old.txt", "new.txt")
            snapshot = inventory_worktree(open_repository(repository.root))
            entries = {entry.path: entry for entry in snapshot.entries}
            self.assertNotIn("old.txt", entries)
            self.assertEqual(entries["new.txt"].source, InventorySource.TRACKED)
            self.assertEqual(entries["new.txt"].kind, WorktreeKind.REGULAR)

    def test_gitlink_is_modeled_without_recursing_into_another_repository(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("seed.txt", "content\n")
            commit_id = repository.commit()
            repository.git(
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                commit_id,
                "vendor/submodule",
            )
            repository.path("vendor/submodule").mkdir(parents=True)
            entries = {
                entry.path: entry
                for entry in inventory_worktree(open_repository(repository.root)).entries
            }
            gitlink = entries["vendor/submodule"]
            self.assertEqual(gitlink.source, InventorySource.TRACKED)
            self.assertEqual(gitlink.kind, WorktreeKind.OTHER)
            self.assertEqual(gitlink.index.mode, GitFileMode.GITLINK)
            self.assertNotIn("vendor/submodule/.git", entries)

    def test_sparse_checkout_skip_worktree_path_is_stably_missing(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("keep/present.txt", "present\n")
            repository.write_text("omit/missing.txt", "missing\n")
            repository.commit()
            initialized = repository.git(
                "sparse-checkout",
                "init",
                "--cone",
                "--sparse-index",
                check=False,
            )
            if initialized.returncode != 0:
                self.skipTest("host Git does not support sparse-index checkout")
            selected = repository.git("sparse-checkout", "set", "keep", check=False)
            if selected.returncode != 0:
                self.skipTest("host Git could not configure the sparse checkout")

            entries = {
                entry.path: entry
                for entry in inventory_worktree(open_repository(repository.root)).entries
            }
            self.assertEqual(entries["keep/present.txt"].kind, WorktreeKind.REGULAR)
            sparse = entries["omit/missing.txt"]
            self.assertEqual(sparse.source, InventorySource.TRACKED)
            self.assertEqual(sparse.kind, WorktreeKind.MISSING)
            self.assertTrue(sparse.index.skip_worktree)

    def test_regular_executable_and_symlink_metadata_are_explicit(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("regular.txt", "regular\n")
            executable = repository.write_text("script.sh", "#!/bin/sh\n")
            if os.name != "nt":
                executable.chmod(0o755)
            try:
                repository.symlink("tracked-link", "../outside-target")
                repository.commit()
                repository.symlink("untracked-link", "regular.txt")
            except OSError as error:
                self.skipTest(f"symlink creation is unavailable: {error}")

            entries = {
                entry.path: entry
                for entry in inventory_worktree(open_repository(repository.root)).entries
            }
            self.assertEqual(entries["regular.txt"].kind, WorktreeKind.REGULAR)
            if os.name != "nt":
                self.assertEqual(entries["script.sh"].index.mode, GitFileMode.EXECUTABLE)
            self.assertEqual(entries["tracked-link"].kind, WorktreeKind.SYMLINK)
            self.assertEqual(entries["tracked-link"].symlink_target, "../outside-target")
            self.assertEqual(entries["tracked-link"].index.mode, GitFileMode.SYMLINK)
            self.assertEqual(entries["untracked-link"].kind, WorktreeKind.SYMLINK)
            self.assertEqual(entries["untracked-link"].symlink_target, "regular.txt")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs are unavailable")
    def test_untracked_special_file_is_not_opened_or_treated_as_regular(self) -> None:
        with RepositoryFixture() as repository:
            os.mkfifo(repository.path("named-pipe"))
            handle = open_repository(repository.root)
            with patch(
                "repo_context.inventory._run_git",
                side_effect=(b"", b"", b"named-pipe\x00"),
            ):
                entries = inventory_worktree(handle).entries
            pipe = next(entry for entry in entries if entry.path == "named-pipe")
            self.assertEqual(pipe.source, InventorySource.UNTRACKED)
            self.assertEqual(pipe.kind, WorktreeKind.OTHER)
            self.assertIsNone(pipe.size_bytes)

    @unittest.skipIf(os.name == "nt", "Windows cannot create these POSIX names")
    def test_nul_framing_preserves_tabs_newlines_unicode_and_sorting(self) -> None:
        with RepositoryFixture() as repository:
            paths = (
                "z-last.txt",
                "line\nbreak.txt",
                "tab\tname.txt",
                "literal*.txt",
                "what?.txt",
                "class[a].txt",
                "中文.txt",
                "a-first.txt",
            )
            for path in reversed(paths):
                repository.write_text(path, path)
            repository.commit()
            first = inventory_worktree(open_repository(repository.root)).entries
            second = inventory_worktree(open_repository(repository.root)).entries
            self.assertEqual(first, second)
            self.assertEqual(
                tuple(entry.path for entry in first),
                tuple(sorted(paths)),
            )


class BaseRevisionTests(unittest.TestCase):
    def test_base_metadata_and_blobs_are_read_without_mutating_repository_state(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("raw.bin", b"raw\x00\xffbytes")
            executable = repository.write_text("script.sh", "#!/bin/sh\nexit 0\n")
            if os.name != "nt":
                executable.chmod(0o755)
            repository.write_text("delete-me.txt", "from base\n")
            if os.name != "nt":
                repository.write_text("line\nbreak.txt", "newline path\n")
            symlink_available = True
            try:
                repository.symlink("base-link", "delete-me.txt")
            except OSError:
                symlink_available = False
            first_commit = repository.commit("base files")
            repository.git(
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                first_commit,
                "vendor/submodule",
            )
            base_commit = repository.git(
                "commit",
                "--quiet",
                "--message",
                "base gitlink",
            )
            self.assertEqual(base_commit.returncode, 0)
            base_commit_id = repository.git("rev-parse", "HEAD").stdout.strip()

            repository.delete("delete-me.txt")
            repository.write_text("new.txt", "not in base\n")
            repository.write_bytes("raw.bin", b"current bytes")
            status_before = repository.status_bytes()
            index_path = repository.git_path("index")
            index_before = index_path.read_bytes()
            worktree_before = {
                "raw.bin": repository.path("raw.bin").read_bytes(),
                "new.txt": repository.path("new.txt").read_bytes(),
            }
            link_before = (
                os.readlink(repository.path("base-link"))
                if symlink_available
                else None
            )

            def assert_repository_bytes_unchanged() -> None:
                self.assertEqual(repository.status_bytes(), status_before)
                self.assertEqual(index_path.read_bytes(), index_before)
                self.assertEqual(
                    {
                        path: repository.path(path).read_bytes()
                        for path in worktree_before
                    },
                    worktree_before,
                )
                self.assertFalse(repository.path("delete-me.txt").exists())
                if symlink_available:
                    self.assertEqual(os.readlink(repository.path("base-link")), link_before)

            handle = open_repository(repository.root)
            revision = resolve_base_revision(handle, base_commit_id)
            assert_repository_bytes_unchanged()
            tree = list_base_tree(handle, revision)
            assert_repository_bytes_unchanged()
            self.assertEqual(tuple(entry.path for entry in tree), tuple(sorted(entry.path for entry in tree)))

            raw = find_base_entry(tree, "raw.bin")
            self.assertIsNotNone(raw)
            assert raw is not None
            self.assertEqual(raw.object_type, GitObjectType.BLOB)
            self.assertEqual(read_base_blob(handle, raw), b"raw\x00\xffbytes")
            assert_repository_bytes_unchanged()

            deleted = find_base_entry(tree, "delete-me.txt")
            self.assertIsNotNone(deleted)
            self.assertIsNone(find_base_entry(tree, "new.txt"))
            script = find_base_entry(tree, "script.sh")
            self.assertIsNotNone(script)
            if os.name != "nt":
                assert script is not None
                self.assertEqual(script.mode, GitFileMode.EXECUTABLE)
            if symlink_available:
                link = find_base_entry(tree, "base-link")
                self.assertIsNotNone(link)
                assert link is not None
                self.assertEqual(link.mode, GitFileMode.SYMLINK)
                self.assertEqual(read_base_blob(handle, link), b"delete-me.txt")
            if os.name != "nt":
                self.assertIsNotNone(find_base_entry(tree, "line\nbreak.txt"))

            gitlink = find_base_entry(tree, "vendor/submodule")
            self.assertIsNotNone(gitlink)
            assert gitlink is not None
            self.assertEqual(gitlink.mode, GitFileMode.GITLINK)
            self.assertEqual(gitlink.object_type, GitObjectType.COMMIT)
            with self.assertRaises(RepositoryAccessError) as raised:
                read_base_blob(handle, gitlink)
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT007")
            assert_repository_bytes_unchanged()

    def test_missing_option_like_and_noncommit_refs_are_base_errors(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("file.txt", "content\n")
            repository.commit()
            blob_id = repository.git("hash-object", "-w", "file.txt").stdout.strip()
            handle = open_repository(repository.root)
            for revision in ("missing-ref", "--not-an-option", blob_id):
                with self.subTest(revision=revision):
                    with self.assertRaises(RepositoryAccessError) as raised:
                        resolve_base_revision(handle, revision)
                    self.assertEqual(raised.exception.diagnostics[0].code, "GIT006")

    def test_base_access_ignores_local_replacement_objects(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("file.txt", "original\n")
            original_commit = repository.commit("original")
            repository.write_text("file.txt", "replacement\n")
            replacement_commit = repository.commit("replacement")
            repository.git("replace", original_commit, replacement_commit)

            handle = open_repository(repository.root)
            revision = resolve_base_revision(handle, original_commit)
            tree = list_base_tree(handle, revision)
            entry = find_base_entry(tree, "file.txt")
            self.assertIsNotNone(entry)
            assert entry is not None
            self.assertEqual(read_base_blob(handle, entry), b"original\n")

    def test_object_ids_are_not_assumed_to_have_sha1_length(self) -> None:
        try:
            repository = RepositoryFixture(object_format="sha256")
        except subprocess.CalledProcessError as error:
            self.skipTest(f"host Git does not support SHA-256 repositories: {error}")
        with repository:
            repository.write_text("file.txt", "content\n")
            commit_id = repository.commit()
            handle = open_repository(repository.root)
            revision = resolve_base_revision(handle, commit_id)
            tree = list_base_tree(handle, revision)
            self.assertEqual(len(revision.commit_id), 64)
            self.assertEqual(len(tree[0].object_id), 64)


if __name__ == "__main__":
    unittest.main()
