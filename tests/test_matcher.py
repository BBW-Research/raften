from __future__ import annotations

import unittest
from pathlib import PureWindowsPath

from repo_context.matcher import (
    PathFlavor,
    PatternSyntaxError,
    candidate_path_validation_error,
    compile_pattern,
    match_path,
    matches_any,
    normalize_platform_path,
)


class RepositoryGlobTests(unittest.TestCase):
    def test_patterns_match_the_complete_repository_path(self) -> None:
        self.assertTrue(match_path("*.py", "module.py"))
        self.assertFalse(match_path("*.py", "src/module.py"))
        self.assertTrue(match_path("**/*.py", "module.py"))
        self.assertTrue(match_path("**/*.py", "src/module.py"))
        self.assertTrue(match_path("**/*.py", "src/pkg/module.py"))
        self.assertFalse(match_path("src/*.py", "src/pkg/module.py"))
        self.assertFalse(match_path("index.md", "docs/index.md"))

    def test_only_a_complete_double_star_component_crosses_separators(self) -> None:
        self.assertTrue(match_path("docs/*.md", "docs/index.md"))
        self.assertFalse(match_path("docs/*.md", "docs/api/index.md"))
        self.assertTrue(match_path("docs/?.md", "docs/a.md"))
        self.assertFalse(match_path("docs/?.md", "docs/a/b.md"))
        self.assertTrue(match_path("docs/**/*.md", "docs/api/index.md"))

    def test_double_star_consumes_zero_one_or_many_components(self) -> None:
        cases = (
            ("**", "README.md"),
            ("**", "docs/api/index.md"),
            ("docs/**", "docs"),
            ("docs/**", "docs/index.md"),
            ("docs/**", "docs/api/index.md"),
            ("docs/**/index.md", "docs/index.md"),
            ("docs/**/index.md", "docs/api/index.md"),
            ("docs/**/index.md", "docs/api/v1/index.md"),
            ("**/**/index.md", "index.md"),
            ("**/**/index.md", "docs/api/index.md"),
        )
        for pattern, path in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertTrue(match_path(pattern, path))

    def test_star_and_question_mark_have_component_local_cardinality(self) -> None:
        self.assertTrue(match_path("file*.txt", "file.txt"))
        self.assertTrue(match_path("file*.txt", "file-long.txt"))
        self.assertFalse(match_path("file?.txt", "file.txt"))
        self.assertTrue(match_path("file?.txt", "fileA.txt"))
        self.assertTrue(match_path("file?.txt", "file中.txt"))
        self.assertTrue(match_path("file?.txt", "file🙂.txt"))
        self.assertFalse(match_path("file?.txt", "fileAB.txt"))

    def test_character_classes_use_the_documented_subset(self) -> None:
        cases = (
            ("[abc].txt", "a.txt", True),
            ("[abc].txt", "d.txt", False),
            ("[a-z].txt", "q.txt", True),
            ("[a-z].txt", "Q.txt", False),
            ("[!a-z].txt", "Q.txt", True),
            ("[!a-z].txt", "q.txt", False),
            ("[-a].txt", "-.txt", True),
            ("[a-].txt", "-.txt", True),
            ("[**].txt", "*.txt", True),
            ("[a!].txt", "!.txt", True),
            ("[一-鿿].txt", "中.txt", True),
            ("[^a].txt", "^.txt", True),
            ("[^a].txt", "b.txt", False),
        )
        for pattern, path, expected in cases:
            with self.subTest(pattern=pattern, path=path):
                self.assertEqual(match_path(pattern, path), expected)

    def test_dotfiles_have_no_hidden_file_magic(self) -> None:
        self.assertTrue(match_path("*", ".env"))
        self.assertTrue(match_path("**/*.yml", ".github/workflows/check.yml"))
        self.assertTrue(match_path(".github/**/*.yml", ".github/check.yml"))

    def test_matching_is_case_sensitive_and_does_not_normalize_unicode(self) -> None:
        self.assertFalse(match_path("README.md", "readme.md"))
        self.assertTrue(match_path("中?.md", "中🙂.md"))
        self.assertTrue(match_path("?.md", "é.md"))
        self.assertFalse(match_path("?.md", "e\u0301.md"))
        self.assertFalse(match_path("é.md", "e\u0301.md"))

    def test_candidate_metacharacters_are_literal_path_data(self) -> None:
        for path in ("literal*.txt", "what?.txt", "class[a].txt", "slash\\name"):
            with self.subTest(path=path):
                self.assertIsNone(candidate_path_validation_error(path))
                self.assertTrue(match_path("**", path))
        self.assertTrue(match_path("literal[**].txt", "literal*.txt"))

    def test_invalid_candidate_paths_are_rejected(self) -> None:
        for path in (
            "",
            "/absolute",
            "C:/absolute",
            "dir/C:relative",
            "dir/C:/absolute",
            "a//b",
            "a/./b",
            "a/../b",
            "a/",
            "nul\x00name",
        ):
            with self.subTest(path=path):
                self.assertIsNotNone(candidate_path_validation_error(path))
                with self.assertRaises(ValueError):
                    match_path("**", path)

    def test_compile_rejects_every_malformed_pattern(self) -> None:
        patterns = (
            "",
            "/**/*.md",
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
                with self.assertRaises(PatternSyntaxError):
                    compile_pattern(pattern)

    def test_precompiled_patterns_and_matches_any_are_equivalent(self) -> None:
        pattern = compile_pattern("docs/**/*.md")
        self.assertEqual(
            match_path(pattern, "docs/api/index.md"),
            match_path(pattern.source, "docs/api/index.md"),
        )
        self.assertFalse(matches_any((), "README.md"))
        self.assertTrue(
            matches_any(
                (compile_pattern("src/**/*.py"), compile_pattern("docs/**")),
                "docs/index.md",
            )
        )

    def test_dynamic_programming_handles_adversarial_wildcards(self) -> None:
        component = "a" * 200
        pattern = "*a" * 200
        self.assertTrue(match_path(pattern, component))
        deep_path = "/".join(["part"] * 200 + ["target.md"])
        self.assertTrue(match_path("**/**/**/target.md", deep_path))


class PlatformPathNormalizationTests(unittest.TestCase):
    def test_posix_paths_preserve_literal_backslashes(self) -> None:
        self.assertEqual(
            normalize_platform_path("dir\\name", flavor=PathFlavor.POSIX),
            "dir\\name",
        )

    def test_windows_paths_become_canonical_posix_paths(self) -> None:
        self.assertEqual(
            normalize_platform_path(
                "docs\\api\\index.md",
                flavor=PathFlavor.WINDOWS,
            ),
            "docs/api/index.md",
        )

    def test_normalization_rejects_absolute_and_noncanonical_paths(self) -> None:
        cases = (
            ("/tmp/file", PathFlavor.POSIX),
            ("C:\\repo\\file", PathFlavor.WINDOWS),
            ("dir\\C:relative", PathFlavor.WINDOWS),
            ("dir\\C:\\absolute", PathFlavor.WINDOWS),
            ("\\\\server\\share", PathFlavor.WINDOWS),
            ("docs\\..\\README.md", PathFlavor.WINDOWS),
            ("docs\\\\index.md", PathFlavor.WINDOWS),
        )
        for value, flavor in cases:
            with self.subTest(value=value, flavor=flavor):
                with self.assertRaises(ValueError):
                    normalize_platform_path(value, flavor=flavor)

    def test_nested_drive_component_would_reset_a_different_windows_drive(self) -> None:
        root = PureWindowsPath("D:/repository")
        for path in ("dir/C:relative", "dir/C:/absolute"):
            with self.subTest(path=path):
                joined = root.joinpath(*path.split("/"))
                self.assertFalse(joined.is_relative_to(root))
                self.assertIsNotNone(candidate_path_validation_error(path))


if __name__ == "__main__":
    unittest.main()
