from __future__ import annotations

import unittest

from raften.config import ConfigurationError, parse_policy
from raften.model import Diagnostic


class ConfigurationAssertions(unittest.TestCase):
    def policy_diagnostics(self, data: str | bytes) -> tuple[Diagnostic, ...]:
        encoded = data.encode("utf-8") if isinstance(data, str) else data
        with self.assertRaises(ConfigurationError) as caught:
            parse_policy(encoded, source_path="fixture.toml")
        diagnostics = caught.exception.diagnostics
        self.assertIsInstance(diagnostics, tuple)
        return diagnostics

    def assert_policy_diagnostic(
        self,
        data: str | bytes,
        code: str,
        field_path: str,
    ) -> tuple[Diagnostic, ...]:
        diagnostics = self.policy_diagnostics(data)
        self.assertIn(
            (code, field_path),
            ((diagnostic.code, diagnostic.field_path) for diagnostic in diagnostics),
        )
        return diagnostics
