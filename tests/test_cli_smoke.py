from __future__ import annotations

import contextlib
import io
import tomllib
import unittest
from pathlib import Path

from repo_context.cli import build_parser, main


class CliSmokeTests(unittest.TestCase):
    def test_target_commands_are_exposed(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        for command in ("check", "audit", "explain", "init"):
            self.assertIn(command, help_text)

    def test_no_command_prints_help_and_succeeds(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main([])
        self.assertEqual(result, 0)
        self.assertIn("repo-context", stdout.getvalue())

    def test_invalid_explicit_repository_is_a_structured_failure(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main(["check", "--repo", "/does/not/exist"])
        self.assertEqual(result, 2)
        self.assertIn("GIT001", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_package_metadata_reads_the_single_runtime_version_constant(self) -> None:
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertNotIn("version", metadata["project"])
        self.assertIn("version", metadata["project"]["dynamic"])
        self.assertEqual(
            metadata["tool"]["setuptools"]["dynamic"]["version"],
            {"attr": "repo_context.__version__"},
        )


if __name__ == "__main__":
    unittest.main()
