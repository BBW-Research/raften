from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from repo_context.config import starter_policy
from repo_context.model import (
    ExactSelector,
    ExceptionSettings,
    FileKind,
    FileRule,
    IntentionalException,
    PathOverride,
    PatternSelector,
)
from repo_context.sizes import compile_size_policy, resolve_effective_policy


class EffectivePolicyTests(unittest.TestCase):
    def test_first_rule_and_first_pattern_match_supply_provenance(self) -> None:
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule(
                    "first",
                    ("src/**", "**/*.py"),
                    FileKind.FIXTURE,
                    True,
                    20,
                    30,
                ),
                FileRule(
                    "later-specific",
                    ("src/generated.py",),
                    FileKind.GENERATED,
                    False,
                    None,
                    None,
                    "generated",
                ),
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(),
            context_sets=(),
        )
        compiled = compile_size_policy(policy)
        match = resolve_effective_policy(compiled, "src/generated.py", date(2026, 9, 1))
        self.assertIsNotNone(match)
        self.assertEqual(match.rule_match.rule_index, 0)
        self.assertEqual(match.rule_match.pattern_index, 0)
        self.assertEqual(match.rule_match.pattern, "src/**")
        self.assertEqual(match.kind, FileKind.FIXTURE)

    def test_exact_override_wins_and_pattern_override_uses_highest_specificity(self) -> None:
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(
                PathOverride(PatternSelector("**/*.md"), 90, 180),
                PathOverride(PatternSelector("docs/**/index.md"), 80, 160),
                PathOverride(ExactSelector("docs/api/index.md"), 70, 140),
                PathOverride(PatternSelector("docs/**/*.md"), 95, 190),
            ),
            context_sets=(),
        )
        compiled = compile_size_policy(policy)

        exact = resolve_effective_policy(compiled, "docs/api/index.md", date(2026, 9, 1))
        self.assertIsNotNone(exact)
        self.assertEqual(exact.override_match.override_index, 2)
        self.assertIsNone(exact.override_match.specificity)
        self.assertEqual((exact.ordinary_warn_bytes, exact.ordinary_hard_bytes), (70, 140))

        pattern = resolve_effective_policy(compiled, "docs/guide/index.md", date(2026, 9, 1))
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern.override_match.override_index, 1)
        self.assertEqual((pattern.ordinary_warn_bytes, pattern.ordinary_hard_bytes), (80, 160))

    def test_override_can_only_narrow_rule_limits(self) -> None:
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(
                PathOverride(ExactSelector("README.md"), 150, 300),
            ),
            context_sets=(),
        )
        match = resolve_effective_policy(
            compile_size_policy(policy),
            "README.md",
            date(2026, 9, 1),
        )
        self.assertIsNotNone(match)
        self.assertEqual((match.ordinary_warn_bytes, match.ordinary_hard_bytes), (100, 200))

    def test_override_does_not_turn_on_an_unscanned_rule(self) -> None:
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule(
                    "generated",
                    ("generated/**",),
                    FileKind.GENERATED,
                    False,
                    None,
                    None,
                    "generated",
                ),
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(
                PathOverride(PatternSelector("generated/*.json"), 50, 75),
            ),
            context_sets=(),
        )
        match = resolve_effective_policy(
            compile_size_policy(policy),
            "generated/schema.json",
            date(2026, 9, 1),
        )
        self.assertIsNotNone(match)
        self.assertIsNotNone(match.override_match)
        self.assertFalse(match.ordinary_scan)
        self.assertFalse(match.effective_scan)
        self.assertIsNone(match.effective_warn_bytes)
        self.assertIsNone(match.effective_hard_bytes)

    def test_exception_replaces_limits_or_scan_after_ordinary_policy(self) -> None:
        exceptions = ExceptionSettings(
            True,
            True,
            True,
            False,
            (
                IntentionalException(
                    ExactSelector("large.txt"),
                    "owner",
                    "temporary",
                    "issue-1",
                    date(2026, 1, 1),
                    None,
                    None,
                    250,
                    300,
                ),
                IntentionalException(
                    PatternSelector("vendor/*.txt"),
                    "owner",
                    "do not scan",
                    "issue-2",
                    date(2026, 1, 1),
                    date(2026, 12, 31),
                    False,
                    None,
                    None,
                ),
            ),
        )
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(),
            context_sets=(),
            exceptions=exceptions,
        )
        compiled = compile_size_policy(policy)

        larger = resolve_effective_policy(compiled, "large.txt", date(2026, 9, 1))
        self.assertIsNotNone(larger)
        self.assertEqual((larger.ordinary_warn_bytes, larger.ordinary_hard_bytes), (100, 200))
        self.assertEqual((larger.effective_warn_bytes, larger.effective_hard_bytes), (250, 300))
        self.assertEqual(larger.exception_match.exception_index, 0)

        excluded = resolve_effective_policy(compiled, "vendor/code.txt", date(2026, 9, 1))
        self.assertIsNotNone(excluded)
        self.assertTrue(excluded.ordinary_scan)
        self.assertFalse(excluded.effective_scan)
        self.assertIsNone(excluded.effective_warn_bytes)
        self.assertIsNone(excluded.effective_hard_bytes)

    def test_expired_exception_is_not_applied(self) -> None:
        record = IntentionalException(
            ExactSelector("large.txt"),
            "owner",
            "temporary",
            "issue-1",
            date(2026, 1, 1),
            date(2026, 8, 31),
            None,
            250,
            300,
        )
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(),
            context_sets=(),
            exceptions=replace(starter_policy().exceptions, records=(record,)),
        )
        compiled = compile_size_policy(policy)
        on_expiry = resolve_effective_policy(compiled, "large.txt", date(2026, 8, 31))
        after_expiry = resolve_effective_policy(compiled, "large.txt", date(2026, 9, 1))
        self.assertIsNotNone(on_expiry.exception_match)
        self.assertIsNone(after_expiry.exception_match)

    def test_exact_exception_wins_then_pattern_specificity_breaks_precedence(self) -> None:
        records = (
            IntentionalException(
                PatternSelector("temporary/*.txt"),
                "owner",
                "broad temporary boundary",
                "issue-1",
                date(2026, 1, 1),
                None,
                None,
                210,
                220,
            ),
            IntentionalException(
                ExactSelector("temporary/a.txt"),
                "owner",
                "exact temporary boundary",
                "issue-2",
                date(2026, 1, 1),
                None,
                None,
                310,
                320,
            ),
            IntentionalException(
                PatternSelector("temporary/special/*.txt"),
                "owner",
                "specific temporary boundary",
                "issue-3",
                date(2026, 1, 1),
                None,
                None,
                410,
                420,
            ),
        )
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(),
            context_sets=(),
            exceptions=replace(starter_policy().exceptions, records=records),
        )
        compiled = compile_size_policy(policy)
        exact = resolve_effective_policy(compiled, "temporary/a.txt", date(2026, 9, 1))
        specific = resolve_effective_policy(
            compiled,
            "temporary/special/a.txt",
            date(2026, 9, 1),
        )
        self.assertEqual(exact.exception_match.exception_index, 1)
        self.assertEqual((exact.effective_warn_bytes, exact.effective_hard_bytes), (310, 320))
        self.assertEqual(specific.exception_match.exception_index, 2)
        self.assertEqual(
            (specific.effective_warn_bytes, specific.effective_hard_bytes),
            (410, 420),
        )

    def test_manually_incomplete_policy_can_leave_a_path_unclassified(self) -> None:
        policy = replace(
            starter_policy(),
            file_rules=(
                FileRule("only-python", ("**/*.py",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(),
            context_sets=(),
        )
        self.assertIsNone(
            resolve_effective_policy(
                compile_size_policy(policy),
                "README.md",
                date(2026, 9, 1),
            )
        )


if __name__ == "__main__":
    unittest.main()
