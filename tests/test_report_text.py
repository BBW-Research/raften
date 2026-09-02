from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path

from repo_context.model import OutputFormat
from repo_context.report import render_report
from repo_context.runner import explain_repository_path, run_repository
from tests.support.repository import RepositoryFixture
from tests.support.target import install_clean_target, install_runtime_configuration_failure


ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 9, 2)


class TextReportTests(unittest.TestCase):
    def test_clean_check_matches_focused_golden(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            rendered = render_report("check", outcome, OutputFormat.TEXT)

        expected = (ROOT / "tests/fixtures/output/check-clean.txt").read_text(encoding="utf-8")
        self.assertEqual(rendered, expected)
        self.assertEqual(rendered.count("Summary:"), 1)

    def test_control_characters_in_paths_never_create_fake_output_lines(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("line\nbreak.txt", b"x" * 30_000)
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            rendered = render_report("check", outcome, OutputFormat.TEXT)

        self.assertIn('"line\\nbreak.txt"', rendered)
        self.assertNotIn('"line\nbreak.txt"', rendered)
        self.assertEqual(rendered.count("Summary:"), 1)

    def test_audit_and_explain_have_sections_then_one_final_summary(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            run = run_repository(repository.root, evaluation_date=TODAY)
            explanation = explain_repository_path(
                repository.root,
                "ARCHITECTURE.md",
                evaluation_date=TODAY,
            )
            audit = render_report("audit", run, OutputFormat.TEXT)
            explain = render_report("explain", explanation, OutputFormat.TEXT)

        self.assertIn("Largest governed files:", audit)
        self.assertIn("Context sets:", audit)
        self.assertIn("Documentation:", audit)
        self.assertTrue(audit.rstrip().endswith("Summary: 0 errors, 0 warnings, 1 note."))
        self.assertIn('Path: "ARCHITECTURE.md".', explain)
        self.assertIn("Override:", explain)
        self.assertIn("Migration: status=not_applicable", explain)
        self.assertEqual(explain.count("Summary:"), 1)

    def test_audit_file_rows_include_complete_budget_provenance(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("large.txt", b"x" * 30_000)
            run = run_repository(repository.root, evaluation_date=TODAY)
            audit = render_report("audit", run, OutputFormat.TEXT)

        expected = (
            '  "large.txt": size=30000 bytes, classification=authored, '
            'rule="authored", warn=20480, hard=25600, '
            'percent_of_hard=117.19%.'
        )
        self.assertIn(expected, audit)
        self.assertIn(expected[:-1] + ", state=hard.", audit)

    def test_failed_audit_omits_partial_data_sections(self) -> None:
        with RepositoryFixture() as repository:
            install_runtime_configuration_failure(repository)
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            rendered = render_report("audit", outcome, OutputFormat.TEXT)

        self.assertNotIn("Audit:", rendered)
        self.assertNotIn("Largest governed files:", rendered)
        self.assertIn("ERROR CFG015", rendered)
        self.assertTrue(rendered.endswith("Summary: 1 error, 0 warnings, 0 notes.\n"))


if __name__ == "__main__":
    unittest.main()
