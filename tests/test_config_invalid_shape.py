from __future__ import annotations

import unittest

from repo_context.diagnostics import (
    CFG_MISSING_KEY,
    CFG_PARSE,
    CFG_TYPE,
    CFG_UNKNOWN_KEY,
    CFG_VALUE,
)
from tests.support.config import ROOT_POLICY_TEXT, append_exception_record, replace_once
from tests.support.config_assertions import ConfigurationAssertions


class ParseFailureTests(ConfigurationAssertions):
    def test_invalid_utf8_is_a_parse_diagnostic(self) -> None:
        diagnostics = self.assert_policy_diagnostic(b"version = 1\n\xff", CFG_PARSE, "$")
        self.assertEqual(diagnostics[0].details, (("byte_offset", 12),))

    def test_malformed_and_duplicate_toml_are_parse_diagnostics(self) -> None:
        for data in (
            b"version = [\n",
            b"version = 1\nversion = 1\n",
        ):
            with self.subTest(data=data):
                self.assert_policy_diagnostic(data, CFG_PARSE, "$")


class StrictShapeTests(ConfigurationAssertions):
    def test_unknown_keys_are_rejected_at_every_table_shape(self) -> None:
        text = replace_once(ROOT_POLICY_TEXT, "version = 1\n", "version = 1\nsurprise = true\n")
        text = replace_once(
            text,
            "follow_symlinks = false\n",
            "follow_symlinks = false\nrepository_typo = true\n",
        )
        text = replace_once(
            text,
            'reason = "Machine-generated dependency resolution data is not useful bootstrap context."\n',
            'reason = "Machine-generated dependency resolution data is not useful bootstrap context."\nrule_typo = true\n',
        )
        text = append_exception_record(
            text,
            '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false
record_typo = true''',
        )
        diagnostics = self.policy_diagnostics(text)
        pairs = {(item.code, item.field_path) for item in diagnostics}
        self.assertTrue(
            {
                (CFG_UNKNOWN_KEY, "surprise"),
                (CFG_UNKNOWN_KEY, "repository.repository_typo"),
                (CFG_UNKNOWN_KEY, "file_rule[0].rule_typo"),
                (CFG_UNKNOWN_KEY, "exceptions.record[0].record_typo"),
            }.issubset(pairs)
        )

    def test_unusual_unknown_keys_have_unambiguous_escaped_field_paths(self) -> None:
        text = replace_once(
            ROOT_POLICY_TEXT,
            "version = 1\n",
            'version = 1\n"zeta.key" = true\n"line\\u0085key" = true\n',
        )
        diagnostics = self.policy_diagnostics(text)
        fields = {item.field_path for item in diagnostics if item.code == CFG_UNKNOWN_KEY}
        self.assertEqual(fields, {'$["zeta.key"]', '$["line\\u0085key"]'})

    def test_required_top_level_values_and_tables_are_reported(self) -> None:
        cases = (
            (replace_once(ROOT_POLICY_TEXT, "version = 1\n\n", ""), "version"),
            (
                replace_once(
                    ROOT_POLICY_TEXT,
                    '[repository]\ninventory = "git-visible"\nencoding = "utf-8"\nfollow_symlinks = false\n\n',
                    "",
                ),
                "repository",
            ),
            (
                ROOT_POLICY_TEXT[
                    : ROOT_POLICY_TEXT.index("[[file_rule]]\n")
                ]
                + ROOT_POLICY_TEXT[ROOT_POLICY_TEXT.index("[[path_override]]\n") :],
                "file_rule",
            ),
        )
        for text, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(text, CFG_MISSING_KEY, field_path)

    def test_required_keys_are_reported_in_fixed_and_repeatable_records(self) -> None:
        cases = (
            (replace_once(ROOT_POLICY_TEXT, 'inventory = "git-visible"\n', ""), "repository.inventory"),
            (replace_once(ROOT_POLICY_TEXT, 'default_format = "text"\n', ""), "output.default_format"),
            (replace_once(ROOT_POLICY_TEXT, 'name = "lockfiles"\n', ""), "file_rule[0].name"),
            (
                replace_once(
                    ROOT_POLICY_TEXT,
                    'path = "AGENTS.md"\nwarn_bytes = 8192\n',
                    'path = "AGENTS.md"\n',
                ),
                "path_override[0].warn_bytes",
            ),
            (replace_once(ROOT_POLICY_TEXT, 'roots = ["docs/index.md"]\n', ""), "documentation.roots"),
            (
                replace_once(
                    ROOT_POLICY_TEXT,
                    'path = "AGENTS.md"\nrequired_targets = ["docs/index.md"]\n\n[[entrypoint]]',
                    'path = "AGENTS.md"\n\n[[entrypoint]]',
                ),
                "entrypoint[0].required_targets",
            ),
            (replace_once(ROOT_POLICY_TEXT, 'name = "bootstrap"\n', ""), "context_set[0].name"),
            (replace_once(ROOT_POLICY_TEXT, "compare_file_sizes = true\n", ""), "ratchet.compare_file_sizes"),
            (replace_once(ROOT_POLICY_TEXT, "require_reason = true\n", ""), "exceptions.require_reason"),
        )
        for text, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(text, CFG_MISSING_KEY, field_path)

    def test_exception_records_require_governance_metadata(self) -> None:
        text = append_exception_record(
            ROOT_POLICY_TEXT,
            '''path = "generated/schema.json"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01
scan = false''',
        )
        self.assert_policy_diagnostic(text, CFG_MISSING_KEY, "exceptions.record[0].owner")

    def test_fixed_table_type_is_strict(self) -> None:
        text = replace_once(
            ROOT_POLICY_TEXT,
            '[repository]\ninventory = "git-visible"\nencoding = "utf-8"\nfollow_symlinks = false',
            'repository = "git-visible"',
        )
        self.assert_policy_diagnostic(text, CFG_TYPE, "repository")

    def test_array_of_tables_type_is_strict(self) -> None:
        text = replace_once(ROOT_POLICY_TEXT, "version = 1\n", 'version = 1\nfile_rule = "authored"\n')
        text = text[: text.index("[[file_rule]]\n")] + text[text.index("[[path_override]]\n") :]
        self.assert_policy_diagnostic(text, CFG_TYPE, "file_rule")

    def test_scalar_and_array_types_are_strict(self) -> None:
        cases = (
            (replace_once(ROOT_POLICY_TEXT, "version = 1", "version = true"), "version"),
            (
                replace_once(ROOT_POLICY_TEXT, 'inventory = "git-visible"', "inventory = 1"),
                "repository.inventory",
            ),
            (
                replace_once(ROOT_POLICY_TEXT, "stable_sort = true", 'stable_sort = "true"'),
                "output.stable_sort",
            ),
            (
                replace_once(
                    ROOT_POLICY_TEXT,
                    'patterns = ["uv.lock", "**/uv.lock", "package-lock.json", "**/package-lock.json"]',
                    'patterns = "uv.lock"',
                ),
                "file_rule[0].patterns",
            ),
            (
                replace_once(ROOT_POLICY_TEXT, "hard_bytes = 25600", "hard_bytes = true"),
                "file_rule[1].hard_bytes",
            ),
            (
                replace_once(
                    ROOT_POLICY_TEXT,
                    'paths = ["AGENTS.md", "ARCHITECTURE.md", "docs/index.md"]',
                    'paths = ["AGENTS.md", 7]',
                ),
                "context_set[0].paths[1]",
            ),
        )
        for text, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(text, CFG_TYPE, field_path)

    def test_toml_datetime_is_not_accepted_as_a_local_date(self) -> None:
        text = append_exception_record(
            ROOT_POLICY_TEXT,
            '''path = "generated/schema.json"
owner = "tooling"
rationale = "Temporary compatibility boundary"
tracking_reference = "ADR-42"
created_on = 2026-08-01T00:00:00Z
scan = false''',
        )
        self.assert_policy_diagnostic(text, CFG_TYPE, "exceptions.record[0].created_on")

    def test_unsupported_version_and_enum_values_are_rejected(self) -> None:
        cases = (
            (replace_once(ROOT_POLICY_TEXT, "version = 1", "version = 2"), "version"),
            (
                replace_once(ROOT_POLICY_TEXT, 'inventory = "git-visible"', 'inventory = "filesystem"'),
                "repository.inventory",
            ),
            (
                replace_once(ROOT_POLICY_TEXT, 'encoding = "utf-8"', 'encoding = "utf-16"'),
                "repository.encoding",
            ),
            (
                replace_once(ROOT_POLICY_TEXT, 'kind = "generated"', 'kind = "binary"'),
                "file_rule[0].kind",
            ),
            (
                replace_once(ROOT_POLICY_TEXT, 'default_format = "text"', 'default_format = "json"'),
                "output.default_format",
            ),
        )
        for text, field_path in cases:
            with self.subTest(field_path=field_path):
                self.assert_policy_diagnostic(text, CFG_VALUE, field_path)


if __name__ == "__main__":
    unittest.main()
