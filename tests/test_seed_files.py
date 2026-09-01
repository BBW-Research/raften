from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support.repository import (
    RepositoryFixture,
    isolated_process_environment,
    seed_policy,
)
from tests.support.seed import SEED


class SeedGitInventoryTests(unittest.TestCase):
    def test_git_inventory_invokes_nul_delimited_visible_path_command(self) -> None:
        root = Path("/fixture")
        completed = SimpleNamespace(stdout=b"z.txt\0line\nbreak.txt\0a.txt\0")
        with mock.patch.object(SEED.subprocess, "run", return_value=completed) as run:
            paths = SEED.git_paths(root)
        self.assertEqual(paths, ["a.txt", "line\nbreak.txt", "z.txt"])
        run.assert_called_once_with(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
        )

    def test_git_inventory_includes_tracked_untracked_and_deleted_but_not_ignored(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.write_text("deleted.txt", "deleted\n")
            repository.write_text("tracked-then-ignored.txt", "tracked\n")
            repository.write_text("space name.txt", "nul-safe path\n")
            repository.commit("base")
            repository.delete("deleted.txt")
            repository.write_text("untracked.txt", "untracked\n")
            repository.write_text("ignored.txt", "ignored\n")
            repository.ignore("ignored.txt", "tracked-then-ignored.txt")

            with isolated_process_environment():
                paths = SEED.git_paths(repository.root)

        self.assertEqual(paths, sorted(paths))
        self.assertIn("tracked.txt", paths)
        self.assertIn("tracked-then-ignored.txt", paths)
        self.assertIn("deleted.txt", paths)
        self.assertIn("untracked.txt", paths)
        self.assertIn("space name.txt", paths)
        self.assertNotIn("ignored.txt", paths)


class SeedPlaintextTests(unittest.TestCase):
    def test_utf8_text_classification(self) -> None:
        cases = (
            (b"", True),
            (b"plain ASCII\n", True),
            ("指南\n".encode("utf-8"), True),
            (b"\xef\xbb\xbfwith BOM", True),
            (b"line one\r\nline two\r\n", True),
            (b"before\0after", False),
            (b"\xff", False),
            (b"\xe2\x82", False),
        )
        for data, expected in cases:
            with self.subTest(data=data):
                self.assertEqual(SEED.is_utf8_text(data), expected)


class SeedEffectiveLimitTests(unittest.TestCase):
    def test_default_entrypoint_and_document_index_limits(self) -> None:
        policy = seed_policy(
            max_text_bytes=100,
            index_max_bytes=40,
            entrypoint_limits={"README.md": 60, "docs/index.md": 30, "large.md": 200},
            documentation_roots=["docs"],
        )
        cases = (
            ("src/main.py", 100),
            ("README.md", 60),
            ("large.md", 100),
            ("docs/index.md", 30),
            ("docs/guide/index.md", 40),
            ("reference/index.md", 100),
        )
        for path, expected in cases:
            with self.subTest(path=path):
                self.assertEqual(SEED.effective_limit(path, policy), expected)


class SeedSizeCheckTests(unittest.TestCase):
    def test_ordinary_limit_uses_raw_bytes_at_exact_boundary(self) -> None:
        policy = seed_policy(max_text_bytes=4)
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_bytes("exact.txt", b"1234")
            repository.write_bytes("large.txt", b"12345")
            repository.write_bytes("unicode.txt", "ééé".encode("utf-8"))
            repository.write_bytes("crlf.txt", b"a\r\nb\r\n")
            errors, count = SEED.check_sizes(
                repository.root,
                ["exact.txt", "large.txt", "unicode.txt", "crlf.txt"],
                policy,
            )
        self.assertEqual(count, 4)
        self.assertEqual(
            errors,
            [
                "large.txt: 5 bytes exceeds 4; split the file",
                "unicode.txt: 6 bytes exceeds 4; split the file",
                "crlf.txt: 6 bytes exceeds 4; split the file",
            ],
        )

    def test_missing_nonregular_excluded_and_binary_paths_are_skipped(self) -> None:
        policy = seed_policy(text_excluded_globs=["excluded.txt"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("plain.txt", "plain\n")
            repository.write_text("excluded.txt", "excluded\n")
            repository.write_bytes("nul.bin", b"text\0data")
            repository.write_bytes("invalid.bin", b"\xff")
            repository.path("directory").mkdir()
            errors, count = SEED.check_sizes(
                repository.root,
                [
                    "plain.txt",
                    "excluded.txt",
                    "nul.bin",
                    "invalid.bin",
                    "directory",
                    "missing.txt",
                ],
                policy,
            )
        self.assertEqual(errors, [])
        self.assertEqual(count, 1)

    def test_symlink_is_skipped_as_nonregular(self) -> None:
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("plain.txt", "plain\n")
            try:
                repository.symlink("link.txt", "plain.txt")
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            errors, count = SEED.check_sizes(
                repository.root,
                ["link.txt"],
                seed_policy(),
            )
        self.assertEqual(errors, [])
        self.assertEqual(count, 0)

    def test_legacy_file_may_remain_above_ordinary_limit_up_to_ceiling(self) -> None:
        policy = seed_policy(max_text_bytes=4, legacy_oversize={"legacy.txt": 10})
        with RepositoryFixture(initialize_git=False) as repository:
            for size in (5, 10):
                with self.subTest(size=size):
                    repository.write_bytes("legacy.txt", b"x" * size)
                    self.assertEqual(
                        SEED.check_sizes(repository.root, ["legacy.txt"], policy),
                        ([], 1),
                    )

    def test_legacy_file_above_ceiling_fails(self) -> None:
        policy = seed_policy(max_text_bytes=4, legacy_oversize={"legacy.txt": 10})
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_bytes("legacy.txt", b"x" * 11)
            errors, count = SEED.check_sizes(repository.root, ["legacy.txt"], policy)
        self.assertEqual(count, 1)
        self.assertEqual(errors, ["legacy.txt: 11 bytes exceeds legacy ceiling 10"])

    def test_legacy_file_within_ordinary_limit_must_drop_ceiling(self) -> None:
        policy = seed_policy(max_text_bytes=4, legacy_oversize={"legacy.txt": 10})
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_bytes("legacy.txt", b"1234")
            errors, count = SEED.check_sizes(repository.root, ["legacy.txt"], policy)
        self.assertEqual(count, 1)
        self.assertEqual(errors, ["legacy.txt: now within 4 bytes; remove its legacy ceiling"])

    def test_invalid_or_unresolved_legacy_entries_fail(self) -> None:
        policy = seed_policy(
            max_text_bytes=4,
            text_excluded_globs=["excluded.txt"],
            legacy_oversize={
                "too-low.txt": 4,
                "missing.txt": 10,
                "excluded.txt": 10,
                "binary.bin": 10,
            },
        )
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("excluded.txt", "excluded")
            repository.write_bytes("binary.bin", b"\0")
            errors, count = SEED.check_sizes(
                repository.root,
                ["excluded.txt", "binary.bin"],
                policy,
            )
        self.assertEqual(count, 0)
        self.assertIn("too-low.txt: legacy ceiling must exceed its ordinary limit", errors)
        for path in ("too-low.txt", "missing.txt", "excluded.txt", "binary.bin"):
            self.assertIn(
                f"{path}: legacy ceiling points to a missing, excluded, or non-text file",
                errors,
            )

    def test_seed_manual_ceiling_allows_regrowth_after_partial_reduction(self) -> None:
        policy = seed_policy(max_text_bytes=25, legacy_oversize={"legacy.txt": 100})
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_bytes("legacy.txt", b"x" * 60)
            reduced = SEED.check_sizes(repository.root, ["legacy.txt"], policy)
            repository.write_bytes("legacy.txt", b"x" * 61)
            regrown = SEED.check_sizes(repository.root, ["legacy.txt"], policy)
        self.assertEqual(reduced, ([], 1))
        self.assertEqual(regrown, ([], 1))


if __name__ == "__main__":
    unittest.main()
