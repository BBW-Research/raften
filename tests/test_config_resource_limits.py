"""Policy rejection must not amplify attacker-controlled record populations."""

import unittest
from unittest.mock import patch

from raften.config import ConfigurationError, parse_policy
from raften.config_records import parse_exception_records
from raften.config_rules import parse_path_overrides
from raften.config_validation import Validator
from raften.diagnostics import CFG_AMBIGUOUS_OVERRIDE, CFG_RESOURCE_LIMIT
from tests.support.config import STARTER_POLICY_BYTES
from datetime import date


def records(count: int, *, exception: bool = False) -> list[dict]:
    result = []
    for index in range(count):
        record = {"pattern": f"docs/*{index:04d}*.md", "warn_bytes": 100, "hard_bytes": 200}
        if exception:
            record.update(owner="owner", rationale="reviewed", tracking_reference="#9",
                          created_on=date(2026, 1, 1))
        result.append(record)
    return result


class ConfigurationResourceTests(unittest.TestCase):
    def test_ambiguities_keep_only_first_witness_in_both_sections(self) -> None:
        for exception in (False, True):
            with self.subTest(exception=exception):
                validator = Validator("raften.toml")
                items = records(64, exception=exception)
                if exception:
                    parse_exception_records({"record": items}, validator)
                else:
                    parse_path_overrides({"path_override": items}, validator)
                self.assertEqual(validator.pattern_comparisons, 63)
                self.assertEqual(len(validator.diagnostics), 63)
                for diagnostic in validator.diagnostics:
                    self.assertEqual(diagnostic.code, CFG_AMBIGUOUS_OVERRIDE)
                    self.assertEqual(dict(diagnostic.details)["other_index"], 0)

    def test_record_overflow_fails_before_comparisons(self) -> None:
        for exception in (False, True):
            validator = Validator("raften.toml")
            with patch("raften.config_validation.MAX_SECTION_RECORDS", 2):
                with self.assertRaises(ConfigurationError) as caught:
                    if exception:
                        parse_exception_records({"record": records(3, exception=True)}, validator)
                    else:
                        parse_path_overrides({"path_override": records(3)}, validator)
            self.assertEqual(validator.pattern_comparisons, 0)
            self.assert_limit(caught.exception, "section_records")

    def test_diagnostic_and_comparison_exhaustion_abort_with_one_error(self) -> None:
        for setting, resource in (("MAX_DIAGNOSTICS", "diagnostics"),
                                  ("MAX_PATTERN_COMPARISONS", "pattern_comparisons")):
            with patch(f"raften.config_validation.{setting}", 2):
                with self.assertRaises(ConfigurationError) as caught:
                    parse_path_overrides({"path_override": records(4)}, Validator("p.toml"))
            self.assert_limit(caught.exception, resource)

    def test_policy_byte_limit_is_inclusive_and_precedes_toml(self) -> None:
        with patch("raften.config.MAX_POLICY_BYTES", len(STARTER_POLICY_BYTES)):
            parse_policy(STARTER_POLICY_BYTES)
            with self.assertRaises(ConfigurationError) as caught:
                parse_policy(STARTER_POLICY_BYTES + b"\n")
            self.assert_limit(caught.exception, "policy_bytes")

    def test_disjoint_patterns_share_one_comparison_budget_across_sections(self) -> None:
        validator = Validator("raften.toml")
        overrides = records(3)
        exceptions = records(2, exception=True)
        for index, record in enumerate(overrides + exceptions):
            record["pattern"] = f"docs/{index:04d}/*.md"
        with patch("raften.config_validation.MAX_PATTERN_COMPARISONS", 3):
            parse_path_overrides({"path_override": overrides}, validator)
            self.assertEqual(validator.pattern_comparisons, 3)
            self.assertEqual(validator.diagnostics, [])
            with self.assertRaises(ConfigurationError) as caught:
                parse_exception_records({"record": exceptions}, validator)
        self.assert_limit(caught.exception, "pattern_comparisons")

    def test_record_array_and_diagnostic_limits_are_inclusive(self) -> None:
        validator = Validator("raften.toml")
        with patch("raften.config_validation.MAX_SECTION_RECORDS", 2):
            parse_path_overrides({"path_override": records(2)}, validator)
            self.assertEqual(validator.array({"x": [1, 2]}, "x", parent="$"), [1, 2])
            with self.assertRaises(ConfigurationError) as caught:
                validator.array({"x": [1, 2, 3]}, "x", parent="$")
        self.assert_limit(caught.exception, "array_items")
        with patch("raften.config_validation.MAX_DIAGNOSTICS", 2):
            validator.add("CFG005", "$", "second")
            self.assertEqual(len(validator.diagnostics), 2)
            with self.assertRaises(ConfigurationError) as caught:
                validator.add("CFG005", "$", "third")
        self.assert_limit(caught.exception, "diagnostics")

    def assert_limit(self, error: ConfigurationError, resource: str) -> None:
        self.assertEqual(len(error.diagnostics), 1)
        self.assertEqual(error.diagnostics[0].code, CFG_RESOURCE_LIMIT)
        self.assertEqual(dict(error.diagnostics[0].details)["resource"], resource)
