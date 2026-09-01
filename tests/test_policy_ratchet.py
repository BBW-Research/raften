from __future__ import annotations

import unittest
from dataclasses import replace

from repo_context.config import starter_policy
from repo_context.diagnostics import (
    RAT_CONTEXT_WEAKENED,
    RAT_DOCUMENTATION_WEAKENED,
    RAT_ENTRYPOINT_WEAKENED,
    RAT_EXCEPTION_BROADENED,
    RAT_FILE_LIMIT_INCREASED,
    RAT_FILE_POLICY_WEAKENED,
    RAT_OVERRIDE_WEAKENED,
    RAT_RATCHET_DISABLED,
)
from repo_context.model import (
    ContextSet,
    Entrypoint,
    FileKind,
    FileRule,
    PathOverride,
    PatternSelector,
)
from repo_context.policy_ratchet import compare_policies
from tests.support.repository import seed_policy
from tests.support.seed import SEED


def _reasons(diagnostics):
    return tuple(dict(item.details)["reason"] for item in diagnostics)


class PolicyRatchetTests(unittest.TestCase):
    def test_policy_ratchet_diagnostic_identities_are_frozen(self) -> None:
        self.assertEqual(
            (
                RAT_FILE_LIMIT_INCREASED,
                RAT_OVERRIDE_WEAKENED,
                RAT_FILE_POLICY_WEAKENED,
                RAT_DOCUMENTATION_WEAKENED,
                RAT_ENTRYPOINT_WEAKENED,
                RAT_CONTEXT_WEAKENED,
                RAT_RATCHET_DISABLED,
                RAT_EXCEPTION_BROADENED,
            ),
            (
                "RAT006",
                "RAT007",
                "RAT008",
                "RAT009",
                "RAT010",
                "RAT011",
                "RAT012",
                "RAT013",
            ),
        )

    def test_identical_policy_has_no_weakening(self) -> None:
        policy = starter_policy()
        self.assertEqual(compare_policies(policy, policy), ())

    def test_scanned_rule_limit_increases_are_reported_independently(self) -> None:
        base = starter_policy()
        authored = base.file_rules[-1]
        current = replace(
            base,
            file_rules=(*base.file_rules[:-1], replace(authored, warn_bytes=30_000, hard_bytes=31_000)),
        )

        diagnostics = compare_policies(current, base)

        self.assertEqual(tuple(item.code for item in diagnostics), (RAT_FILE_LIMIT_INCREASED,) * 2)
        self.assertEqual(set(_reasons(diagnostics)), {"warning_limit_increased", "hard_limit_increased"})

    def test_scanned_rule_identity_kind_and_precedence_cannot_be_weakened(self) -> None:
        base = replace(
            starter_policy(),
            file_rules=(
                FileRule("python", ("src/**/*.py",), FileKind.AUTHORED, True, 10, 20),
                FileRule("docs", ("docs/**",), FileKind.AUTHORED, True, 10, 20),
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20),
            ),
        )
        cases = (
            (
                "scanned_rule_removed",
                replace(base, file_rules=base.file_rules[1:]),
            ),
            (
                "scanned_patterns_changed",
                replace(base, file_rules=(replace(base.file_rules[0], patterns=("src/**",)), *base.file_rules[1:])),
            ),
            (
                "authored_classification_removed",
                replace(base, file_rules=(replace(base.file_rules[0], kind=FileKind.FIXTURE), *base.file_rules[1:])),
            ),
            (
                "file_rule_precedence_changed",
                replace(base, file_rules=(base.file_rules[1], base.file_rules[0], base.file_rules[2])),
            ),
        )
        for reason, current in cases:
            with self.subTest(reason=reason):
                diagnostics = compare_policies(current, base)
                self.assertIn(RAT_FILE_POLICY_WEAKENED, {item.code for item in diagnostics})
                self.assertIn(reason, _reasons(diagnostics))

    def test_unscanned_expansion_is_reported_without_seed_exemptions(self) -> None:
        added_rule = FileRule(
            "structured-data",
            ("config/*.json", "schemas/*.json"),
            FileKind.GENERATED,
            False,
            None,
            None,
            "generated structured data",
        )
        seed_base = seed_policy(text_excluded_globs=[])
        seed_current = seed_policy(
            text_excluded_globs=["config/*.json", "schemas/*.json"],
        )

        self.assertEqual(SEED.check_not_weakened(seed_current, seed_base), [])
        for exclusion_guard, limit_guard, expected_count in (
            (True, True, 2),
            (False, True, 2),
            (False, False, 0),
        ):
            with self.subTest(exclusion_guard=exclusion_guard, limit_guard=limit_guard):
                base = replace(
                    starter_policy(),
                    ratchet=replace(
                        starter_policy().ratchet,
                        forbid_exclusion_expansion=exclusion_guard,
                        forbid_limit_increases=limit_guard,
                    ),
                )
                current = replace(base, file_rules=(added_rule, *base.file_rules))
                diagnostics = compare_policies(current, base)
                self.assertEqual(
                    tuple(item.code for item in diagnostics),
                    (RAT_FILE_POLICY_WEAKENED,) * expected_count,
                )
                self.assertEqual(
                    set(_reasons(diagnostics)),
                    {"unscanned_pattern_added"} if expected_count else set(),
                )

    def test_retained_unscanned_rule_cannot_move_ahead_of_scanned_coverage(self) -> None:
        rules = (
            FileRule("docs", ("docs/**",), FileKind.AUTHORED, True, 10, 20),
            FileRule("generated", ("docs/generated/**",), FileKind.GENERATED, False, None, None),
            FileRule("authored", ("**",), FileKind.AUTHORED, True, 15, 30),
        )
        for exclusion_guard in (True, False):
            with self.subTest(exclusion_guard=exclusion_guard):
                base = replace(
                    starter_policy(),
                    file_rules=rules,
                    ratchet=replace(
                        starter_policy().ratchet,
                        forbid_exclusion_expansion=exclusion_guard,
                    ),
                )
                current = replace(
                    base,
                    file_rules=(rules[1], rules[0], rules[2]),
                )

                diagnostics = compare_policies(current, base)

                self.assertIn(RAT_FILE_POLICY_WEAKENED, {item.code for item in diagnostics})
                self.assertIn("unscanned_rule_moved_ahead", _reasons(diagnostics))

    def test_retained_scanned_precedence_is_guarded_when_only_limits_are_monotone(self) -> None:
        strict = FileRule("python", ("src/**/*.py",), FileKind.AUTHORED, True, 10, 20)
        broad = FileRule("source", ("src/**",), FileKind.AUTHORED, True, 15, 30)
        catch_all = FileRule("authored", ("**",), FileKind.AUTHORED, True, 20, 40)
        base = replace(
            starter_policy(),
            file_rules=(strict, broad, catch_all),
            ratchet=replace(
                starter_policy().ratchet,
                forbid_exclusion_expansion=False,
            ),
        )
        current = replace(base, file_rules=(broad, strict, catch_all))

        diagnostics = compare_policies(current, base)

        self.assertIn(RAT_FILE_POLICY_WEAKENED, {item.code for item in diagnostics})
        self.assertIn("file_rule_precedence_changed", _reasons(diagnostics))

    def test_enabling_retained_unscanned_rule_checks_new_selectors_and_limits(self) -> None:
        vendor = FileRule("vendor", ("vendor/**",), FileKind.VENDORED, False, None, None)
        docs = FileRule("docs", ("docs/**",), FileKind.AUTHORED, True, 10, 20)
        catch_all = FileRule("authored", ("**",), FileKind.AUTHORED, True, 15, 30)
        base = replace(starter_policy(), file_rules=(vendor, docs, catch_all))
        current = replace(
            base,
            file_rules=(
                replace(
                    vendor,
                    patterns=("vendor/**", "docs/**"),
                    kind=FileKind.GENERATED,
                    scan=True,
                    warn_bytes=100,
                    hard_bytes=200,
                ),
                docs,
                catch_all,
            ),
        )

        diagnostics = compare_policies(current, base)

        self.assertIn(RAT_FILE_POLICY_WEAKENED, {item.code for item in diagnostics})
        self.assertIn(RAT_FILE_LIMIT_INCREASED, {item.code for item in diagnostics})
        self.assertIn("authored_classification_removed", _reasons(diagnostics))
        self.assertIn("new_scanned_rule_hard_limit_increased", _reasons(diagnostics))

    def test_retained_unscanned_classification_is_stable(self) -> None:
        generated = FileRule("generated", ("generated/**",), FileKind.GENERATED, False, None, None)
        catch_all = FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20)
        base = replace(starter_policy(), file_rules=(generated, catch_all))
        current = replace(
            base,
            file_rules=(replace(generated, kind=FileKind.VENDORED), catch_all),
        )

        diagnostics = compare_policies(current, base)

        self.assertIn(RAT_FILE_POLICY_WEAKENED, {item.code for item in diagnostics})
        self.assertIn("unscanned_classification_changed", _reasons(diagnostics))

    def test_new_scanned_rule_must_be_authored_and_no_weaker_than_overlap(self) -> None:
        base = replace(
            starter_policy(),
            file_rules=(FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20),),
        )
        safe = replace(
            base,
            file_rules=(
                FileRule("python", ("src/**/*.py",), FileKind.AUTHORED, True, 5, 10),
                *base.file_rules,
            ),
        )
        weaker = replace(
            base,
            file_rules=(
                FileRule("python", ("src/**/*.py",), FileKind.AUTHORED, True, 15, 25),
                *base.file_rules,
            ),
        )
        reclassified = replace(
            base,
            file_rules=(
                FileRule("python", ("src/**/*.py",), FileKind.FIXTURE, True, 5, 10),
                *base.file_rules,
            ),
        )

        self.assertEqual(compare_policies(safe, base), ())
        self.assertIn(RAT_FILE_LIMIT_INCREASED, {item.code for item in compare_policies(weaker, base)})
        self.assertIn(RAT_FILE_POLICY_WEAKENED, {item.code for item in compare_policies(reclassified, base)})

        limits_only_base = replace(
            base,
            ratchet=replace(base.ratchet, forbid_exclusion_expansion=False),
        )
        limits_only_weaker = replace(weaker, ratchet=limits_only_base.ratchet)
        structure_only_base = replace(
            base,
            ratchet=replace(base.ratchet, forbid_limit_increases=False),
        )
        structure_only_weaker = replace(weaker, ratchet=structure_only_base.ratchet)
        self.assertIn(
            RAT_FILE_LIMIT_INCREASED,
            {item.code for item in compare_policies(limits_only_weaker, limits_only_base)},
        )
        self.assertNotIn(
            RAT_FILE_LIMIT_INCREASED,
            {item.code for item in compare_policies(structure_only_weaker, structure_only_base)},
        )

    def test_removing_or_increasing_an_override_is_reported(self) -> None:
        base = starter_policy()
        removed = replace(base, path_overrides=base.path_overrides[1:])
        increased = replace(
            base,
            path_overrides=(replace(base.path_overrides[0], hard_bytes=20_000), *base.path_overrides[1:]),
        )

        removed_diagnostics = compare_policies(removed, base)
        increased_diagnostics = compare_policies(increased, base)

        self.assertIn(RAT_OVERRIDE_WEAKENED, {item.code for item in removed_diagnostics})
        self.assertIn("override_removed", _reasons(removed_diagnostics))
        self.assertIn(RAT_OVERRIDE_WEAKENED, {item.code for item in increased_diagnostics})
        self.assertIn("hard_limit_increased", _reasons(increased_diagnostics))

    def test_new_override_that_can_displace_a_tighter_base_override_is_reported(self) -> None:
        base = replace(
            starter_policy(),
            path_overrides=(PathOverride(PatternSelector("docs/**"), 5, 10),),
        )
        current = replace(
            base,
            path_overrides=(
                *base.path_overrides,
                PathOverride(PatternSelector("docs/api/**"), 8, 12),
            ),
        )

        diagnostics = compare_policies(current, base)
        self.assertIn("displacing_override_added", _reasons(diagnostics))

    def test_documentation_roots_exclusions_and_every_true_requirement_are_monotone(self) -> None:
        base = starter_policy()
        current = replace(
            base,
            documentation=replace(
                base.documentation,
                roots=("other/index.md",),
                exclude=("docs/private/**",),
                require_directory_indexes=False,
                require_sibling_links=False,
                require_child_index_links=False,
                require_root_reachability=False,
                check_local_targets=False,
                check_fragments=False,
            ),
        )

        diagnostics = compare_policies(current, base)

        self.assertEqual({item.code for item in diagnostics}, {RAT_DOCUMENTATION_WEAKENED})
        self.assertEqual(
            set(_reasons(diagnostics)),
            {
                "documentation_root_removed",
                "documentation_exclusion_added",
                "documentation_requirement_disabled",
            },
        )

    def test_nested_documentation_root_is_a_reachability_weakening(self) -> None:
        base = starter_policy()
        nested = replace(
            base,
            documentation=replace(
                base.documentation,
                roots=(*base.documentation.roots, "docs/orphan.md"),
            ),
        )
        external = replace(
            base,
            documentation=replace(
                base.documentation,
                roots=(*base.documentation.roots, "handbook/index.md"),
            ),
        )

        diagnostics = compare_policies(nested, base)

        self.assertIn(RAT_DOCUMENTATION_WEAKENED, {item.code for item in diagnostics})
        self.assertIn("reachability_root_added_within_governed_tree", _reasons(diagnostics))
        self.assertEqual(compare_policies(external, base), ())

    def test_entrypoint_removal_and_target_removal_are_reported(self) -> None:
        base = replace(
            starter_policy(),
            entrypoints=(Entrypoint("README.md", ("docs/index.md", "ARCHITECTURE.md")),),
        )
        removed_entrypoint = replace(base, entrypoints=())
        removed_target = replace(
            base,
            entrypoints=(Entrypoint("README.md", ("docs/index.md",)),),
        )

        self.assertIn("entrypoint_removed", _reasons(compare_policies(removed_entrypoint, base)))
        target_diagnostics = compare_policies(removed_target, base)
        self.assertEqual(tuple(item.code for item in target_diagnostics), (RAT_ENTRYPOINT_WEAKENED,))
        self.assertEqual(_reasons(target_diagnostics), ("required_target_removed",))

    def test_context_set_members_limits_and_identity_are_monotone(self) -> None:
        context = ContextSet(
            "bootstrap",
            ("AGENTS.md", "docs/index.md"),
            ("src/**/*.py",),
            100,
            200,
        )
        base = replace(starter_policy(), context_sets=(context,))
        cases = (
            ("context_set_removed", replace(base, context_sets=())),
            (
                "context_path_removed",
                replace(base, context_sets=(replace(context, paths=("AGENTS.md",)),)),
            ),
            (
                "context_pattern_removed",
                replace(base, context_sets=(replace(context, patterns=()),)),
            ),
            (
                "warning_limit_increased",
                replace(base, context_sets=(replace(context, warn_bytes=150),)),
            ),
            (
                "hard_limit_increased",
                replace(base, context_sets=(replace(context, hard_bytes=250),)),
            ),
        )
        for reason, current in cases:
            with self.subTest(reason=reason):
                diagnostics = compare_policies(current, base)
                self.assertIn(RAT_CONTEXT_WEAKENED, {item.code for item in diagnostics})
                self.assertIn(reason, _reasons(diagnostics))

    def test_every_base_ratchet_boolean_is_monotone(self) -> None:
        base = starter_policy()
        current = replace(
            base,
            ratchet=replace(
                base.ratchet,
                compare_file_sizes=False,
                forbid_new_oversize=False,
                forbid_limit_increases=False,
                forbid_exclusion_expansion=False,
                forbid_removed_documentation_roots=False,
                forbid_removed_entrypoint_targets=False,
            ),
        )

        diagnostics = compare_policies(current, base)

        self.assertEqual(tuple(item.code for item in diagnostics), (RAT_RATCHET_DISABLED,) * 6)
        self.assertEqual(
            {dict(item.details)["setting"] for item in diagnostics},
            {
                "compare_file_sizes",
                "forbid_new_oversize",
                "forbid_limit_increases",
                "forbid_exclusion_expansion",
                "forbid_removed_documentation_roots",
                "forbid_removed_entrypoint_targets",
            },
        )

    def test_current_flag_cannot_disable_its_own_base_comparison(self) -> None:
        base = starter_policy()
        authored = base.file_rules[-1]
        current = replace(
            base,
            file_rules=(
                *base.file_rules[:-1],
                replace(authored, warn_bytes=30_000, hard_bytes=31_000),
            ),
            ratchet=replace(base.ratchet, forbid_limit_increases=False),
        )

        codes = {item.code for item in compare_policies(current, base)}
        self.assertEqual(codes, {RAT_FILE_LIMIT_INCREASED, RAT_RATCHET_DISABLED})

    def test_safe_tightening_is_accepted(self) -> None:
        base = starter_policy()
        authored = base.file_rules[-1]
        current = replace(
            base,
            file_rules=(*base.file_rules[:-1], replace(authored, warn_bytes=10_000, hard_bytes=20_000)),
            documentation=replace(base.documentation, roots=(*base.documentation.roots, "handbook/index.md")),
            entrypoints=tuple(
                replace(item, required_targets=(*item.required_targets, "SECURITY.md"))
                for item in base.entrypoints
            ),
            context_sets=tuple(
                replace(item, paths=(*item.paths, "README.md"), warn_bytes=20_000, hard_bytes=30_000)
                for item in base.context_sets
            ),
        )

        self.assertEqual(compare_policies(current, base), ())

    def test_diagnostics_have_current_policy_location_and_deterministic_order(self) -> None:
        base = starter_policy()
        current = replace(
            base,
            documentation=replace(base.documentation, roots=()),
            entrypoints=(),
            ratchet=replace(base.ratchet, compare_file_sizes=False),
        )
        first = compare_policies(current, base, policy_path="config/policy.toml")
        second = compare_policies(current, base, policy_path="config/policy.toml")

        self.assertEqual(first, second)
        self.assertTrue(all(item.location.path == "config/policy.toml" for item in first))
        self.assertEqual(first, tuple(sorted(first, key=lambda item: (item.location.path, item.code, item.field_path or "", repr(item.details)))))


if __name__ == "__main__":
    unittest.main()
