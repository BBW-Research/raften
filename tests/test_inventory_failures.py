from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import repo_context.worktree as worktree_module
from repo_context.inventory import (
    RepositoryAccessError,
    RepositoryHandle,
    decode_git_path,
    inventory_worktree,
    list_base_tree,
    open_repository,
    worktree_path,
)
from repo_context.model import BaseRevision
from tests.support.repository import RepositoryFixture


class GitBoundaryTests(unittest.TestCase):
    def test_git_is_invoked_with_argv_binary_streams_and_isolated_environment(self) -> None:
        discovered_git = shutil.which("git")
        self.assertIsNotNone(discovered_git)
        trusted_git = Path(discovered_git).resolve()
        hostile = {
            "GIT_DIR": "/redirected/repository",
            "GIT_WORK_TREE": "/redirected/worktree",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.excludesFile",
            "GIT_CONFIG_VALUE_0": "/redirected/ignore",
            "LC_ALL": "hostile-locale",
            "PATH": f".{os.pathsep}{trusted_git.parent}",
        }
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=b"true\n\n",
            stderr=b"",
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, hostile, clear=False):
                with patch("repo_context.inventory.subprocess.run", return_value=completed) as run:
                    handle = open_repository(directory)

        arguments = run.call_args.args[0]
        options = run.call_args.kwargs
        self.assertEqual(
            arguments,
            [
                str(trusted_git),
                "-c",
                f"core.excludesFile={os.devnull}",
                "-c",
                f"core.fsmonitor={os.devnull}",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "core.untrackedCache=false",
                "rev-parse",
                "--is-inside-work-tree",
                "--show-prefix",
            ],
        )
        self.assertEqual(options["cwd"], handle.root)
        self.assertIs(options["stdin"], subprocess.DEVNULL)
        self.assertIs(options["stdout"], subprocess.PIPE)
        self.assertIs(options["stderr"], subprocess.PIPE)
        self.assertNotIn("GIT_DIR", options["env"])
        self.assertNotIn("GIT_WORK_TREE", options["env"])
        self.assertEqual(options["env"]["GIT_CONFIG_COUNT"], "0")
        self.assertEqual(options["env"]["LC_ALL"], "C")
        self.assertEqual(options["env"]["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(options["env"]["GIT_NO_REPLACE_OBJECTS"], "1")
        self.assertEqual(options["env"]["GIT_OPTIONAL_LOCKS"], "0")
        self.assertEqual(options["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(options["env"]["NoDefaultCurrentDirectoryInExePath"], "1")
        self.assertEqual(options["env"]["PATH"], str(trusted_git.parent))

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shell")
    def test_repository_path_entries_cannot_select_a_repository_git_program(self) -> None:
        discovered_git = shutil.which("git")
        self.assertIsNotNone(discovered_git)
        trusted_directory = Path(discovered_git).resolve().parent
        with RepositoryFixture() as repository:
            marker = repository.path("repository-git-executed")
            malicious_git = repository.write_text(
                "git",
                "#!/bin/sh\n: > repository-git-executed\nprintf 'true\\n\\n'\n",
            )
            malicious_git.chmod(0o755)
            with tempfile.TemporaryDirectory() as external:
                alias = Path(external) / "repository-bin"
                alias.symlink_to(repository.root, target_is_directory=True)
                linked_executable_directory = Path(external) / "linked-executable"
                linked_executable_directory.mkdir()
                (linked_executable_directory / "git").symlink_to(malicious_git)
                unsafe_entries = (
                    ".",
                    "",
                    str(repository.root),
                    str(alias),
                    str(linked_executable_directory),
                )
                for unsafe_entry in unsafe_entries:
                    with self.subTest(unsafe_entry=unsafe_entry or "empty"):
                        search_path = os.pathsep.join(
                            (unsafe_entry, str(trusted_directory))
                        )
                        with patch.dict(os.environ, {"PATH": search_path}):
                            handle = open_repository(repository.root)
                        self.assertEqual(handle.root, repository.root.resolve())
                        self.assertFalse(marker.exists())

            with patch.dict(os.environ, {"PATH": "."}):
                with self.assertRaises(RepositoryAccessError) as raised:
                    open_repository(repository.root)
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT002")
            self.assertFalse(marker.exists())

    def test_inventory_commands_use_nul_modes_and_explicit_cwd(self) -> None:
        outputs = (
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, b"", b""),
            subprocess.CompletedProcess([], 0, b"", b""),
        )
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory).resolve())
            with patch("repo_context.inventory.subprocess.run", side_effect=outputs) as run:
                snapshot = inventory_worktree(handle)
        self.assertEqual(snapshot.entries, ())
        commands = [call.args[0][9:] for call in run.call_args_list]
        self.assertEqual(
            commands,
            [
                ["ls-files", "--stage", "-t", "-z"],
                ["ls-files", "--deleted", "-z"],
                ["ls-files", "--others", "--exclude-standard", "-z"],
            ],
        )
        self.assertTrue(all(call.kwargs["cwd"] == handle.root for call in run.call_args_list))

    def test_hostile_ambient_git_state_and_global_ignores_do_not_change_inventory(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.commit()
            repository.ignore("*.local")
            repository.write_text("visible.ambient", "visible\n")
            repository.write_text("hidden.local", "local ignore\n")
            repository.path(".git/info/exclude").write_text(
                "*.info\n",
                encoding="utf-8",
            )
            repository.write_text("hidden.info", "info ignore\n")
            with tempfile.TemporaryDirectory() as external:
                global_ignore = Path(external) / "global-ignore"
                global_ignore.write_text("*.ambient\n", encoding="utf-8")
                hostile = {
                    "GIT_DIR": str(Path(external) / "not-a-repository"),
                    "GIT_WORK_TREE": external,
                    "GIT_CONFIG_GLOBAL": str(global_ignore),
                    "GIT_CONFIG_COUNT": "1",
                    "GIT_CONFIG_KEY_0": "core.excludesFile",
                    "GIT_CONFIG_VALUE_0": str(global_ignore),
                    "LC_ALL": "invalid-locale",
                }
                with patch.dict(os.environ, hostile, clear=False):
                    entries = inventory_worktree(open_repository(repository.root)).entries
            paths = tuple(entry.path for entry in entries)
            self.assertIn("visible.ambient", paths)
            self.assertNotIn("hidden.local", paths)
            self.assertNotIn("hidden.info", paths)

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shell")
    def test_repository_fsmonitor_program_is_never_executed(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.commit()
            marker = repository.path("fsmonitor-executed")
            monitor = repository.write_text(
                "fsmonitor-hook",
                "#!/bin/sh\n: > fsmonitor-executed\n",
            )
            monitor.chmod(0o755)
            repository.git("config", "core.fsmonitor", str(monitor))
            repository.write_text("untracked.txt", "untracked\n")
            index_before = repository.path(".git/index").read_bytes()
            entries = inventory_worktree(open_repository(repository.root)).entries
            self.assertIn("untracked.txt", tuple(entry.path for entry in entries))
            self.assertFalse(marker.exists())
            self.assertEqual(repository.path(".git/index").read_bytes(), index_before)

    def test_git_command_failure_receives_the_stable_command_code(self) -> None:
        failed = subprocess.CompletedProcess([], 9, b"", b"failure")
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch("repo_context.inventory.subprocess.run", return_value=failed):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT002")
        self.assertEqual(
            dict(raised.exception.diagnostics[0].details),
            {"operation": "list-index", "return_code": 9},
        )


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

    def test_worktree_join_rejects_nested_drive_components_on_every_host(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            for path in ("dir/C:relative", "dir/C:/absolute"):
                with self.subTest(path=path):
                    with self.assertRaises(ValueError):
                        worktree_path(handle, path)

    def test_malformed_non_nul_index_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch(
                "repo_context.inventory._run_git",
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
                    with patch("repo_context.inventory._run_git", side_effect=side_effect):
                        with self.assertRaises(RepositoryAccessError) as raised:
                            inventory_worktree(handle)
                self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_base_tree_records_are_validated_and_sorted_independent_of_git_order(self) -> None:
        object_id = b"a" * 40
        reversed_tree = (
            b"100644 blob " + object_id + b"\tz.txt\x00"
            b"100644 blob " + object_id + b"\ta.txt\x00"
        )
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            revision = BaseRevision("main", "b" * 40)
            with patch("repo_context.inventory._run_git", return_value=reversed_tree):
                entries = list_base_tree(handle, revision)
            self.assertEqual(tuple(entry.path for entry in entries), ("a.txt", "z.txt"))
            with patch(
                "repo_context.inventory._run_git",
                return_value=reversed_tree[:-1],
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    list_base_tree(handle, revision)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT003")

    def test_failure_evaluation_is_globally_path_sorted_across_sources(self) -> None:
        object_id = b"a" * 40
        tracked_z = b"H 100644 " + object_id + b" 0\tz.txt\x00"
        untracked_a = b"a.txt\x00"
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch(
                "repo_context.inventory._run_git",
                side_effect=(tracked_z, b"", untracked_a),
            ):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
        diagnostic = raised.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "GIT005")
        self.assertEqual(diagnostic.location.path, "a.txt")
        self.assertEqual(dict(diagnostic.details)["listed_source"], "untracked")


class WorktreeRaceAndSafetyTests(unittest.TestCase):
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
