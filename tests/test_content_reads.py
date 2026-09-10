from __future__ import annotations

import errno
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import raften.worktree as worktree_module
from raften.inventory import (
    RepositoryAccessError,
    inventory_worktree,
    open_repository,
    read_worktree_bytes,
)
from raften.model import InventoryEntry, InventorySource, WorktreeKind
from tests.support.repository import RepositoryFixture


def entries_by_path(repository: RepositoryFixture):
    handle = open_repository(repository.root)
    snapshot = inventory_worktree(handle)
    return handle, {entry.path: entry for entry in snapshot.entries}


class SnapshotContentReadTests(unittest.TestCase):
    def test_descriptor_read_is_bounded_to_snapshot_size_plus_one(self) -> None:
        with tempfile.TemporaryFile() as stream:
            stream.write(b"x" * 100)
            stream.seek(0)
            data = worktree_module._read_descriptor(stream.fileno(), 5)
        self.assertEqual(data, b"x" * 6)

    def test_tracked_and_untracked_bytes_share_the_public_inventory_boundary(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("tracked.bin", b"tracked\x00bytes")
            repository.commit()
            repository.write_bytes("nested/untracked.txt", "你好\r\n".encode())
            handle, entries = entries_by_path(repository)

            self.assertEqual(
                read_worktree_bytes(handle, entries["tracked.bin"]),
                b"tracked\x00bytes",
            )
            self.assertEqual(
                read_worktree_bytes(handle, entries["nested/untracked.txt"]),
                "你好\r\n".encode(),
            )
            for path in ("tracked.bin", "nested/untracked.txt"):
                identity = entries[path].identity
                self.assertIsNotNone(identity)
                self.assertEqual(identity.size_bytes, entries[path].size_bytes)

    def test_same_size_path_replacement_after_inventory_is_git005(self) -> None:
        with RepositoryFixture() as repository:
            original = repository.write_bytes("replace.txt", b"first\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            replacement = repository.write_bytes("replacement.tmp", b"other\n")
            os.replace(replacement, original)

            with self.assertRaises(RepositoryAccessError) as raised:
                read_worktree_bytes(handle, entries["replace.txt"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")
            self.assertEqual(raised.exception.diagnostics[0].location.path, "replace.txt")

    def test_same_inode_rewrite_after_inventory_is_git005(self) -> None:
        with RepositoryFixture() as repository:
            target = repository.write_bytes("rewrite.txt", b"alpha\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            target.write_bytes(b"omega\n")
            identity = entries["rewrite.txt"].identity
            os.utime(
                target,
                ns=(identity.modified_ns + 1_000_000_000,) * 2,
            )

            with self.assertRaises(RepositoryAccessError) as raised:
                read_worktree_bytes(handle, entries["rewrite.txt"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    def test_change_during_an_open_read_is_git005(self) -> None:
        with RepositoryFixture() as repository:
            target = repository.write_bytes("changing.txt", b"alpha\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            original_read = worktree_module._read_descriptor

            def mutate_then_read(descriptor: int, expected_size: int) -> bytes:
                target.write_bytes(b"omega\n")
                return original_read(descriptor, expected_size)

            with patch(
                "raften.worktree._read_descriptor",
                side_effect=mutate_then_read,
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["changing.txt"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    def test_path_replacement_after_descriptor_read_is_git005(self) -> None:
        with RepositoryFixture() as repository:
            target = repository.write_bytes("moving.txt", b"alpha\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            replacement = repository.write_bytes("new.tmp", b"omega\n")
            original_read = worktree_module._read_descriptor

            def read_then_replace(descriptor: int, expected_size: int) -> bytes:
                data = original_read(descriptor, expected_size)
                os.replace(replacement, target)
                return data

            with patch(
                "raften.worktree._read_descriptor",
                side_effect=read_then_replace,
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["moving.txt"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    def test_leaf_symlink_replacement_is_not_followed(self) -> None:
        with RepositoryFixture() as repository:
            target = repository.write_bytes("safe.txt", b"inside\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            with tempfile.TemporaryDirectory(prefix="raften-external-") as external:
                secret = Path(external, "secret.txt")
                secret.write_bytes(b"outside-secret\n")
                target.unlink()
                try:
                    target.symlink_to(secret)
                except OSError as error:
                    self.skipTest(f"symlink creation is unavailable: {error}")
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["safe.txt"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs are unavailable")
    def test_fifo_replacement_between_identity_check_and_open_does_not_block(self) -> None:
        with RepositoryFixture() as repository:
            target = repository.write_bytes("pipe-race", b"regular\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            original_check = worktree_module._require_current_identity
            checks = 0

            def replace_after_check(root, entry, operation):
                nonlocal checks
                original_check(root, entry, operation)
                checks += 1
                if checks == 1:
                    target.unlink()
                    os.mkfifo(target)

            with patch(
                "raften.worktree._require_current_identity",
                side_effect=replace_after_check,
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["pipe-race"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    def test_type_change_with_an_unusual_open_errno_is_classified_as_git005(self) -> None:
        with RepositoryFixture() as repository:
            target = repository.write_bytes("type-race", b"regular\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            unusual_errno = getattr(errno, "EOPNOTSUPP", errno.EACCES)

            def replace_then_fail(_root, _path):
                target.unlink()
                target.mkdir()
                raise OSError(unusual_errno, "unsupported leaf type")

            with patch(
                "raften.worktree._open_snapshot_file",
                side_effect=replace_then_fail,
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["type-race"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    def test_intermediate_symlink_replacement_is_not_followed(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("parent/file.txt", b"inside\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            repository.path("parent").rename(repository.path("original-parent"))
            with tempfile.TemporaryDirectory(prefix="raften-external-") as external:
                Path(external, "file.txt").write_bytes(b"outside-secret\n")
                try:
                    repository.path("parent").symlink_to(external, target_is_directory=True)
                except OSError as error:
                    self.skipTest(f"symlink creation is unavailable: {error}")
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["parent/file.txt"])
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT005")

    def test_open_permission_failure_is_git009(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("blocked.txt", b"content\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            failure = PermissionError(errno.EACCES, "blocked")
            with patch("raften.worktree._open_snapshot_file", side_effect=failure):
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["blocked.txt"])
            diagnostic = raised.exception.diagnostics[0]
            self.assertEqual(diagnostic.code, "GIT009")
            self.assertEqual(dict(diagnostic.details)["operation"], "open")

    def test_reader_fails_closed_when_secure_no_follow_open_is_unavailable(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("content.txt", b"content\n")
            repository.commit()
            handle, entries = entries_by_path(repository)
            with patch.object(worktree_module.os, "supports_dir_fd", set()):
                with self.assertRaises(RepositoryAccessError) as raised:
                    read_worktree_bytes(handle, entries["content.txt"])
            diagnostic = raised.exception.diagnostics[0]
            self.assertEqual(diagnostic.code, "GIT009")
            self.assertEqual(dict(diagnostic.details)["operation"], "open")

    def test_reader_rejects_records_without_regular_snapshot_identity(self) -> None:
        with RepositoryFixture() as repository:
            handle = open_repository(repository.root)
            cases = (
                InventoryEntry("link", InventorySource.TRACKED, WorktreeKind.SYMLINK),
                InventoryEntry("file", InventorySource.TRACKED, WorktreeKind.REGULAR, 1),
            )
            for entry in cases:
                with self.subTest(kind=entry.kind):
                    with self.assertRaises(ValueError):
                        read_worktree_bytes(handle, entry)


if __name__ == "__main__":
    unittest.main()
