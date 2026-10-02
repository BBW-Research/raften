"""Content ceilings must apply before allocation and preserve raw-byte semantics."""

import contextlib
import hashlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from raften import inventory, runner
from raften.cli import main
from raften.config import render_starter_policy
from raften.debt import parse_debt_manifest, render_debt_manifest
from raften.model import ContentState
from raften.repository_errors import RepositoryAccessError
from raften.size_policy import compile_size_policy
from raften.sizes import classify_content, evaluate_sizes
from tests.support.repository import RepositoryFixture
from tests.support.sizes import TODAY, policy_with, regular
from tests.support.target import install_clean_target


class ContentResourceTests(unittest.TestCase):
    def test_sparse_current_policy_fails_before_content_read_for_check_and_audit(self):
        with RepositoryFixture() as repository:
            with repository.path("raften.toml").open("wb") as stream:
                stream.truncate(runner.MAX_POLICY_BYTES + 1)
            for command in ("check", "audit"):
                output = io.StringIO()
                with patch("raften.worktree._read_descriptor") as read, contextlib.redirect_stdout(output):
                    code = main([command, "--repo", str(repository.root), "--format", "json"])
                read.assert_not_called()
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(output.getvalue())["diagnostics"][0]["code"], "GIT010")

    def test_regular_snapshot_ceiling_is_checked_before_open(self):
        with RepositoryFixture() as repository:
            repository.write_bytes("large", b"abcd")
            handle = inventory.open_repository(repository.root)
            entry = inventory.inspect_repository_path(handle, "large")
            with patch("raften.resource_limits.MAX_CONTENT_BYTES", 3), \
                 patch("raften.worktree._open_snapshot_file") as opened:
                with self.assertRaises(RepositoryAccessError):
                    inventory.read_worktree_bytes(handle, entry)
                opened.assert_not_called()
            with patch("raften.resource_limits.MAX_CONTENT_BYTES", 4):
                self.assertEqual(inventory.read_worktree_bytes(handle, entry), b"abcd")

    def test_base_blob_size_preflight_and_stream_bound(self):
        with RepositoryFixture() as repository:
            repository.write_bytes("large", b"x" * 33)
            revision = repository.commit()
            handle = inventory.open_repository(repository.root)
            entry = inventory.list_base_tree(handle, inventory.resolve_base_revision(handle, revision))[0]
            with patch("raften.inventory._run_git", wraps=inventory._run_git) as git:
                with self.assertRaises(RepositoryAccessError):
                    inventory.read_base_blob(handle, entry, max_bytes=32)
                self.assertEqual([call.kwargs["operation"] for call in git.call_args_list], ["size-base-blob"])
            original = inventory._run_git

            def false_size(*args, **kwargs):
                return b"1\n" if kwargs["operation"] == "size-base-blob" else original(*args, **kwargs)

            with patch("raften.inventory._run_git", side_effect=false_size):
                with self.assertRaises(RepositoryAccessError) as caught:
                    inventory.read_base_blob(handle, entry, max_bytes=32)
                self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "stdout_bytes")
            self.assertEqual(inventory.read_base_blob(handle, entry, max_bytes=33), b"x" * 33)

    def test_oversized_base_policy_uses_policy_specific_ceiling(self):
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            original = render_starter_policy()
            repository.write_bytes("raften.toml", original + b"\n#" + b"x" * 5000)
            base = repository.commit()
            repository.write_bytes("raften.toml", original)
            with patch("raften.runner.MAX_POLICY_BYTES", len(original)), \
                 patch("raften.inventory._run_git", wraps=inventory._run_git) as git:
                result = runner.run_repository(repository.root, base_ref=base, evaluation_date=TODAY)
            self.assertEqual(result.diagnostics[0].code, "GIT010")
            self.assertFalse(any(call.kwargs["operation"] == "read-base-blob" for call in git.call_args_list))

    def test_retained_text_limits_precede_reads(self):
        entries = (regular("a.md", 4), regular("b.md", 4))
        read = Mock(return_value=b"text")
        with patch("raften.resource_limits.MAX_RETAINED_TEXT_BYTES", 7):
            with self.assertRaises(RepositoryAccessError):
                evaluate_sizes(compile_size_policy(policy_with()), entries, read,
                               evaluation_date=TODAY, retain_text_paths=frozenset({"a.md", "b.md"}))
        self.assertEqual(read.call_count, 1)
        with patch("raften.sizes.MAX_MARKDOWN_BYTES", 3):
            read.reset_mock()
            with self.assertRaises(RepositoryAccessError):
                evaluate_sizes(compile_size_policy(policy_with()), entries, read,
                               evaluation_date=TODAY, retain_text_paths=frozenset({"a.md"}))
            read.assert_not_called()

    def test_classification_digest_and_manifest_exact_boundaries(self):
        with patch("raften.resource_limits.MAX_CONTENT_BYTES", 4):
            for raw, state in ((b"a\0bc", ContentState.CONTAINS_NUL),
                               (b"abc\xff", ContentState.INVALID_UTF8),
                               ("éé".encode(), ContentState.PLAINTEXT)):
                self.assertEqual(classify_content(raw).state, state)
                result = evaluate_sizes(compile_size_policy(policy_with()), (regular("a", 4),),
                                        lambda entry: raw, evaluation_date=TODAY)
                self.assertEqual(result.files[0].content_identity, "sha256:" + hashlib.sha256(raw).hexdigest())
        raw = b'{"schema_version":1,"entries":[]}'
        with patch("raften.resource_limits.MAX_MANIFEST_BYTES", len(raw)):
            parse_debt_manifest(raw)
            with self.assertRaises(RepositoryAccessError):
                parse_debt_manifest(raw + b" ")
        manifest = parse_debt_manifest(raw)
        rendered = render_debt_manifest(manifest)
        with patch("raften.resource_limits.MAX_MANIFEST_BYTES", len(rendered)):
            self.assertEqual(render_debt_manifest(manifest), rendered)
        with patch("raften.resource_limits.MAX_MANIFEST_BYTES", len(rendered) - 1):
            with self.assertRaises(RepositoryAccessError):
                render_debt_manifest(manifest)
