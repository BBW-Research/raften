from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raften.inventory import (
    RepositoryAccessError,
    RepositoryHandle,
    decode_git_path,
    inventory_worktree,
    list_base_tree,
    open_repository,
)
from raften.model import BaseRevision, GitFileMode, GitObjectType
from tests.support.repository import RepositoryFixture


class GitOutputValidationTests(unittest.TestCase):
    def test_git_paths_decode_strict_utf8_without_normalization(self) -> None:
        self.assertEqual(
            decode_git_path("é\tname".encode(), operation="test", index=2),
            "é\tname",
        )
        with self.assertRaises(RepositoryAccessError) as raised:
            decode_git_path(b"bad-\xff", operation="test", index=3)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")
        self.assertEqual(dict(raised.exception.diagnostics[0].details)["record_index"], 3)

    def test_unsafe_git_paths_receive_a_stable_diagnostic(self) -> None:
        for raw_path in (
            b"/absolute",
            b"../escape",
            b"dir//file",
            b"C:/drive",
            b"dir/C:relative",
            b"dir/C:/drive",
        ):
            with self.subTest(raw_path=raw_path):
                with self.assertRaises(RepositoryAccessError) as raised:
                    decode_git_path(raw_path, operation="test", index=0)
                self.assertEqual(raised.exception.diagnostics[0].code, "GIT004")

    def test_malformed_non_nul_index_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch(
                "raften.inventory._run_git",
            return_value=b"H 100644 " + b"a" * 40 + b" 0\tfile.txt",
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_unmerged_index_stage_is_rejected_without_guessing(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("conflict.txt", "base\n")
            repository.commit("base")
            repository.git("checkout", "--quiet", "-b", "side")
            repository.write_text("conflict.txt", "side\n")
            repository.commit("side")
            repository.git("checkout", "--quiet", "main")
            repository.write_text("conflict.txt", "main\n")
            repository.commit("main")
            merge = repository.git("merge", "side", check=False)
            self.assertNotEqual(merge.returncode, 0)
            with self.assertRaises(RepositoryAccessError) as raised:
                inventory_worktree(open_repository(repository.root))
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT008")

    @unittest.skipIf(
        os.name == "nt" or sys.platform == "darwin",
        "host filesystem cannot create arbitrary non-UTF-8 names",
    )
    def test_non_utf8_git_filename_is_a_deterministic_operational_error(self) -> None:
        with RepositoryFixture() as repository:
            raw_path = os.fsencode(repository.root) + b"/invalid-\xff.txt"
            descriptor = os.open(raw_path, os.O_WRONLY | os.O_CREAT, 0o644)
            try:
                os.write(descriptor, b"content")
            finally:
                os.close(descriptor)
            repository.git_bytes("add", "--all")
            with self.assertRaises(RepositoryAccessError) as raised:
                inventory_worktree(open_repository(repository.root))
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_duplicate_or_cross_source_path_is_malformed_git_output(self) -> None:
        object_id = b"a" * 40
        index_record = b"H 100644 " + object_id + b" 0\tfile.txt\x00"
        output_sets = (
            (index_record + index_record,),
            (index_record, b"", b"file.txt\x00"),
        )
        for outputs in output_sets:
            with self.subTest(outputs=len(outputs)):
                if len(outputs) == 1:
                    side_effect = [outputs[0]]
                else:
                    side_effect = list(outputs)
                with tempfile.TemporaryDirectory() as directory:
                    handle = RepositoryHandle(Path(directory))
                    with patch("raften.inventory._run_git", side_effect=side_effect):
                        with self.assertRaises(RepositoryAccessError) as raised:
                            inventory_worktree(handle)
                self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_base_tree_records_are_validated_and_sorted_independent_of_git_order(self) -> None:
        object_id = b"a" * 40
        reversed_tree = (
            b"100644 blob " + object_id + b"\tz.txt\x00"
            b"040000 tree " + object_id + b"\tnested\x00"
            b"100644 blob " + object_id + b"\ta.txt\x00"
        )
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            revision = BaseRevision("main", "b" * 40)
            with patch("raften.inventory._run_git", return_value=reversed_tree) as run:
                entries = list_base_tree(handle, revision)
            self.assertEqual(tuple(entry.path for entry in entries), ("a.txt", "nested", "z.txt"))
            self.assertEqual(entries[1].mode, GitFileMode.TREE)
            self.assertEqual(entries[1].object_type, GitObjectType.TREE)
            self.assertEqual(
                run.call_args.kwargs["arguments"],
                ("ls-tree", "-r", "-t", "-z", "--full-tree", revision.commit_id),
            )
            with patch(
                "raften.inventory._run_git",
                return_value=reversed_tree[:-1],
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    list_base_tree(handle, revision)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_tree_mode_is_rejected_in_current_index_records(self) -> None:
        record = b"H 040000 " + b"a" * 40 + b" 0\tdirectory\x00"
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch(
                "raften.inventory._run_git",
                side_effect=(record, b"", b""),
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_failure_evaluation_is_globally_path_sorted_across_sources(self) -> None:
        object_id = b"a" * 40
        tracked_z = b"H 100644 " + object_id + b" 0\tz.txt\x00"
        untracked_a = b"a.txt\x00"
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch(
                "raften.inventory._run_git",
                side_effect=(tracked_z, b"", untracked_a),
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
        diagnostic = raised.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "GIT005")
        self.assertEqual(diagnostic.location.path, "a.txt")
        self.assertEqual(dict(diagnostic.details)["listed_source"], "untracked")


if __name__ == "__main__":
    unittest.main()
