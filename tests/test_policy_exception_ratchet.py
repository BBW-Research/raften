from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from repo_context.config import starter_policy
from repo_context.diagnostics import CFG_EFFECTIVE_POLICY, RAT_EXCEPTION_BROADENED
from repo_context.model import (
    ExactSelector,
    FileKind,
    FileRule,
    IntentionalException,
    PatternSelector,
)
from repo_context.policy_ratchet import compare_policies
from repo_context.size_policy import compile_size_policy
from repo_context.sizes import evaluate_sizes
from tests.support.sizes import TODAY, regular


def _reasons(diagnostics):
    return tuple(dict(item.details)["reason"] for item in diagnostics)


def _exception(
    selector=None,
    *,
    scan=None,
    warn_bytes=30_000,
    hard_bytes=40_000,
    expires_on=date(2026, 12, 31),
):
    return IntentionalException(
        ExactSelector("legacy.txt") if selector is None else selector,
        "maintainers",
        "temporary migration",
        "issue-123",
        date(2026, 1, 1),
        expires_on,
        scan,
        warn_bytes,
        hard_bytes,
    )


class ExceptionPolicyRatchetTests(unittest.TestCase):
    def test_new_and_broadened_exceptions_are_reported_but_safe_removal_is_tightening(self) -> None:
        base_record = _exception()
        base = replace(
            starter_policy(),
            exceptions=replace(starter_policy().exceptions, records=(base_record,)),
        )
        additions = replace(
            base,
            exceptions=replace(
                base.exceptions,
                records=(base_record, _exception(ExactSelector("other.txt"))),
            ),
        )
        broader_limit = replace(
            base,
            exceptions=replace(base.exceptions, records=(replace(base_record, hard_bytes=50_000),)),
        )
        broader_expiry = replace(
            base,
            exceptions=replace(base.exceptions, records=(replace(base_record, expires_on=None),)),
        )
        broader_scan = replace(
            base,
            exceptions=replace(
                base.exceptions,
                records=(replace(base_record, scan=False, warn_bytes=None, hard_bytes=None),),
            ),
        )

        for reason, current in (
            ("exception_added", additions),
            ("hard_limit_increased", broader_limit),
            ("expiry_extended", broader_expiry),
            ("scan_relief_broadened", broader_scan),
        ):
            with self.subTest(reason=reason):
                diagnostics = compare_policies(current, base)
                self.assertIn(RAT_EXCEPTION_BROADENED, {item.code for item in diagnostics})
                self.assertIn(reason, _reasons(diagnostics))

        added = next(
            item
            for item in compare_policies(additions, base)
            if dict(item.details)["reason"] == "exception_added"
        )
        self.assertEqual(
            {"owner", "rationale", "tracking_reference", "created_on", "expires_on"},
            set(dict(added.details)).difference({"reason", "base_value", "current_value"}),
        )

        removed = replace(base, exceptions=replace(base.exceptions, records=()))
        self.assertEqual(compare_policies(removed, base), ())

    def test_exception_removal_cannot_expose_broader_pattern_relief(self) -> None:
        broad = _exception(
            PatternSelector("src/**/*.py"),
            warn_bytes=100_000,
            hard_bytes=200_000,
        )
        tight = _exception(
            ExactSelector("src/safe.py"),
            warn_bytes=100,
            hard_bytes=200,
        )
        base = replace(
            starter_policy(),
            exceptions=replace(starter_policy().exceptions, records=(broad, tight)),
        )
        current = replace(
            base,
            exceptions=replace(base.exceptions, records=(broad,)),
        )

        diagnostics = compare_policies(current, base)

        self.assertIn(RAT_EXCEPTION_BROADENED, {item.code for item in diagnostics})
        self.assertIn("exception_removal_exposes_weaker_fallback", _reasons(diagnostics))

    def test_exception_limit_removal_cannot_expose_looser_ordinary_limits(self) -> None:
        tight = _exception(
            ExactSelector("legacy.txt"),
            scan=True,
            warn_bytes=100,
            hard_bytes=200,
        )
        base = replace(
            starter_policy(),
            exceptions=replace(starter_policy().exceptions, records=(tight,)),
        )
        current = replace(
            base,
            exceptions=replace(
                base.exceptions,
                records=(replace(tight, warn_bytes=None, hard_bytes=None),),
            ),
        )

        diagnostics = compare_policies(current, base)

        self.assertIn(RAT_EXCEPTION_BROADENED, {item.code for item in diagnostics})
        self.assertIn("replacement_limits_removed", _reasons(diagnostics))

    def test_incomplete_current_fallback_is_cfg015_and_a_policy_finding(self) -> None:
        generated = FileRule("generated", ("generated/**",), FileKind.GENERATED, False, None, None)
        authored = FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20)
        broad = _exception(
            PatternSelector("generated/**/*.txt"),
            scan=True,
            warn_bytes=None,
            hard_bytes=None,
        )
        exact = _exception(
            ExactSelector("generated/safe.txt"),
            scan=True,
            warn_bytes=None,
            hard_bytes=None,
        )
        base = replace(
            starter_policy(),
            file_rules=(generated, authored),
            path_overrides=(),
            context_sets=(),
            exceptions=replace(starter_policy().exceptions, records=(broad, exact)),
        )
        current = replace(base, exceptions=replace(base.exceptions, records=(broad,)))

        evaluation = evaluate_sizes(
            compile_size_policy(current),
            (regular("generated/safe.txt", 10),),
            lambda _entry: self.fail("an incomplete effective policy must fail before reading"),
            evaluation_date=TODAY,
        )

        self.assertEqual(tuple(item.code for item in evaluation.diagnostics), (CFG_EFFECTIVE_POLICY,))
        diagnostics = compare_policies(current, base)
        self.assertIn(RAT_EXCEPTION_BROADENED, {item.code for item in diagnostics})
        self.assertIn("exception_removal_exposes_weaker_fallback", _reasons(diagnostics))

    def test_base_only_cfg015_is_not_a_monotone_guarantee_and_can_be_repaired(self) -> None:
        generated = FileRule("generated", ("generated/**",), FileKind.GENERATED, False, None, None)
        authored = FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20)
        exact = _exception(
            ExactSelector("generated/safe.txt"),
            scan=True,
            warn_bytes=None,
            hard_bytes=None,
        )
        base = replace(
            starter_policy(),
            file_rules=(generated, authored),
            path_overrides=(),
            context_sets=(),
            exceptions=replace(starter_policy().exceptions, records=(exact,)),
        )
        repaired = replace(
            base,
            file_rules=(replace(generated, scan=True, warn_bytes=10, hard_bytes=20), authored),
        )
        entry = (regular("generated/safe.txt", 10),)
        base_evaluation = evaluate_sizes(
            compile_size_policy(base),
            entry,
            lambda _entry: self.fail("base CFG015 must occur before reading"),
            evaluation_date=TODAY,
        )
        self.assertEqual(tuple(item.code for item in base_evaluation.diagnostics), (CFG_EFFECTIVE_POLICY,))
        for remove_exact in (False, True):
            with self.subTest(remove_exact=remove_exact):
                current = (
                    replace(repaired, exceptions=replace(base.exceptions, records=()))
                    if remove_exact
                    else repaired
                )
                current_evaluation = evaluate_sizes(
                    compile_size_policy(current),
                    entry,
                    lambda _entry: b"x" * 10,
                    evaluation_date=TODAY,
                )
                self.assertEqual(current_evaluation.diagnostics, ())
                self.assertEqual(compare_policies(current, base), ())

    def test_base_cfg015_cannot_be_repaired_by_leaving_path_unscanned(self) -> None:
        generated = FileRule("generated", ("generated/**",), FileKind.GENERATED, False, None, None)
        authored = FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20)
        exact = _exception(
            ExactSelector("generated/safe.txt"),
            scan=None,
            warn_bytes=10,
            hard_bytes=20,
        )
        base = replace(
            starter_policy(),
            file_rules=(generated, authored),
            path_overrides=(),
            context_sets=(),
            exceptions=replace(starter_policy().exceptions, records=(exact,)),
        )
        current = replace(base, exceptions=replace(base.exceptions, records=()))
        entry = (regular("generated/safe.txt", 10),)

        base_evaluation = evaluate_sizes(
            compile_size_policy(base),
            entry,
            lambda _entry: self.fail("base CFG015 must occur before reading"),
            evaluation_date=TODAY,
        )
        current_evaluation = evaluate_sizes(
            compile_size_policy(current),
            entry,
            lambda _entry: self.fail("an unscanned path must not be read"),
            evaluation_date=TODAY,
        )

        self.assertEqual(tuple(item.code for item in base_evaluation.diagnostics), (CFG_EFFECTIVE_POLICY,))
        self.assertEqual(current_evaluation.diagnostics, ())
        diagnostics = compare_policies(current, base)
        self.assertIn(RAT_EXCEPTION_BROADENED, {item.code for item in diagnostics})
        self.assertIn("exception_removal_exposes_weaker_fallback", _reasons(diagnostics))


if __name__ == "__main__":
    unittest.main()
