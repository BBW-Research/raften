from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.support.repository import seed_policy
from tests.support.seed import SEED


class SeedPolicyParsingTests(unittest.TestCase):
    def assert_policy_error(self, policy: object, message: str) -> None:
        with self.assertRaisesRegex(SEED.PolicyError, message):
            SEED.load_policy_bytes(json.dumps(policy).encode("utf-8"), "fixture.json")

    def test_valid_policy_bytes_and_file_are_loaded(self) -> None:
        policy = seed_policy()
        encoded = json.dumps(policy).encode("utf-8")
        self.assertEqual(SEED.load_policy_bytes(encoded, "memory"), policy)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_bytes(encoded)
            self.assertEqual(SEED.load_policy(path), policy)

    def test_invalid_encoding_json_and_top_level_shape_are_rejected(self) -> None:
        for data in (b"\xff", b"{"):
            with self.subTest(data=data):
                with self.assertRaisesRegex(SEED.PolicyError, "invalid policy JSON"):
                    SEED.load_policy_bytes(data, "fixture.json")
        self.assert_policy_error([], "must be an object")

    def test_key_set_and_version_are_strict(self) -> None:
        missing = seed_policy()
        del missing["max_text_bytes"]
        self.assert_policy_error(missing, "missing=\\['max_text_bytes'\\]")

        unknown = seed_policy(extra=True)
        self.assert_policy_error(unknown, "unknown=\\['extra'\\]")

        unsupported = seed_policy(policy_version=2)
        self.assert_policy_error(unsupported, "unsupported policy_version")

    def test_global_limits_must_be_positive_integers(self) -> None:
        for key in ("max_text_bytes", "index_max_bytes"):
            for value in (0, -1, "10", 1.5, None):
                with self.subTest(key=key, value=value):
                    policy = seed_policy()
                    policy[key] = value
                    self.assert_policy_error(policy, f"{key}.*positive integer")

    def test_path_limit_maps_validate_shape_paths_and_values(self) -> None:
        for key in ("entrypoint_limits", "legacy_oversize"):
            with self.subTest(key=key, case="shape"):
                policy = seed_policy()
                policy[key] = []
                self.assert_policy_error(policy, f"{key}.*must be an object")
            for raw_path in ("/README.md", "docs/../README.md", "docs//index.md"):
                with self.subTest(key=key, path=raw_path):
                    policy = seed_policy()
                    policy[key] = {raw_path: 10}
                    self.assert_policy_error(policy, "unsafe or non-canonical")
            for value in (0, -1, "10", None):
                with self.subTest(key=key, value=value):
                    policy = seed_policy()
                    policy[key] = {"README.md": value}
                    self.assert_policy_error(policy, "invalid byte limit")

    def test_string_list_fields_validate_shape_and_members(self) -> None:
        keys = (
            "documentation_roots",
            "documentation_excluded_globs",
            "text_excluded_globs",
        )
        for key in keys:
            for value in ("docs", [""], [1], ["docs", None]):
                with self.subTest(key=key, value=value):
                    policy = seed_policy()
                    policy[key] = value
                    self.assert_policy_error(policy, f"{key}.*string list")

    def test_documentation_roots_must_be_canonical(self) -> None:
        policy = seed_policy(documentation_roots=["docs/../reference"])
        self.assert_policy_error(policy, "unsafe or non-canonical")

    def test_required_entrypoint_links_validate_shape_and_paths(self) -> None:
        policy = seed_policy(required_entrypoint_links=[])
        self.assert_policy_error(policy, "required_entrypoint_links.*must be an object")

        invalid_cases: list[dict[str, Any]] = [
            {"docs/../README.md": []},
            {"README.md": "docs/index.md"},
            {"README.md": [1]},
            {"README.md": ["docs/../index.md"]},
        ]
        for required_links in invalid_cases:
            with self.subTest(required_links=required_links):
                policy = seed_policy(required_entrypoint_links=required_links)
                self.assert_policy_error(policy, "invalid required links|unsafe or non-canonical")

    def test_seed_accepts_boolean_numbers_empty_lists_and_duplicate_json_keys(self) -> None:
        policy = seed_policy(
            policy_version=True,
            max_text_bytes=True,
            index_max_bytes=True,
        )
        self.assertEqual(SEED.load_policy_bytes(json.dumps(policy).encode(), "memory"), policy)

        duplicate = json.dumps(seed_policy()).removesuffix("}")
        duplicate += ', "max_text_bytes": 7}'
        self.assertEqual(SEED.load_policy_bytes(duplicate.encode(), "memory")["max_text_bytes"], 7)

    def test_seed_does_not_validate_glob_canonicality(self) -> None:
        policy = seed_policy(
            documentation_excluded_globs=["../outside/**"],
            text_excluded_globs=["docs\\*.md"],
        )
        parsed = SEED.load_policy_bytes(json.dumps(policy).encode(), "memory")
        self.assertEqual(parsed["documentation_excluded_globs"], ["../outside/**"])


class SeedCanonicalPathTests(unittest.TestCase):
    def test_canonical_relative_paths_are_returned_unchanged(self) -> None:
        for value in ("README.md", "docs/index.md", "docs/指南.md"):
            with self.subTest(value=value):
                self.assertEqual(SEED.canonical_rel(value), value)

    def test_noncanonical_or_traversing_paths_are_rejected(self) -> None:
        values = (
            "",
            "/README.md",
            "./README.md",
            "docs//index.md",
            "docs/",
            "../README.md",
            "docs/../README.md",
            "docs/reference/../../README.md",
        )
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(SEED.PolicyError):
                    SEED.canonical_rel(value)

    def test_seed_accepts_dot_backslash_and_nul_paths(self) -> None:
        for value in (".", "docs\\index.md", "docs/nu\0l.md"):
            with self.subTest(value=value):
                self.assertEqual(SEED.canonical_rel(value), value)


class SeedMatcherTests(unittest.TestCase):
    def test_fnmatchcase_features_are_inherited(self) -> None:
        cases = (
            ("README.md", ["*.md"], True),
            ("README.MD", ["*.md"], False),
            ("docs/a.md", ["docs/?.md"], True),
            ("docs/a.md", ["docs/[ab].md"], True),
            ("docs/c.md", ["docs/[ab].md"], False),
            ("src/main.py", ["*.md", "src/*.py"], True),
            ("src/main.py", [], False),
        )
        for path, patterns, expected in cases:
            with self.subTest(path=path, patterns=patterns):
                self.assertEqual(SEED.matches_any(path, patterns), expected)

    def test_seed_star_and_question_mark_cross_path_separators(self) -> None:
        self.assertTrue(SEED.matches_any("docs/deep/guide.md", ["docs/*.md"]))
        self.assertTrue(SEED.matches_any("docs//.md", ["docs/?.md"]))
        self.assertTrue(SEED.matches_any("docs/guide.md", ["*.md"]))


if __name__ == "__main__":
    unittest.main()
