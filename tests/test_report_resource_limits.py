from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import date
from unittest import mock

from raften.cli import main
from raften import report_text
from raften.model import OutputFormat
from raften.report import render_report
from raften.report_encoding import encode_report
from raften.repository_errors import RepositoryAccessError
from raften.runner import run_repository
from tests.support.config import STARTER_POLICY_TEXT, append_exception_record
from tests.support.repository import RepositoryFixture
from tests.support.target import install_clean_target


class ReportResourceTests(unittest.TestCase):
    def test_encoder_preserves_json_layout_and_inclusive_utf8_byte_limit(self) -> None:
        value = {"nested": [[], {}, {"unicode": "中文", "text": "\"\n"}], "ok": True}
        expected = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        size = len(expected.encode("utf-8"))
        with mock.patch("raften.resource_limits.MAX_REPORT_BYTES", size):
            self.assertEqual(encode_report(value), expected)
        with mock.patch("raften.resource_limits.MAX_REPORT_BYTES", size - 1):
            with self.assertRaises(RepositoryAccessError):
                encode_report(value)

    def test_encoder_stops_lazy_projection_at_item_limit(self) -> None:
        visited = []

        def rows():
            for index in range(100):
                visited.append(index)
                yield index

        with mock.patch("raften.resource_limits.MAX_REPORT_ITEMS", 3):
            with self.assertRaises(RepositoryAccessError) as caught:
                encode_report(rows())
        self.assertEqual(visited, [0, 1, 2])
        self.assertEqual(dict(caught.exception.diagnostics[0].details)["resource"], "report_items")

    def test_repeated_policy_text_stops_before_expanded_output_is_retained(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            policy = append_exception_record(
                STARTER_POLICY_TEXT,
                'pattern = "data/*.txt"\nowner = "security"\n'
                f'rationale = "{"x" * 4000}"\ntracking_reference = "issue-19"\n'
                'created_on = 2026-08-01\nwarn_bytes = 20000\nhard_bytes = 30000',
            )
            repository.write_text("raften.toml", policy)
            for index in range(20):
                repository.write_text(f"data/{index}.txt", "small\n")
            outcome = run_repository(repository.root, evaluation_date=date(2026, 10, 10))
            with mock.patch("raften.resource_limits.MAX_REPORT_BYTES", 16_000, create=True):
                with self.assertRaises(RepositoryAccessError) as caught:
                    render_report("audit", outcome, OutputFormat.JSON)
        diagnostic = caught.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "GIT010")
        self.assertEqual(dict(diagnostic.details)["resource"], "report_bytes")

    def test_cli_report_exhaustion_emits_one_complete_failure_document(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            stdout, stderr = io.StringIO(), io.StringIO()
            with mock.patch("raften.resource_limits.MAX_REPORT_BYTES", 1500, create=True):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = main(["audit", "--repo", str(repository.root), "--format", "json"])
        document = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(document["status"], "operational_error")
        self.assertIsNone(document["data"])
        self.assertEqual([item["code"] for item in document["diagnostics"]], ["GIT010"])

    def test_text_audit_stops_projecting_warning_rows_at_byte_limit(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            policy = STARTER_POLICY_TEXT.replace('name = "authored"', 'name = "' + "x" * 2000 + '"')
            repository.write_text("raften.toml", policy)
            for index in range(20):
                repository.write_bytes(f"data/{index}.txt", b"x" * 21_000)
            outcome = run_repository(repository.root, evaluation_date=date(2026, 10, 10))
            with mock.patch("raften.resource_limits.MAX_REPORT_BYTES", 16_000):
                with mock.patch("raften.report_text._audit_file_line",
                                wraps=report_text._audit_file_line) as project:
                    with self.assertRaises(RepositoryAccessError):
                        render_report("audit", outcome, OutputFormat.TEXT)
            self.assertLess(project.call_count, 10)


if __name__ == "__main__":
    unittest.main()
