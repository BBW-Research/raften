"""One repository command bounds cumulative content and Git process work."""

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from raften import inventory, runner, worktree
from raften.cli import main
from raften.initialization import initialize_repository
from raften.repository_errors import RepositoryAccessError
from raften.run_model import RepositoryRun
from tests.support.repository import RepositoryFixture
from tests.support.sizes import TODAY
from tests.support.target import install_clean_target


class CommandContentTests(unittest.TestCase):
    def test_current_bytes_are_charged_before_each_open_and_limits_are_inclusive(self):
        with RepositoryFixture() as fixture:
            fixture.write_bytes("a", b"abcd")
            fixture.write_bytes("b", b"efgh")
            for ceiling in (7, 8):
                handle = inventory.open_repository(fixture.root)
                entries = [inventory.inspect_repository_path(handle, name) for name in ("a", "b")]
                with patch("raften.resource_limits.MAX_COMMAND_CONTENT_BYTES", ceiling), \
                        patch("raften.worktree._read_descriptor", wraps=worktree._read_descriptor) as read:
                    self.assertEqual(inventory.read_worktree_bytes(handle, entries[0]), b"abcd")
                    if ceiling == 7:
                        with self.assertRaises(RepositoryAccessError) as caught:
                            inventory.read_worktree_bytes(handle, entries[1])
                        self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "command_content_bytes")
                        self.assertEqual(read.call_count, 1)
                    else:
                        self.assertEqual(inventory.read_worktree_bytes(handle, entries[1]), b"efgh")

    def test_worktree_and_base_bytes_share_budget_before_blob_expansion(self):
        with RepositoryFixture() as fixture:
            fixture.write_bytes("a", b"abcd")
            fixture.commit()
            handle = inventory.open_repository(fixture.root)
            revision = inventory.resolve_base_revision(handle, "HEAD")
            blob = inventory.list_base_tree(handle, revision)[0]
            entry = inventory.inspect_repository_path(handle, "a")
            inventory.read_worktree_bytes(handle, entry)
            with patch("raften.resource_limits.MAX_COMMAND_CONTENT_BYTES", 7), \
                    patch("raften.inventory._run_git", wraps=inventory._run_git) as git:
                with self.assertRaises(RepositoryAccessError):
                    inventory.read_base_blob(handle, blob)
                self.assertEqual([call.kwargs["operation"] for call in git.call_args_list], ["size-base-blob"])

    def test_init_streaming_unscanned_content_hash_is_bounded_before_read(self):
        with RepositoryFixture() as fixture:
            fixture.write_bytes("uv.lock", b"x" * 20)
            fixture.commit()
            with patch("raften.resource_limits.MAX_COMMAND_CONTENT_BYTES", 19), \
                    patch("raften.worktree._hash_descriptor") as hashed:
                result = initialize_repository(fixture.root)
                hashed.assert_not_called()
            self.assertEqual(result.diagnostics[0].code, "GIT010")
            self.assertFalse(fixture.path("raften.toml").exists())

    def test_process_limit_refuses_before_next_spawn_and_commands_are_fresh(self):
        with RepositoryFixture() as fixture:
            with patch("raften.resource_limits.MAX_COMMAND_GIT_PROCESSES", 1):
                for _ in range(2):
                    handle = inventory.open_repository(fixture.root)
                    with patch("raften.inventory.subprocess.Popen") as spawn:
                        with self.assertRaises(RepositoryAccessError) as caught:
                            inventory.inventory_worktree(handle)
                        spawn.assert_not_called()
                    self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "command_git_processes")

    def test_empty_base_blob_still_charges_each_process(self):
        with RepositoryFixture() as fixture:
            fixture.write_bytes("a", b"")
            fixture.commit()
            handle = inventory.open_repository(fixture.root)
            blob = inventory.list_base_tree(handle, inventory.resolve_base_revision(handle, "HEAD"))[0]
            limit = handle.budget.git_processes + 1
            with patch("raften.resource_limits.MAX_COMMAND_GIT_PROCESSES", limit), \
                    patch("raften.inventory.subprocess.Popen", wraps=inventory.subprocess.Popen) as spawn:
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.read_base_blob(handle, blob)
                self.assertEqual(spawn.call_count, 1)
            self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "command_git_processes")

    def test_short_base_output_cannot_satisfy_reserved_size(self):
        with RepositoryFixture() as fixture:
            fixture.write_bytes("a", b"abcd")
            fixture.commit()
            handle = inventory.open_repository(fixture.root)
            blob = inventory.list_base_tree(handle, inventory.resolve_base_revision(handle, "HEAD"))[0]
            original = inventory._run_git
            def false_size(*args, **kwargs):
                return b"5\n" if kwargs["operation"] == "size-base-blob" else original(*args, **kwargs)
            with patch("raften.inventory._run_git", side_effect=false_size):
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.read_base_blob(handle, blob)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT007")
            self.assertEqual(handle.budget.content_bytes, 5)

    def test_duplicate_base_blobs_share_compact_classification(self):
        with RepositoryFixture() as fixture:
            install_clean_target(fixture)
            for path in ("a.txt", "b.txt"):
                fixture.write_bytes(path, b"x" * 26_000)
            base = fixture.commit()
            with patch("raften.runner.read_base_blob", wraps=runner.read_base_blob) as read:
                outcome = runner.run_repository(fixture.root, base_ref=base, evaluation_date=TODAY)
            self.assertIsInstance(outcome, RepositoryRun)
            self.assertEqual(len(read.call_args_list), 2)  # one policy and one shared payload
            self.assertEqual([item.migration_status.value for item in outcome.ratchet.files], ["debt", "debt"])

    def test_cli_resource_failure_is_complete_for_all_read_commands(self):
        with RepositoryFixture() as fixture:
            install_clean_target(fixture)
            for command in ("check", "audit", "explain"):
                output = io.StringIO()
                arguments = [command] + (["README.md"] if command == "explain" else [])
                with patch("raften.resource_limits.MAX_COMMAND_CONTENT_BYTES", 0), contextlib.redirect_stdout(output):
                    code = main(arguments + ["--repo", str(fixture.root), "--format", "json"])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output.getvalue())["diagnostics"][0]["code"], "GIT010")
