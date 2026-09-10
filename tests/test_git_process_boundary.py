from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raften.inventory import (
    RepositoryAccessError,
    RepositoryHandle,
    inventory_worktree,
    open_repository,
    repository_is_clean,
)
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
                with patch("raften.inventory.subprocess.run", return_value=completed) as run:
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
                "core.fsmonitor=false",
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
            with patch("raften.inventory.subprocess.run", side_effect=outputs) as run:
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

    @unittest.skipIf(os.name == "nt", "fixture executable uses a POSIX shell")
    def test_cleanliness_probe_never_executes_repository_filter_commands(self) -> None:
        with RepositoryFixture() as repository:
            marker = repository.path("filter-executed")
            filter_program = repository.write_text(
                "filter-probe",
                "#!/bin/sh\n: > filter-executed\ncat\n",
            )
            filter_program.chmod(0o755)
            repository.write_text(".gitattributes", "tracked.txt filter=probe\n")
            repository.write_text(".gitignore", "filter-executed\n")
            repository.write_text("tracked.txt", "tracked\n")
            repository.commit()
            repository.git("config", "filter.probe.clean", str(filter_program))
            repository.write_text("tracked.txt", "changed\n")
            repository.write_text("tracked.txt", "tracked\n")

            self.assertTrue(repository_is_clean(open_repository(repository.root)))
            self.assertFalse(marker.exists())

    def test_git_command_failure_receives_the_stable_command_code(self) -> None:
        failed = subprocess.CompletedProcess([], 9, b"", b"failure")
        with tempfile.TemporaryDirectory() as directory:
            handle = RepositoryHandle(Path(directory))
            with patch("raften.inventory.subprocess.run", return_value=failed):
                with self.assertRaises(RepositoryAccessError) as raised:
                    inventory_worktree(handle)
        self.assertEqual(raised.exception.diagnostics[0].code, "GIT002")
        self.assertEqual(
            dict(raised.exception.diagnostics[0].details),
            {"operation": "list-index", "return_code": 9},
        )


class RepositoryCleanlinessTests(unittest.TestCase):
    def test_head_index_worktree_and_untracked_state_must_all_match(self) -> None:
        cases = (
            ("clean", True),
            ("ignored", True),
            ("worktree", False),
            ("staged", False),
            ("deleted", False),
            ("staged_deletion", False),
            ("untracked", False),
        )
        for state, expected in cases:
            with self.subTest(state=state), RepositoryFixture() as repository:
                repository.write_text(".gitignore", "ignored.local\n")
                repository.write_text("tracked.txt", "tracked\n")
                repository.commit()
                if state == "ignored":
                    repository.write_text("ignored.local", "ignored\n")
                elif state in {"worktree", "staged"}:
                    repository.write_text("tracked.txt", "changed\n")
                    if state == "staged":
                        repository.git("add", "tracked.txt")
                elif state in {"deleted", "staged_deletion"}:
                    repository.delete("tracked.txt")
                    if state == "staged_deletion":
                        repository.git("add", "--update", "tracked.txt")
                elif state == "untracked":
                    repository.write_text("untracked.txt", "untracked\n")

                self.assertEqual(
                    repository_is_clean(open_repository(repository.root)),
                    expected,
                )

    def test_empty_unborn_repository_is_clean_but_a_staged_addition_is_not(self) -> None:
        with RepositoryFixture() as repository:
            self.assertTrue(repository_is_clean(open_repository(repository.root)))
            repository.write_text("tracked.txt", "tracked\n")
            repository.git("add", "tracked.txt")
            self.assertFalse(repository_is_clean(open_repository(repository.root)))

    def test_missing_head_object_is_an_operational_error_not_an_unborn_branch(self) -> None:
        with RepositoryFixture() as repository:
            branch_ref = repository.git("symbolic-ref", "--quiet", "HEAD").stdout.strip()
            branch_path = repository.git_path(branch_ref)
            branch_path.parent.mkdir(parents=True, exist_ok=True)
            branch_path.write_text("0" * 40 + "\n", encoding="ascii")

            with self.assertRaises(RepositoryAccessError) as raised:
                repository_is_clean(open_repository(repository.root))
            self.assertEqual(raised.exception.diagnostics[0].code, "GIT002")

    @unittest.skipIf(os.name == "nt", "executable and symlink modes are POSIX fixtures")
    def test_executable_mode_and_symlink_target_changes_are_dirty(self) -> None:
        with RepositoryFixture() as repository:
            executable = repository.write_text("script.sh", "#!/bin/sh\n")
            executable.chmod(0o755)
            repository.symlink("linked", "first-target")
            repository.commit()
            self.assertTrue(repository_is_clean(open_repository(repository.root)))

            executable.chmod(0o644)
            self.assertFalse(repository_is_clean(open_repository(repository.root)))
            executable.chmod(0o755)
            repository.path("linked").unlink()
            repository.symlink("linked", "second-target")
            self.assertFalse(repository_is_clean(open_repository(repository.root)))

    def test_cleanliness_supports_sha256_object_ids_when_git_does(self) -> None:
        try:
            repository = RepositoryFixture(object_format="sha256")
        except subprocess.CalledProcessError as error:
            self.skipTest(f"host Git does not support SHA-256 repositories: {error}")
        with repository:
            repository.write_text("tracked.txt", "tracked\n")
            repository.commit()
            self.assertTrue(repository_is_clean(open_repository(repository.root)))
            repository.write_text("tracked.txt", "changed\n")
            self.assertFalse(repository_is_clean(open_repository(repository.root)))

    def test_filter_normalized_worktree_fails_closed_without_running_a_filter(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text(".gitattributes", "tracked.txt text eol=lf\n")
            repository.write_bytes("tracked.txt", b"tracked\r\n")
            repository.commit()
            self.assertEqual(repository.status_bytes(), b"")
            self.assertFalse(repository_is_clean(open_repository(repository.root)))

    def test_gitlinks_fail_closed_without_nested_repository_inspection(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("seed.txt", "seed\n")
            commit_id = repository.commit()
            repository.git(
                "update-index",
                "--add",
                "--cacheinfo",
                "160000",
                commit_id,
                "vendor/submodule",
            )
            repository.git("commit", "--quiet", "--message", "gitlink")
            gitlink_path = repository.path("vendor/submodule")
            gitlink_path.mkdir(parents=True)
            self.assertFalse(repository_is_clean(open_repository(repository.root)))
            gitlink_path.rmdir()
            repository.git("update-index", "--skip-worktree", "vendor/submodule")
            self.assertFalse(repository_is_clean(open_repository(repository.root)))


if __name__ == "__main__":
    unittest.main()
