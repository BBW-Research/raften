from __future__ import annotations

import contextlib
import io
import unittest

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

    def test_unimplemented_command_fails_explicitly(self) -> None:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main(["check"])
        self.assertEqual(result, 2)
        self.assertIn("not implemented", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
