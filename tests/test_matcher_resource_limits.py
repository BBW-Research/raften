from __future__ import annotations

import unittest
from unittest import mock

from raften.config import ConfigurationError, parse_policy
from raften.matcher import compile_pattern, match_path
from raften.matcher_limits import MatchBudget
from raften.repository_errors import RepositoryAccessError
from tests.support.config import STARTER_POLICY_TEXT


class MatcherResourceTests(unittest.TestCase):
    def test_pattern_and_work_limits_are_inclusive(self) -> None:
        self.assertEqual(compile_pattern("😀" * 1024).source, "😀" * 1024)
        self.assertEqual(len(compile_pattern("?" * 1024).components[0].tokens), 1024)
        measured = MatchBudget()
        self.assertTrue(match_path("*", "ab", budget=measured))
        self.assertTrue(match_path("*", "ab", budget=MatchBudget(limit=measured.work)))
        with self.assertRaises(RepositoryAccessError):
            match_path("*", "ab", budget=MatchBudget(limit=measured.work - 1))

    def test_shared_budget_accounts_for_multiple_matches(self) -> None:
        budget = MatchBudget(limit=25)
        self.assertTrue(match_path("*", "ab", budget=budget))
        with self.assertRaises(RepositoryAccessError):
            match_path("*", "ab", budget=budget)

    def test_maximum_pattern_and_large_component_refuse_before_character_scan(self) -> None:
        with mock.patch("raften.matcher._token_matches_character", side_effect=AssertionError("scanned")):
            with self.assertRaises(RepositoryAccessError):
                match_path("*" + "?" * 1023, "a" * 8192)

    def test_long_wildcard_pattern_is_rejected_before_token_allocation(self) -> None:
        with mock.patch("raften.matcher._compile_component", side_effect=AssertionError("compiled")):
            with self.assertRaises(ValueError):
                compile_pattern("?" * 5000)

    def test_configuration_scalar_and_list_patterns_fail_with_one_resource_diagnostic(self) -> None:
        pattern = "?" * 2000
        cases = (
            STARTER_POLICY_TEXT.replace('patterns = ["**"]', f'patterns = ["{pattern}"]'),
            STARTER_POLICY_TEXT + f'\n[[path_override]]\npattern = "data/{pattern}.txt"\nwarn_bytes = 10\nhard_bytes = 20\n',
        )
        for policy in cases:
            with self.subTest(policy=policy[-80:]):
                with self.assertRaises(ConfigurationError) as caught:
                    parse_policy(policy.encode("utf-8"))
                self.assertEqual([d.code for d in caught.exception.diagnostics], ["CFG016"])

    def test_one_large_character_class_is_charged_for_its_ranges(self) -> None:
        with self.assertRaises(ValueError):
            compile_pattern("[" + "a" * 2000 + "]")

    def test_component_work_stops_before_dynamic_programming_rows(self) -> None:
        with mock.patch("raften.resource_limits.MAX_MATCH_WORK", 100, create=True):
            with self.assertRaises(RepositoryAccessError) as caught:
                match_path("*" + "?" * 20, "a" * 100)
        self.assertEqual(caught.exception.diagnostics[0].code, "GIT010")


if __name__ == "__main__":
    unittest.main()
