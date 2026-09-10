from __future__ import annotations

import json
import unittest
from datetime import date

from raften.config import render_starter_policy
from raften.model import OutputFormat
from raften.report import command_exit_code, render_report
from raften.run_model import CommandFailure, RepositoryRun
from raften.runner import explain_repository_path, run_repository
from tests.support.config import append_exception_record
from tests.support.repository import RepositoryFixture
from tests.support.target import install_clean_target


TODAY = date(2026, 9, 2)


class JsonReportTests(unittest.TestCase):
    def test_check_envelope_is_versioned_deterministic_and_structured(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            first = render_report("check", outcome, OutputFormat.JSON)
            second = render_report("check", outcome, OutputFormat.JSON)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        document = json.loads(first)
        self.assertEqual(
            tuple(document),
            ("schema_version", "tool", "command", "status", "summary", "diagnostics", "data"),
        )
        self.assertEqual(document["schema_version"], 1)
        self.assertEqual(document["tool"], {"name": "raften", "version": "1.0.0"})
        self.assertEqual(document["command"], "check")
        self.assertEqual(document["status"], "complete")
        self.assertEqual(document["summary"], {"errors": 0, "warnings": 0, "notes": 1})
        self.assertEqual(document["diagnostics"][0]["code"], "RAT001")
        self.assertIsNone(document["diagnostics"][0]["location"])
        self.assertEqual(document["data"]["evaluation_date"], "2026-09-02")

    def test_audit_exposes_required_metrics_and_exits_zero_with_violations(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("large.txt", b"x" * 30_000)
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            rendered = render_report("audit", outcome, OutputFormat.JSON)

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertEqual(command_exit_code("audit", outcome), 0)
        document = json.loads(rendered)
        data = document["data"]
        self.assertEqual(data["largest_governed_files"][0]["path"], "large.txt")
        self.assertEqual(data["files_above_warning"][0]["limit_state"], "hard")
        self.assertEqual(data["classification_counts"], [{"kind": "authored", "count": 7}])
        self.assertEqual(data["contexts"][0]["name"], "bootstrap")
        self.assertEqual(data["documentation"]["directory_count"], 2)
        self.assertEqual(data["documentation"]["max_depth"], 2)
        self.assertEqual(data["migration"][0]["status"], "unbaselined")
        self.assertEqual(data["exceptions"], [])

    def test_audit_retains_deleted_and_nonregular_governed_states(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_text("gone.txt", "tracked then deleted\n")
            repository.commit("tracked deletion fixture")
            repository.delete("gone.txt")
            repository.symlink("linked.txt", "README.md")
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            document = json.loads(render_report("audit", outcome, OutputFormat.JSON))

        files = document["data"]["largest_governed_files"]
        by_path = {item["path"]: item for item in files}
        self.assertEqual(by_path["gone.txt"]["inventory_source"], "deleted")
        self.assertEqual(by_path["gone.txt"]["worktree_kind"], "missing")
        self.assertIsNone(by_path["gone.txt"]["size_bytes"])
        self.assertEqual(by_path["linked.txt"]["worktree_kind"], "symlink")
        self.assertIsNone(by_path["linked.txt"]["content_state"])
        unsized = [item["path"] for item in files if item["size_bytes"] is None]
        self.assertEqual(unsized, sorted(unsized))
        self.assertTrue(
            all(item["size_bytes"] is not None for item in files[: -len(unsized)])
        )

    def test_explain_filters_unrelated_violations_and_exposes_full_provenance(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            policy = append_exception_record(
                render_starter_policy().decode("utf-8"),
                '''path = "ARCHITECTURE.md"
owner = "architecture"
rationale = "Temporary entrypoint allowance"
tracking_reference = "ADR-42"
created_on = 2026-08-01
expires_on = 2026-12-31
warn_bytes = 9000
hard_bytes = 10000''',
            )
            policy = append_exception_record(
                policy,
                '''path = "other.txt"
owner = "other-owner"
rationale = "Expired exception unrelated to the explained path"
tracking_reference = "ADR-99"
created_on = 2026-08-01
expires_on = 2026-09-01
warn_bytes = 9000
hard_bytes = 10000''',
            )
            policy = f'''{policy.rstrip()}

[[context_set]]
name = "unrelated"
paths = ["unrelated.txt"]
warn_bytes = 1
hard_bytes = 2
'''
            repository.write_text("raften.toml", policy)
            repository.write_bytes("unrelated.txt", b"x" * 30_000)
            outcome = explain_repository_path(
                repository.root,
                "ARCHITECTURE.md",
                evaluation_date=TODAY,
            )
            rendered = render_report("explain", outcome, OutputFormat.JSON)

        self.assertNotIsInstance(outcome, CommandFailure)
        document = json.loads(rendered)
        self.assertEqual([item["code"] for item in document["diagnostics"]], ["RAT001"])
        data = document["data"]
        self.assertEqual(data["path"], "ARCHITECTURE.md")
        self.assertEqual(data["policy"]["rule"]["name"], "authored")
        self.assertEqual(data["policy"]["override"]["selector"], {"type": "path", "value": "ARCHITECTURE.md"})
        self.assertEqual(data["policy"]["override"]["warn_bytes"], 6144)
        self.assertEqual(data["policy"]["override"]["hard_bytes"], 8192)
        self.assertEqual(data["policy"]["exception"]["owner"], "architecture")
        self.assertFalse(data["policy"]["exception"]["expired"])
        self.assertIsNone(data["policy"]["exception"]["scan"])
        self.assertEqual(data["policy"]["exception"]["warn_bytes"], 9000)
        self.assertEqual(data["policy"]["exception"]["hard_bytes"], 10000)
        self.assertEqual(data["context_sets"], ["bootstrap"])
        self.assertFalse(data["documentation"]["governed"])
        self.assertEqual(data["migration"], {"status": "not_applicable", "baseline_source": "unavailable"})

    def test_explain_retains_an_expired_exception_for_the_selected_path(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            policy = append_exception_record(
                render_starter_policy().decode("utf-8"),
                '''path = "ARCHITECTURE.md"
owner = "architecture"
rationale = "Expired selected-path allowance"
tracking_reference = "ADR-42"
created_on = 2026-08-01
expires_on = 2026-09-01
warn_bytes = 9000
hard_bytes = 10000''',
            )
            repository.write_text("raften.toml", policy)
            outcome = explain_repository_path(
                repository.root,
                "ARCHITECTURE.md",
                evaluation_date=TODAY,
            )
            document = json.loads(render_report("explain", outcome, OutputFormat.JSON))

        self.assertEqual(
            [item["code"] for item in document["diagnostics"]],
            ["EXC002", "RAT001"],
        )
        self.assertIsNone(document["data"]["policy"]["exception"])

    def test_failure_is_a_machine_readable_document_with_no_partial_data(self) -> None:
        with RepositoryFixture() as repository:
            outcome = run_repository(repository.root, evaluation_date=TODAY)
            rendered = render_report("check", outcome, OutputFormat.JSON)

        self.assertIsInstance(outcome, CommandFailure)
        document = json.loads(rendered)
        self.assertEqual(document["status"], "configuration_error")
        self.assertEqual(document["summary"]["errors"], 1)
        self.assertEqual(document["diagnostics"][0]["code"], "CFG001")
        self.assertIsNone(document["data"])
        self.assertEqual(command_exit_code("check", outcome), 2)


if __name__ == "__main__":
    unittest.main()
