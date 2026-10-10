"""Git input provenance must remain bound to the selected worktree."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raften import inventory
from raften.repository_errors import RepositoryAccessError
from tests.support.repository import RepositoryFixture


class GitAdministrationTests(unittest.TestCase):
    def test_unrelated_gitfile_and_symlink_fail_before_spawning_git(self):
        with RepositoryFixture() as external, tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            entry = root / ".git"
            for kind in ("gitfile", "symlink"):
                with self.subTest(kind=kind):
                    if kind == "gitfile":
                        entry.write_text(f"gitdir: {external.root / '.git'}\n")
                    else:
                        entry.symlink_to(external.root / ".git", target_is_directory=True)
                    with patch("raften.inventory.subprocess.Popen") as spawn:
                        with self.assertRaises(RepositoryAccessError) as caught:
                            inventory.open_repository(root)
                        spawn.assert_not_called()
                    self.assertEqual(caught.exception.diagnostics[0].code, "GIT001")
                    entry.unlink()

    def test_linked_worktree_requires_its_exact_registration_backlink(self):
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory() as directory:
            repository.write_text("a.txt", "content\n")
            repository.commit()
            root = Path(directory) / "linked"
            repository.git("worktree", "add", "--quiet", "--detach", str(root))
            handle = inventory.open_repository(root)
            self.assertEqual(tuple(e.path for e in inventory.inventory_worktree(handle).entries), ("a.txt",))
            gitdir = Path((root / ".git").read_text().strip().removeprefix("gitdir: "))
            (gitdir / "gitdir").write_text(str(repository.root / ".git") + "\n")
            with patch("raften.inventory.subprocess.Popen") as spawn:
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.open_repository(root)
                spawn.assert_not_called()
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT001")

    def test_administration_replacement_before_inventory_and_base_reads_refuses(self):
        for operation in ("inventory", "base"):
            with self.subTest(operation=operation), RepositoryFixture() as repository:
                repository.write_text("a.txt", "content\n")
                repository.commit()
                handle = inventory.open_repository(repository.root)
                revision = inventory.resolve_base_revision(handle, "HEAD")
                blob = next(e for e in inventory.list_base_tree(handle, revision) if e.path == "a.txt")
                gitdir = repository.root / ".git"
                gitdir.rename(repository.root / "held")
                gitdir.mkdir()
                with patch("raften.inventory.subprocess.Popen") as spawn:
                    with self.assertRaises(RepositoryAccessError) as caught:
                        if operation == "inventory":
                            inventory.inventory_worktree(handle)
                        else:
                            inventory.read_base_blob(handle, blob)
                    spawn.assert_not_called()
                self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_out_and_back_replacement_during_child_is_detected(self):
        with RepositoryFixture() as repository:
            handle = inventory.open_repository(repository.root)
            collect = inventory.collect_output
            def replace(*args, **kwargs):
                result = collect(*args, **kwargs)
                live = repository.root / ".git"
                held = repository.root / "held"
                live.rename(held)
                live.mkdir()
                live.rmdir()
                held.rename(live)
                return result
            with patch("raften.inventory.collect_output", side_effect=replace):
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.inventory_worktree(handle)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_git_input_symlinks_and_object_alternates_are_rejected(self):
        for relative in ("HEAD", "index", "refs/heads/main", "objects/aa/object", "objects/pack/file.pack"):
            with self.subTest(relative=relative), RepositoryFixture() as repository:
                target = repository.root / ".git" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.unlink(missing_ok=True)
                target.symlink_to(repository.root / "external")
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.open_repository(repository.root)
                self.assertEqual(caught.exception.diagnostics[0].code, "GIT001")
        with RepositoryFixture() as repository:
            repository.write_text(".git/objects/info/alternates", "/external/objects\n")
            with self.assertRaises(RepositoryAccessError) as caught:
                inventory.open_repository(repository.root)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT001")

    def test_linked_pointer_mutation_and_in_place_alternates_mutation_refuse(self):
        for name in ("commondir", "gitdir"):
            with self.subTest(name=name), RepositoryFixture() as repository, tempfile.TemporaryDirectory() as directory:
                repository.write_text("a.txt", "content\n")
                repository.commit()
                root = Path(directory) / "linked"
                repository.git("worktree", "add", "--quiet", "--detach", str(root))
                handle = inventory.open_repository(root)
                pointer = handle.administration.gitdir / name
                pointer.write_text("/unrelated\n")
                with patch("raften.inventory.subprocess.Popen") as spawn:
                    with self.assertRaises(RepositoryAccessError) as caught:
                        inventory.inventory_worktree(handle)
                    spawn.assert_not_called()
                self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")
        with RepositoryFixture() as repository:
            repository.write_text(".git/objects/info/alternates", "")
            handle = inventory.open_repository(repository.root)
            repository.write_text(".git/objects/info/alternates", "/external\n")
            with self.assertRaises(RepositoryAccessError) as caught:
                inventory.inventory_worktree(handle)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_pointer_and_administration_scan_have_independent_bounds(self):
        with RepositoryFixture() as repository:
            with patch("raften.git_administration.MAX_ADMIN_ENTRIES", 1):
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.open_repository(repository.root)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".git").write_text("gitdir: " + "x" * 40)
            with patch("raften.git_administration.MAX_POINTER_BYTES", 32), \
                    patch("raften.git_administration.os.read") as read:
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.open_repository(directory)
                read.assert_not_called()
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")

    def test_root_only_handle_cannot_bypass_administration_validation(self):
        with RepositoryFixture() as repository:
            with patch("raften.inventory.subprocess.Popen") as spawn:
                with self.assertRaises(RepositoryAccessError):
                    inventory.inventory_worktree(inventory.RepositoryHandle(repository.root))
                spawn.assert_not_called()

    def test_bound_administration_cannot_be_reused_for_a_different_root(self):
        with RepositoryFixture() as repository, RepositoryFixture() as decoy:
            original = inventory.open_repository(repository.root)
            handle = inventory.RepositoryHandle(decoy.root.resolve(), original.administration)
            with patch("raften.inventory.subprocess.Popen") as spawn:
                with self.assertRaises(RepositoryAccessError):
                    inventory.inventory_worktree(handle)
                spawn.assert_not_called()

    def test_split_index_freshening_preserves_binding_and_replacement_still_refuses(self):
        with RepositoryFixture() as repository:
            repository.write_text("a.txt", "content\n")
            repository.commit()
            repository.git("update-index", "--split-index")
            shared = next((repository.root / ".git").glob("sharedindex.*"))
            os.utime(shared, (1, 1))
            before = shared.read_bytes()
            handle = inventory.open_repository(repository.root)
            snapshot = inventory.inventory_worktree(handle)
            self.assertEqual(tuple(e.path for e in snapshot.entries), ("a.txt",))
            self.assertEqual(shared.read_bytes(), before)
            held = shared.with_name("held-index")
            shared.rename(held)
            shared.write_bytes(before)
            with self.assertRaises(RepositoryAccessError) as caught:
                inventory.inventory_worktree(handle)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")

    def test_restored_root_or_ancestor_cannot_supply_foreign_git_results(self):
        for ancestor in (False, True):
            for operation in ("inventory", "revision", "tree", "blob"):
                with self.subTest(ancestor=ancestor, operation=operation), \
                        RepositoryFixture() as repository, RepositoryFixture() as decoy, \
                        tempfile.TemporaryDirectory() as directory:
                    arena = Path(directory).resolve()
                    for name, fixture, value in (("live", repository, "original"), ("decoy", decoy, "foreign")):
                        parent = arena / name
                        parent.mkdir()
                        fixture.root.rename(parent / "repo")
                        fixture.root = parent / "repo"
                        fixture.write_text("a.txt", value + "\n")
                        fixture.commit()
                    handle = inventory.open_repository(repository.root)
                    revision = inventory.resolve_base_revision(handle, "HEAD")
                    blob = next(e for e in inventory.list_base_tree(handle, revision) if e.path == "a.txt")
                    live = repository.root.parent if ancestor else repository.root
                    foreign = decoy.root.parent if ancestor else decoy.root
                    held = live.with_name("held")
                    real_spawn, real_collect = inventory.subprocess.Popen, inventory.collect_output
                    swapped = False
                    def restore():
                        nonlocal swapped
                        if swapped:
                            live.rename(foreign)
                            held.rename(live)
                            swapped = False
                    def spawn(*args, **kwargs):
                        nonlocal swapped
                        live.rename(held)
                        foreign.rename(live)
                        swapped = True
                        return real_spawn(*args, **kwargs)
                    def collect(*args, **kwargs):
                        result = real_collect(*args, **kwargs)
                        restore()
                        return result
                    try:
                        with patch("raften.inventory.subprocess.Popen", side_effect=spawn), \
                                patch("raften.inventory.collect_output", side_effect=collect):
                            with self.assertRaises(RepositoryAccessError) as caught:
                                if operation == "inventory":
                                    inventory.inventory_worktree(handle)
                                elif operation == "revision":
                                    inventory.resolve_base_revision(handle, "HEAD")
                                elif operation == "tree":
                                    inventory.list_base_tree(handle, revision)
                                else:
                                    inventory.read_base_blob(handle, blob)
                        self.assertEqual(caught.exception.diagnostics[0].code, "GIT005")
                    finally:
                        restore()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "requires POSIX FIFO")
    def test_gitfile_special_file_fails_without_opening_or_spawning(self):
        with tempfile.TemporaryDirectory() as directory:
            os.mkfifo(Path(directory) / ".git")
            with patch("raften.inventory.subprocess.Popen") as spawn:
                with self.assertRaises(RepositoryAccessError):
                    inventory.open_repository(directory)
                spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
