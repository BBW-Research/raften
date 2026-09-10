from __future__ import annotations

import unittest

from raften.matcher import (
    narrow_pattern_error,
    path_validation_error,
    pattern_has_wildcards,
    pattern_specificity,
    pattern_validation_error,
    patterns_provably_disjoint,
)


class ExactPathSyntaxTests(unittest.TestCase):
    def test_canonical_repository_relative_paths_are_valid(self) -> None:
        for path in ("AGENTS.md", ".github/workflows/check.yml", "docs/中文/index.md"):
            with self.subTest(path=path):
                self.assertIsNone(path_validation_error(path))

    def test_unsafe_or_noncanonical_paths_are_rejected(self) -> None:
        paths = (
            "",
            "/absolute.md",
            "C:/absolute.md",
            "docs/C:relative.md",
            "docs/C:/absolute.md",
            "docs\\index.md",
            "docs//index.md",
            "docs/",
            "./docs.md",
            "docs/../README.md",
            "docs/*.md",
            "docs/\x00index.md",
            "docs/\x7findex.md",
            "docs/\u0085index.md",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNotNone(path_validation_error(path))


class PatternSyntaxTests(unittest.TestCase):
    def test_supported_pattern_syntax_is_valid(self) -> None:
        for pattern in (
            "**",
            "docs/**/*.md",
            "source/file?.py",
            "fixtures/[ab].txt",
            "fixtures/[!a-z].txt",
            "docs/[**].md",
            ".github/**/*.yml",
        ):
            with self.subTest(pattern=pattern):
                self.assertIsNone(pattern_validation_error(pattern))

    def test_malformed_patterns_are_rejected(self) -> None:
        patterns = (
            "",
            "/**/*.md",
            "docs/C:*.md",
            "docs/C:/**/*.md",
            "docs\\*.md",
            "docs//*.md",
            "docs/***.md",
            "docs/a**/file.md",
            "docs/[].md",
            "docs/[!].md",
            "docs/[[a].md",
            "docs/[a.md",
            "docs/a].md",
            "docs/[z-a].md",
            "docs/[a--].md",
            "docs/[a-b-c].md",
            "docs/../*.md",
            "docs/\u0085*.md",
        )
        for pattern in patterns:
            with self.subTest(pattern=pattern):
                self.assertIsNotNone(pattern_validation_error(pattern))

    def test_wildcard_detection_covers_each_supported_form(self) -> None:
        self.assertFalse(pattern_has_wildcards("docs/index.md"))
        for pattern in ("*.md", "file?.md", "[ab].md", "**/index.md"):
            with self.subTest(pattern=pattern):
                self.assertTrue(pattern_has_wildcards(pattern))

    def test_specificity_is_structural_and_deterministic(self) -> None:
        self.assertEqual(pattern_specificity("docs/**/index.md"), (2, 12, 3, -1, 0))
        self.assertGreater(
            pattern_specificity("docs/api/*.md"),
            pattern_specificity("docs/**/*.md"),
        )
        self.assertEqual(
            pattern_specificity("source/*.txt"),
            pattern_specificity("vendor/*.txt"),
        )

    def test_static_disjointness_requires_a_differing_literal_component(self) -> None:
        self.assertTrue(patterns_provably_disjoint("source/*.txt", "vendor/*.txt"))
        self.assertTrue(patterns_provably_disjoint("docs/*/one.md", "docs/*/two.md"))
        self.assertTrue(patterns_provably_disjoint("docs/**/one.md", "docs/**/two.md"))
        self.assertTrue(patterns_provably_disjoint("docs/api", "docs/api/v1"))
        self.assertFalse(patterns_provably_disjoint("docs/*.md", "docs/?.md"))
        self.assertFalse(patterns_provably_disjoint("docs/**/index.md", "docs/*/index.md"))
        self.assertFalse(patterns_provably_disjoint("**/a/**/x", "**/b/**/x"))

    def test_narrow_patterns_need_a_fixed_prefix_and_literal_filename(self) -> None:
        self.assertIsNone(narrow_pattern_error("fixtures/**/*.golden"))
        for pattern in ("**", "*.golden", "fixtures/**", "fixtures/*"):
            with self.subTest(pattern=pattern):
                self.assertIsNotNone(narrow_pattern_error(pattern))


if __name__ == "__main__":
    unittest.main()
