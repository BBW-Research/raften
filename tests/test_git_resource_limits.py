"""Bounded Git streams, record decoding, and child cleanup."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from raften import inventory
from raften.git_records import parse_base_tree, parse_index_entries, parse_path_records
from raften.repository_errors import RepositoryAccessError


OBJECT = b"a" * 40


class GitResourceTests(unittest.TestCase):
    def invoke(self, script, *, operation="list-untracked", timeout=5, **ceilings):
        real_popen = subprocess.Popen
        children = []

        def spawn(*args, **kwargs):
            child = real_popen([sys.executable, "-c", script], **kwargs)
            children.append(child)
            return child

        from contextlib import ExitStack
        with ExitStack() as stack:
            directory = stack.enter_context(tempfile.TemporaryDirectory())
            stack.enter_context(patch("raften.inventory.subprocess.Popen", side_effect=spawn))
            stack.enter_context(patch("raften.inventory.GIT_TIMEOUT_SECONDS", timeout))
            for key, value in ceilings.items():
                stack.enter_context(patch(f"raften.resource_limits.{key}", value))
            try:
                return inventory._run_git(Path(directory), operation=operation, arguments=())
            finally:
                self.assertEqual(len(children), 1)
                self.assertIsNotNone(children[0].poll())
                self.assertTrue(children[0].stdout.closed)
                self.assertTrue(children[0].stderr.closed)

    def test_exact_stream_limits_and_binary_mode(self):
        self.assertEqual(self.invoke("import os; os.write(1,b'a'*16); os.write(2,b'e'*8)",
                                     operation="read-base-blob", MAX_GIT_OUTPUT_BYTES=16,
                                     MAX_GIT_STDERR_BYTES=8), b"a" * 16)

    def test_stdout_stderr_and_record_overflows_reap_the_child(self):
        cases = (
            ("os.write(1,b'a'*17)", {"MAX_GIT_OUTPUT_BYTES": 16}, "stdout_bytes"),
            ("os.write(2,b'e'*9)", {"MAX_GIT_STDERR_BYTES": 8}, "stderr_bytes"),
            ("os.write(1,b'a\\0b\\0c\\0')", {"MAX_GIT_RECORDS": 2}, "records"),
            ("os.write(1,b'a'*131)", {"MAX_GIT_PATH_BYTES": 2}, "record_bytes"),
        )
        for action, ceilings, resource in cases:
            with self.subTest(resource=resource):
                with self.assertRaises(RepositoryAccessError) as caught:
                    self.invoke(f"import os,time; {action}; time.sleep(30)", **ceilings)
                self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")
                self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], resource)

    def test_deadline_covers_reading_and_wait_after_pipe_eof(self):
        for script in ("import time; time.sleep(30)",
                       "import os,time; os.close(1); os.close(2); time.sleep(30)"):
            with self.assertRaises(RepositoryAccessError) as caught:
                self.invoke(script, timeout=0.1)
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT002")

    def test_record_framing_across_small_reads(self):
        real_read = os.read
        with patch("raften.git_output.os.read", side_effect=lambda fd, size: real_read(fd, min(size, 3))):
            self.assertEqual(self.invoke("import os; os.write(1,b'abcd\\0efgh\\0')",
                                         MAX_GIT_RECORDS=2, MAX_GIT_PATH_BYTES=4), b"abcd\0efgh\0")
            with self.assertRaises(RepositoryAccessError) as caught:
                self.invoke("import os; os.write(1,b'a'*131)", MAX_GIT_PATH_BYTES=2)
            self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "record_bytes")

    def test_malformed_long_header_is_rejected_before_splitting(self):
        for decode in (parse_index_entries, parse_base_tree):
            with patch("raften.resource_limits.MAX_GIT_PATH_BYTES", 2):
                with self.assertRaises(RepositoryAccessError) as caught:
                    decode(b" " * 131 + b"\0")
            self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")

    def test_all_record_decoders_check_exact_count_and_path_limits(self):
        decoders = (
            (lambda data: parse_path_records(data, operation="list-untracked"), b"abcd\0"),
            (parse_index_entries, b"H 100644 " + OBJECT + b" 0\tabcd\0"),
            (parse_base_tree, b"100644 blob " + OBJECT + b"\tabcd\0"),
        )
        for decode, record in decoders:
            with self.subTest(decode=decode), patch("raften.resource_limits.MAX_GIT_RECORDS", 1):
                with patch("raften.resource_limits.MAX_GIT_PATH_BYTES", 4):
                    self.assertEqual(len(decode(record)), 1)
                    for payload in (record * 2, record.replace(b"abcd", b"abcde")):
                        with self.assertRaises(RepositoryAccessError) as caught:
                            decode(payload)
                        self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")

    def test_combined_inventory_limit_precedes_filesystem_inspection(self):
        outputs = (b"H 100644 " + OBJECT + b" 0\ta\0", b"", b"b\0")
        with patch("raften.resource_limits.MAX_GIT_RECORDS", 1), \
             patch("raften.inventory._run_git", side_effect=outputs), \
             patch("raften.inventory._inspect_worktree_entry") as inspect:
            with self.assertRaises(RepositoryAccessError) as caught:
                inventory.inventory_worktree(inventory.RepositoryHandle(Path("/unused")))
            inspect.assert_not_called()
        self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "inventory_paths")

    def test_documented_hundred_thousand_path_scale_fits_metadata_envelope(self):
        data = b"".join(f"src/module-{index:06d}.py\0".encode() for index in range(100_000))
        self.assertEqual(len(parse_path_records(data, operation="list-untracked")), 100_000)
