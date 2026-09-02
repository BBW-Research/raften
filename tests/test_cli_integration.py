from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from repo_context.cli import main
from repo_context.config import render_starter_policy
from tests.support.config import append_exception_record
from tests.support.repository import RepositoryFixture
from tests.support.target import install_clean_target, install_runtime_configuration_failure


EVALUATION = ("--evaluation-date", "2026-09-02")


class _BrokenWriter(io.StringIO):
    def write(self, value):
        raise BrokenPipeError


class CliIntegrationTests(unittest.TestCase):
    def test_check_text_uses_stdout_for_success_and_stderr_for_violations(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            clean = repository.run_target("check", *EVALUATION)
            repository.write_bytes("large.txt", b"x" * 30_000)
            violation = repository.run_target("check", *EVALUATION)

        self.assertEqual(clean.returncode, 0)
        self.assertIn("Summary: 0 errors", clean.stdout)
        self.assertEqual(clean.stderr, "")
        self.assertEqual(violation.returncode, 1)
        self.assertEqual(violation.stdout, "")
        self.assertIn("CTX002", violation.stderr)
        self.assertIn("Summary:", violation.stderr)
        self.assertNotIn("Traceback", violation.stderr)

    def test_machine_formats_always_emit_one_document_on_stdout(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("large.txt", b"x" * 30_000)
            json_result = repository.run_target("check", "--format", "json", *EVALUATION)
            sarif_result = repository.run_target("check", "--format", "sarif", *EVALUATION)

        self.assertEqual(json_result.returncode, 1)
        self.assertEqual(json_result.stderr, "")
        self.assertEqual(json.loads(json_result.stdout)["command"], "check")
        self.assertEqual(sarif_result.returncode, 1)
        self.assertEqual(sarif_result.stderr, "")
        self.assertEqual(json.loads(sarif_result.stdout)["version"], "2.1.0")

    def test_warning_only_check_succeeds_on_stdout(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("warning.txt", b"x" * 22_000)
            result = repository.run_target("check", *EVALUATION)

        self.assertEqual(result.returncode, 0)
        self.assertIn("CTX001", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_explicit_evaluation_date_controls_exception_expiry(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            policy = append_exception_record(
                render_starter_policy().decode("utf-8"),
                '''path = "ARCHITECTURE.md"
owner = "architecture"
rationale = "Temporary entrypoint allowance"
tracking_reference = "ADR-42"
created_on = 2026-08-01
expires_on = 2026-09-01
warn_bytes = 9000
hard_bytes = 10000''',
            )
            repository.write_text("repo-context.toml", policy)
            on_expiry = repository.run_target(
                "check",
                "--evaluation-date",
                "2026-09-01",
            )
            after_expiry = repository.run_target("check", *EVALUATION)

        self.assertEqual(on_expiry.returncode, 0)
        self.assertNotIn("EXC002", on_expiry.stdout)
        self.assertEqual(after_expiry.returncode, 1)
        self.assertIn("EXC002", after_expiry.stderr)

    def test_audit_and_explain_succeed_despite_unrelated_policy_violations(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("large.txt", b"x" * 30_000)
            before = repository.status_bytes()
            audit = repository.run_target("audit", "--format", "json", *EVALUATION)
            explain = repository.run_target(
                "explain",
                "ARCHITECTURE.md",
                "--format",
                "json",
                *EVALUATION,
            )
            after = repository.status_bytes()

        self.assertEqual(audit.returncode, 0)
        self.assertEqual(audit.stderr, "")
        self.assertEqual(json.loads(audit.stdout)["summary"]["errors"], 1)
        self.assertEqual(after, before)
        self.assertEqual(explain.returncode, 0)
        self.assertEqual(explain.stderr, "")
        self.assertEqual(json.loads(explain.stdout)["data"]["path"], "ARCHITECTURE.md")

    def test_configuration_and_repository_failures_use_exit_two_without_tracebacks(self) -> None:
        with RepositoryFixture() as repository:
            text = repository.run_target("check", *EVALUATION)
            machine = repository.run_target("check", "--format", "json", *EVALUATION)
            audit = repository.run_target("audit", *EVALUATION)
            explain = repository.run_target("explain", "README.md", *EVALUATION)

        self.assertEqual(text.returncode, 2)
        self.assertEqual(text.stdout, "")
        self.assertIn("CFG001", text.stderr)
        self.assertNotIn("Traceback", text.stderr)
        self.assertEqual(machine.returncode, 2)
        self.assertEqual(machine.stderr, "")
        self.assertEqual(json.loads(machine.stdout)["status"], "configuration_error")
        for result in (audit, explain):
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertNotIn("Traceback", result.stderr)

    def test_runtime_configuration_failure_has_no_partial_machine_data(self) -> None:
        with RepositoryFixture() as repository:
            install_runtime_configuration_failure(repository)
            result = repository.run_target(
                "check",
                "--format",
                "json",
                *EVALUATION,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        document = json.loads(result.stdout)
        self.assertEqual(document["status"], "configuration_error")
        self.assertEqual([item["code"] for item in document["diagnostics"]], ["CFG015"])
        self.assertIsNone(document["data"])

    def test_explicit_relative_repository_works_from_an_unrelated_directory(self) -> None:
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory(
            dir=repository.root.parent,
        ) as outside:
            install_clean_target(repository)
            relative = Path("..") / repository.root.name
            result = repository.run_target(
                "check",
                "--repo",
                str(relative),
                *EVALUATION,
                cwd=Path(outside),
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")

    def test_init_end_to_end_captures_debt_and_refuses_dirty_state(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("legacy.txt", b"x" * 30_000)
            repository.commit("legacy")
            captured = repository.run_target("init", "--capture-debt")
            dirty_retry = repository.run_target("init", "--force", "--capture-debt")

        self.assertEqual(captured.returncode, 0)
        self.assertIn('Wrote "repo-context.debt.json".', captured.stdout)
        self.assertEqual(captured.stderr, "")
        self.assertEqual(dirty_retry.returncode, 2)
        self.assertIn("INIT001", dirty_retry.stderr)
        self.assertNotIn("Traceback", dirty_retry.stderr)

    def test_unknown_commands_formats_and_dates_are_argparse_errors(self) -> None:
        with RepositoryFixture() as repository:
            unknown = repository.run_target("unknown")
            audit_sarif = repository.run_target("audit", "--format", "sarif")
            bad_date = repository.run_target("check", "--evaluation-date", "2026-9-2")

        for result in (unknown, audit_sarif, bad_date):
            with self.subTest(stderr=result.stderr):
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)

    def test_explicit_empty_repository_is_not_reinterpreted_as_current_directory(self) -> None:
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            result = main(["check", "--repo", "", *EVALUATION])
        self.assertEqual(result, 2)
        self.assertIn("GIT001", stderr.getvalue())

    def test_command_paths_are_validated_before_any_path_normalization(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            bad_config = repository.run_target(
                "check",
                "--config",
                "nested//repo-context.toml",
                *EVALUATION,
            )
            bad_explain = repository.run_target(
                "explain",
                "docs//index.md",
                *EVALUATION,
            )

        for result in (bad_config, bad_explain):
            with self.subTest(stderr=result.stderr):
                self.assertEqual(result.returncode, 2)
                self.assertIn("CFG006", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_surrogate_command_path_is_a_machine_readable_argument_failure(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            result = repository.run_target(
                "explain",
                "bad\udcff.txt",
                "--format",
                "json",
                *EVALUATION,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        document = json.loads(result.stdout)
        self.assertEqual(document["diagnostics"][0]["code"], "CFG006")
        self.assertIn("Unicode scalar", document["diagnostics"][0]["message"])

    def test_surrogate_repository_path_is_a_machine_readable_root_failure(self) -> None:
        with RepositoryFixture() as repository:
            result = repository.run_target(
                "check",
                "--repo",
                "bad\udcff",
                "--format",
                "json",
                *EVALUATION,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        document = json.loads(result.stdout)
        self.assertEqual(document["diagnostics"][0]["code"], "GIT001")
        self.assertIn("\\udcff", document["diagnostics"][0]["details"]["root"])

    def test_machine_output_is_utf8_under_a_restrictive_stdio_encoding(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_text("café.txt", "unicode path\n")
            result = repository.run_target(
                "audit",
                "--format",
                "json",
                *EVALUATION,
                environment_overrides={"PYTHONIOENCODING": "ascii"},
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "")
        document = json.loads(result.stdout)
        paths = [item["path"] for item in document["data"]["largest_governed_files"]]
        self.assertIn("café.txt", paths)

    def test_version_comes_from_the_package_constant(self) -> None:
        with RepositoryFixture() as repository:
            result = repository.run_target("--version")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "repo-context 0.0.0\n")
        self.assertEqual(result.stderr, "")

    def test_broken_pipe_is_quiet_and_preserves_semantic_exit(self) -> None:
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            with mock.patch("sys.stdout", _BrokenWriter()):
                result = main([
                    "check",
                    "--repo",
                    str(repository.root),
                    *EVALUATION,
                ])
        self.assertEqual(result, 0)

        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_bytes("large.txt", b"x" * 30_000)
            with mock.patch("sys.stderr", _BrokenWriter()):
                violation = main([
                    "check",
                    "--repo",
                    str(repository.root),
                    *EVALUATION,
                ])
        self.assertEqual(violation, 1)

    def test_argparse_help_and_version_are_quiet_on_a_broken_pipe(self) -> None:
        for arguments in (("--help",), ("--version",)):
            with self.subTest(arguments=arguments):
                with mock.patch("sys.stdout", _BrokenWriter()):
                    with self.assertRaises(SystemExit) as raised:
                        main(arguments)
                self.assertEqual(raised.exception.code, 0)

    def test_unexpected_internal_failure_is_structured_without_traceback(self) -> None:
        stderr = io.StringIO()
        with mock.patch("repo_context.cli.run_repository", side_effect=RuntimeError("boom")):
            with mock.patch("sys.stderr", stderr):
                result = main(["check", *EVALUATION])
        self.assertEqual(result, 2)
        self.assertIn("INT001", stderr.getvalue())
        self.assertIn('"error_type":"RuntimeError"', stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_renderer_double_failure_preserves_machine_document_contract(self) -> None:
        for output_format in ("json", "sarif"):
            with self.subTest(output_format=output_format):
                stdout = io.StringIO()
                stderr = io.StringIO()
                with mock.patch(
                    "repo_context.cli.run_repository",
                    side_effect=RuntimeError("runner failed"),
                ):
                    with mock.patch(
                        "repo_context.cli.render_report",
                        side_effect=RuntimeError("renderer failed"),
                    ):
                        with mock.patch("sys.stdout", stdout), mock.patch(
                            "sys.stderr",
                            stderr,
                        ):
                            result = main([
                                "check",
                                "--format",
                                output_format,
                                *EVALUATION,
                            ])

                self.assertEqual(result, 2)
                self.assertEqual(stderr.getvalue(), "")
                document = json.loads(stdout.getvalue())
                if output_format == "json":
                    self.assertEqual(document["status"], "internal_error")
                    self.assertEqual(document["diagnostics"][0]["code"], "INT001")
                    self.assertIsNone(document["data"])
                else:
                    run = document["runs"][0]
                    self.assertFalse(run["invocations"][0]["executionSuccessful"])
                    self.assertEqual(run["results"][0]["ruleId"], "INT001")


if __name__ == "__main__":
    unittest.main()
