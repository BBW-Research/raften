from __future__ import annotations

import unittest

from repo_context.diagnostics import (
    CFG_AMBIGUOUS_OVERRIDE,
    CFG_CATCH_ALL,
    CFG_DUPLICATE_NAME,
    CFG_DUPLICATE_SELECTOR,
    CFG_INCONSISTENT,
    CFG_LIMIT,
    CFG_MISSING_KEY,
    CFG_PATH,
    CFG_PATTERN,
    CFG_UNKNOWN_KEY,
    CFG_VALUE,
    EXC_BROAD_SELECTOR,
    config_diagnostic_sort_key,
)
from tests.support.config import STARTER_POLICY_TEXT, append_exception_record, replace_once
from tests.support.config_assertions import ConfigurationAssertions


def insert_before(text: str, marker: str, addition: str) -> str:
    index = text.index(marker)
    return text[:index] + f"{addition.strip()}\n\n" + text[index:]


class FixedTableInvariantTests(ConfigurationAssertions):
    def test_repository_may_not_enable_global_symlink_following(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "follow_symlinks = false", "follow_symlinks = true")
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "repository.follow_symlinks")

    def test_output_may_not_disable_stable_sorting(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "stable_sort = true", "stable_sort = false")
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "output.stable_sort")


class FileRuleInvariantTests(ConfigurationAssertions):
    def test_file_rule_names_and_patterns_are_unique(self) -> None:
        duplicate_name = replace_once(STARTER_POLICY_TEXT, 'name = "authored"', 'name = "generated-state"')
        self.assert_policy_diagnostic(duplicate_name, CFG_DUPLICATE_NAME, "file_rule[1].name")

        duplicate_pattern = replace_once(
            STARTER_POLICY_TEXT,
            'patterns = ["**"]',
            'patterns = ["uv.lock", "**"]',
        )
        self.assert_policy_diagnostic(
            duplicate_pattern,
            CFG_DUPLICATE_SELECTOR,
            "file_rule[1].patterns[0]",
        )

    def test_file_rule_requires_one_dedicated_catch_all(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, 'patterns = ["**"]', 'patterns = ["**/*.py"]')
        self.assert_policy_diagnostic(text, CFG_CATCH_ALL, "file_rule")

    def test_catch_all_must_be_the_final_file_rule(self) -> None:
        text = insert_before(
            STARTER_POLICY_TEXT,
            "[[path_override]]\n",
            '''[[file_rule]]
name = "generated-reports"
patterns = ["reports/**/*.json"]
kind = "generated"
scan = false
reason = "Reproducible reports are classified explicitly."''',
        )
        self.assert_policy_diagnostic(text, CFG_CATCH_ALL, "file_rule[1].patterns")

    def test_catch_all_must_be_scanned_and_authored(self) -> None:
        text = replace_once(
            STARTER_POLICY_TEXT,
            '''name = "authored"
patterns = ["**"]
kind = "authored"''',
            '''name = "authored"
patterns = ["**"]
kind = "fixture"''',
        )
        self.assert_policy_diagnostic(text, CFG_CATCH_ALL, "file_rule[1]")

    def test_scanned_rules_require_a_complete_limit_pair(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "warn_bytes = 20480\n", "")
        self.assert_policy_diagnostic(text, CFG_MISSING_KEY, "file_rule[1].warn_bytes")

    def test_unscanned_rules_require_a_reason_and_forbid_limits(self) -> None:
        missing_reason = replace_once(
            STARTER_POLICY_TEXT,
            'reason = "Machine-generated dependency and migration state is validated by its owning tool."\n',
            "",
        )
        self.assert_policy_diagnostic(missing_reason, CFG_MISSING_KEY, "file_rule[0].reason")

        with_limits = replace_once(
            STARTER_POLICY_TEXT,
            "scan = false\nreason =",
            "scan = false\nwarn_bytes = 100\nhard_bytes = 200\nreason =",
        )
        self.assert_policy_diagnostic(with_limits, CFG_INCONSISTENT, "file_rule[0]")

    def test_authored_rules_may_not_disable_scanning(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, 'kind = "generated"', 'kind = "authored"')
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "file_rule[0].scan")

    def test_byte_limits_are_positive_and_strictly_increasing(self) -> None:
        cases = (
            (
                replace_once(STARTER_POLICY_TEXT, "warn_bytes = 20480", "warn_bytes = 0"),
                "file_rule[1].warn_bytes",
            ),
            (
                replace_once(STARTER_POLICY_TEXT, "hard_bytes = 25600", "hard_bytes = 20480"),
                "file_rule[1].hard_bytes",
            ),
        )
        for text, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(text, CFG_LIMIT, field_path)

    def test_human_facing_rule_names_may_not_be_blank(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, 'name = "generated-state"', 'name = "   "')
        self.assert_policy_diagnostic(text, CFG_VALUE, "file_rule[0].name")

    def test_human_facing_values_reject_unicode_control_characters(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, 'name = "generated-state"', 'name = "\\u0085"')
        self.assert_policy_diagnostic(text, CFG_VALUE, "file_rule[0].name")


class OverrideInvariantTests(ConfigurationAssertions):
    def test_override_requires_exactly_one_selector(self) -> None:
        neither = replace_once(
            STARTER_POLICY_TEXT,
            'path = "AGENTS.md"\nwarn_bytes = 8192',
            "warn_bytes = 8192",
        )
        self.assert_policy_diagnostic(neither, CFG_INCONSISTENT, "path_override[0]")

        both = replace_once(
            STARTER_POLICY_TEXT,
            'path = "AGENTS.md"\nwarn_bytes = 8192',
            'path = "AGENTS.md"\npattern = "docs/*.md"\nwarn_bytes = 8192',
        )
        self.assert_policy_diagnostic(both, CFG_INCONSISTENT, "path_override[0]")

    def test_pattern_selector_must_actually_contain_a_wildcard(self) -> None:
        text = replace_once(
            STARTER_POLICY_TEXT,
            'pattern = "docs/**/index.md"',
            'pattern = "docs/index.md"',
        )
        self.assert_policy_diagnostic(text, CFG_PATTERN, "path_override[3].pattern")

    def test_exact_and_pattern_override_selectors_are_unique(self) -> None:
        exact = insert_before(
            STARTER_POLICY_TEXT,
            "[documentation]\n",
            '''[[path_override]]
path = "AGENTS.md"
warn_bytes = 4000
hard_bytes = 5000''',
        )
        self.assert_policy_diagnostic(exact, CFG_DUPLICATE_SELECTOR, "path_override[4].path")

        pattern = insert_before(
            STARTER_POLICY_TEXT,
            "[documentation]\n",
            '''[[path_override]]
pattern = "docs/**/index.md"
warn_bytes = 4000
hard_bytes = 5000''',
        )
        self.assert_policy_diagnostic(pattern, CFG_DUPLICATE_SELECTOR, "path_override[4].pattern")

    def test_overlapping_equal_specificity_patterns_are_ambiguous(self) -> None:
        text = insert_before(
            STARTER_POLICY_TEXT,
            "[documentation]\n",
            '''[[path_override]]
pattern = "source/*.txt"
warn_bytes = 100
hard_bytes = 200

[[path_override]]
pattern = "source/?.txt"
warn_bytes = 100
hard_bytes = 200''',
        )
        self.assert_policy_diagnostic(text, CFG_AMBIGUOUS_OVERRIDE, "path_override[5].pattern")


class PathAndDocumentationInvariantTests(ConfigurationAssertions):
    def test_configured_exact_paths_and_patterns_use_repository_syntax(self) -> None:
        unsafe_path = replace_once(
            STARTER_POLICY_TEXT,
            'path = "AGENTS.md"\nwarn_bytes = 8192',
            'path = "../AGENTS.md"\nwarn_bytes = 8192',
        )
        self.assert_policy_diagnostic(unsafe_path, CFG_PATH, "path_override[0].path")

        malformed_pattern = replace_once(
            STARTER_POLICY_TEXT,
            'pattern = "docs/**/index.md"',
            'pattern = "docs/**index.md"',
        )
        self.assert_policy_diagnostic(malformed_pattern, CFG_PATTERN, "path_override[3].pattern")

    def test_documentation_roots_are_index_files(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, 'roots = ["docs/index.md"]', 'roots = ["docs/README.md"]')
        self.assert_policy_diagnostic(text, CFG_VALUE, "documentation.roots[0]")

    def test_documentation_roots_may_not_be_empty(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, 'roots = ["docs/index.md"]', "roots = []")
        self.assert_policy_diagnostic(text, CFG_VALUE, "documentation.roots")

    def test_documentation_roots_may_not_be_explicitly_or_globally_excluded(self) -> None:
        for exclusion in ('["docs/index.md"]', '["**"]'):
            with self.subTest(exclusion=exclusion):
                text = replace_once(STARTER_POLICY_TEXT, "exclude = []", f"exclude = {exclusion}")
                self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "documentation.roots[0]")

    def test_hierarchical_navigation_requires_directory_indexes(self) -> None:
        for key in ("require_sibling_links", "require_child_index_links"):
            with self.subTest(key=key):
                text = replace_once(STARTER_POLICY_TEXT, "require_directory_indexes = true", "require_directory_indexes = false")
                self.assert_policy_diagnostic(text, CFG_INCONSISTENT, f"documentation.{key}")

    def test_fragment_checks_require_local_target_checks(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "check_local_targets = true", "check_local_targets = false")
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "documentation.check_fragments")

    def test_authored_document_symlink_following_is_not_supported(self) -> None:
        text = replace_once(
            STARTER_POLICY_TEXT,
            "allow_authored_symlinks = false",
            "allow_authored_symlinks = true",
        )
        self.assert_policy_diagnostic(
            text,
            CFG_INCONSISTENT,
            "documentation.allow_authored_symlinks",
        )


class EntrypointAndContextInvariantTests(ConfigurationAssertions):
    def test_entrypoint_paths_are_unique(self) -> None:
        text = replace_once(
            STARTER_POLICY_TEXT,
            '[[entrypoint]]\npath = "README.md"\nrequired_targets = ["docs/index.md"]',
            '[[entrypoint]]\npath = "AGENTS.md"\nrequired_targets = ["docs/index.md"]',
        )
        self.assert_policy_diagnostic(text, CFG_DUPLICATE_SELECTOR, "entrypoint[1].path")

    def test_entrypoint_targets_are_nonempty_unique_and_not_self_referential(self) -> None:
        cases = (
            (
                replace_once(
                    STARTER_POLICY_TEXT,
                    'path = "AGENTS.md"\nrequired_targets = ["docs/index.md"]\n\n[[entrypoint]]',
                    'path = "AGENTS.md"\nrequired_targets = []\n\n[[entrypoint]]',
                ),
                CFG_VALUE,
                "entrypoint[0].required_targets",
            ),
            (
                replace_once(
                    STARTER_POLICY_TEXT,
                    'path = "AGENTS.md"\nrequired_targets = ["docs/index.md"]\n\n[[entrypoint]]',
                    'path = "AGENTS.md"\nrequired_targets = ["docs/index.md", "docs/index.md"]\n\n[[entrypoint]]',
                ),
                CFG_DUPLICATE_SELECTOR,
                "entrypoint[0].required_targets[1]",
            ),
            (
                replace_once(
                    STARTER_POLICY_TEXT,
                    'path = "AGENTS.md"\nrequired_targets = ["docs/index.md"]\n\n[[entrypoint]]',
                    'path = "AGENTS.md"\nrequired_targets = ["AGENTS.md"]\n\n[[entrypoint]]',
                ),
                CFG_INCONSISTENT,
                "entrypoint[0].required_targets",
            ),
        )
        for text, code, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(text, code, field_path)

    def test_context_sets_require_a_selector_and_unique_name(self) -> None:
        no_selector = replace_once(
            STARTER_POLICY_TEXT,
            'paths = ["AGENTS.md", "ARCHITECTURE.md", "docs/index.md"]\n',
            "",
        )
        self.assert_policy_diagnostic(no_selector, CFG_VALUE, "context_set[0]")

        duplicate_name = insert_before(
            STARTER_POLICY_TEXT,
            "[ratchet]\n",
            '''[[context_set]]
name = "bootstrap"
paths = ["README.md"]
warn_bytes = 1000
hard_bytes = 2000''',
        )
        self.assert_policy_diagnostic(duplicate_name, CFG_DUPLICATE_NAME, "context_set[1].name")

    def test_context_patterns_must_be_narrow(self) -> None:
        text = replace_once(
            STARTER_POLICY_TEXT,
            'paths = ["AGENTS.md", "ARCHITECTURE.md", "docs/index.md"]',
            'patterns = ["**/*.md"]',
        )
        self.assert_policy_diagnostic(text, CFG_PATTERN, "context_set[0].patterns[0]")


class RatchetAndExceptionInvariantTests(ConfigurationAssertions):
    def test_new_oversize_ratchet_requires_base_size_comparison(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "compare_file_sizes = true", "compare_file_sizes = false")
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "ratchet.forbid_new_oversize")

    def test_exception_governance_cannot_be_disabled(self) -> None:
        cases = (
            ("require_reason = true", "require_reason = false", "exceptions.require_reason"),
            ("require_owner = true", "require_owner = false", "exceptions.require_owner"),
            (
                "require_tracking_reference = true",
                "require_tracking_reference = false",
                "exceptions.require_tracking_reference",
            ),
            ("allow_expired = false", "allow_expired = true", "exceptions.allow_expired"),
        )
        for old, new, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(
                    replace_once(STARTER_POLICY_TEXT, old, new),
                    CFG_INCONSISTENT,
                    field_path,
                )

    def test_exception_patterns_must_be_narrow(self) -> None:
        text = append_exception_record(
            STARTER_POLICY_TEXT,
            '''pattern = "**/*.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false''',
        )
        self.assert_policy_diagnostic(text, EXC_BROAD_SELECTOR, "exceptions.record[0].pattern")

    def test_exception_requires_exactly_one_selector(self) -> None:
        text = append_exception_record(
            STARTER_POLICY_TEXT,
            '''path = "generated/schema.json"
pattern = "generated/*.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false''',
        )
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "exceptions.record[0]")

    def test_exception_requires_replacement_behavior(self) -> None:
        text = append_exception_record(
            STARTER_POLICY_TEXT,
            '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01''',
        )
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "exceptions.record[0]")

    def test_exception_thresholds_are_complete_and_incompatible_with_scan_false(self) -> None:
        partial = append_exception_record(
            STARTER_POLICY_TEXT,
            '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
warn_bytes = 30000''',
        )
        self.assert_policy_diagnostic(partial, CFG_MISSING_KEY, "exceptions.record[0].hard_bytes")

        unscanned = append_exception_record(
            STARTER_POLICY_TEXT,
            '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false
warn_bytes = 30000
hard_bytes = 40000''',
        )
        self.assert_policy_diagnostic(unscanned, CFG_INCONSISTENT, "exceptions.record[0]")

    def test_exception_expiry_may_not_precede_creation(self) -> None:
        text = append_exception_record(
            STARTER_POLICY_TEXT,
            '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-02
expires_on = 2026-08-01
scan = false''',
        )
        self.assert_policy_diagnostic(text, CFG_INCONSISTENT, "exceptions.record[0].expires_on")

    def test_exception_selectors_are_unique(self) -> None:
        body = '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false'''
        text = append_exception_record(append_exception_record(STARTER_POLICY_TEXT, body), body)
        self.assert_policy_diagnostic(text, CFG_DUPLICATE_SELECTOR, "exceptions.record[1].path")

    def test_overlapping_equal_specificity_exception_patterns_are_ambiguous(self) -> None:
        first = '''pattern = "temporary/*.txt"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false'''
        second = '''pattern = "temporary/?.txt"
owner = "tooling"
rationale = "A different temporary boundary"
tracking_reference = "ADR-43"
created_on = 2026-08-01
scan = false'''
        text = append_exception_record(
            append_exception_record(STARTER_POLICY_TEXT, first),
            second,
        )
        self.assert_policy_diagnostic(
            text,
            CFG_AMBIGUOUS_OVERRIDE,
            "exceptions.record[1].pattern",
        )

    def test_exception_metadata_may_not_be_blank(self) -> None:
        text = append_exception_record(
            STARTER_POLICY_TEXT,
            '''path = "generated/schema.json"
owner = " "
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false''',
        )
        self.assert_policy_diagnostic(text, CFG_VALUE, "exceptions.record[0].owner")


class DiagnosticContractTests(ConfigurationAssertions):
    def test_multiple_diagnostics_have_stable_identity_paths_and_order(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "version = 1\n", "version = 1\nzeta = true\nalpha = true\n")
        diagnostics = self.policy_diagnostics(text)
        self.assertEqual(list(diagnostics), sorted(diagnostics, key=config_diagnostic_sort_key))
        self.assertEqual(
            [(item.code, item.field_path) for item in diagnostics],
            [(CFG_UNKNOWN_KEY, "alpha"), (CFG_UNKNOWN_KEY, "zeta")],
        )
        self.assertTrue(all(item.location is not None for item in diagnostics))
        self.assertTrue(all(item.location.path == "fixture.toml" for item in diagnostics if item.location))

    def test_codes_precede_field_paths_when_source_positions_are_equal(self) -> None:
        text = replace_once(STARTER_POLICY_TEXT, "version = 1\n", "zeta = true\n")
        diagnostics = self.policy_diagnostics(text)
        self.assertEqual(
            [(item.code, item.field_path) for item in diagnostics[:2]],
            [(CFG_UNKNOWN_KEY, "zeta"), (CFG_MISSING_KEY, "version")],
        )


if __name__ == "__main__":
    unittest.main()
