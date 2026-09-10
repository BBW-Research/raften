from __future__ import annotations

import json
import unittest
from datetime import date

from raften.model import Diagnostic, OutputFormat, Severity, SourceLocation
from raften.report import render_report
from raften.report_sarif import _result_value
from raften.runner import run_repository
from tests.support.repository import RepositoryFixture
from tests.support.target import install_clean_target


TODAY = date(2026, 9, 2)


class SarifReportTests(unittest.TestCase):
    def test_sarif_has_sorted_rules_levels_and_only_real_artifact_locations(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("space % 中文.txt", b"x" * 30_000)
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            document = json.loads(render_report("check", outcome, OutputFormat.SARIF))

        run = document["runs"][0]
        self.assertEqual(document["version"], "2.1.0")
        self.assertEqual([item["id"] for item in run["tool"]["driver"]["rules"]], ["CTX002", "RAT001"])
        results = {item["ruleId"]: item for item in run["results"]}
        self.assertEqual(results["CTX002"]["level"], "error")
        location = results["CTX002"]["locations"][0]["physicalLocation"]
        self.assertEqual(location["artifactLocation"]["uri"], "space%20%25%20%E4%B8%AD%E6%96%87.txt")
        self.assertNotIn("region", location)
        self.assertNotIn("locations", results["RAT001"])
        self.assertTrue(run["invocations"][0]["executionSuccessful"])

    def test_real_markdown_source_positions_become_sarif_regions(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_text(
                "docs/index.md",
                "[Missing](missing.md)\n[Architecture](architecture/)\n",
            )
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            document = json.loads(render_report("check", outcome, OutputFormat.SARIF))

        results = document["runs"][0]["results"]
        missing = next(item for item in results if item["ruleId"] == "DOC009")
        physical = missing["locations"][0]["physicalLocation"]
        self.assertEqual(physical["artifactLocation"]["uri"], "docs/index.md")
        self.assertEqual(physical["region"]["startLine"], 1)
        self.assertEqual(physical["region"]["startColumn"], 1)

    def test_configuration_failure_does_not_invent_current_artifact_location(self) -> None:
        with RepositoryFixture() as repository:
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            document = json.loads(render_report("check", outcome, OutputFormat.SARIF))

        result = document["runs"][0]["results"][0]
        self.assertEqual(result["ruleId"], "CFG001")
        self.assertNotIn("locations", result)
        self.assertFalse(document["runs"][0]["invocations"][0]["executionSuccessful"])

    def test_nonpositive_source_coordinates_never_become_a_sarif_region(self) -> None:
        diagnostic = Diagnostic(
            code="DOC999",
            severity=Severity.ERROR,
            message="constructed invalid coordinate",
            location=SourceLocation("docs/index.md", 0, -1),
        )

        result = _result_value(diagnostic, frozenset({"docs/index.md"}))

        physical = result["locations"][0]["physicalLocation"]
        self.assertNotIn("region", physical)


if __name__ == "__main__":
    unittest.main()
