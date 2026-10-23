"""Mutable nested Git inputs remain witnessed after administration binding."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raften import inventory
from raften.repository_errors import RepositoryAccessError
from tests.support.repository import RepositoryFixture


class GitRefWitnessTests(unittest.TestCase):
    def test_nested_input_rewrites_are_witnessed_without_directory_changes(self):
        for relative in ("refs/heads/topic/main", "refs/tags/releases/v1", "refs/heads/alias", "reftable/tables.list", "logs/refs/heads/main"):
            with self.subTest(relative=relative), RepositoryFixture() as fixture:
                fixture.write_text("a.txt", "content\n")
                fixture.commit()
                target = fixture.root / ".git" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("ref: refs/heads/main\n" if relative.endswith("alias") else "a" * 40 + "\n")
                handle = inventory.open_repository(fixture.root)
                before = target.parent.stat()
                target.write_text("b" * 40 + "\n")
                after = target.parent.stat()
                self.assertEqual((before.st_mtime_ns, before.st_ctime_ns), (after.st_mtime_ns, after.st_ctime_ns))
                with self.assertRaises(RepositoryAccessError) as caught:
                    handle.administration.verify()
                self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_ref_change_before_resolution_refuses_before_spawn(self):
        with RepositoryFixture() as fixture:
            fixture.write_text("a.txt", "content\n")
            fixture.commit()
            ref = fixture.root / ".git/refs/heads/main"
            handle = inventory.open_repository(fixture.root)
            ref.write_text("a" * 40 + "\n")
            with patch("raften.inventory.subprocess.Popen") as spawn:
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.resolve_base_revision(handle, "main")
                spawn.assert_not_called()
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_restored_ref_write_during_resolution_refuses(self):
        with RepositoryFixture() as fixture:
            fixture.write_text("a.txt", "content\n")
            fixture.commit()
            handle = inventory.open_repository(fixture.root)
            ref = fixture.root / ".git/refs/heads/main"
            original = ref.read_bytes()
            collect = inventory.collect_output
            def rewrite(*args, **kwargs):
                result = collect(*args, **kwargs)
                ref.write_bytes(b"a" * 40 + b"\n")
                ref.write_bytes(original)
                return result
            with patch("raften.inventory.collect_output", side_effect=rewrite):
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.resolve_base_revision(handle, "HEAD")
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_linked_worktree_common_refs_are_witnessed(self):
        with RepositoryFixture() as fixture, tempfile.TemporaryDirectory() as directory:
            fixture.write_text("a.txt", "content\n")
            fixture.commit()
            root = Path(directory) / "linked"
            fixture.git("worktree", "add", "--quiet", "--detach", str(root))
            handle = inventory.open_repository(root)
            (fixture.root / ".git/refs/heads/main").write_text("a" * 40 + "\n")
            with self.assertRaises(RepositoryAccessError) as caught:
                inventory.resolve_base_revision(handle, "main")
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_nested_files_share_metadata_witness_ceiling(self):
        with RepositoryFixture() as fixture:
            fixture.write_text("a.txt", "content\n")
            fixture.commit()
            handle = inventory.open_repository(fixture.root)
            count = sum(w.path.is_file() for w in handle.administration.witnesses)
            target = fixture.root / ".git/refs/heads/deep/topic"
            target.parent.mkdir()
            target.write_text("a" * 40 + "\n")
            with patch("raften.git_administration.MAX_ADMIN_METADATA_FILES", count):
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.open_repository(fixture.root)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")
