from __future__ import annotations

import unittest

from tests.support.repository import RepositoryFixture, seed_policy
from tests.support.seed import SEED


class SeedMarkdownTargetTests(unittest.TestCase):
    def test_inline_targets_are_normalized_relative_to_source(self) -> None:
        with RepositoryFixture(initialize_git=False) as repository:
            repository.path("docs/guide").mkdir(parents=True)
            repository.write_text("docs/guide/index.md", "# Guide\n")
            text = "\n".join(
                (
                    "[file](reference.md)",
                    "[angle](<guide page.md>)",
                    "[title](titled.md \"A title\")",
                    "[query](search.md?mode=full#results)",
                    "[encoded](space%20name.md)",
                    "[directory](guide/)",
                    "[duplicate](reference.md)",
                )
            )
            targets = SEED.markdown_targets("docs/index.md", text, repository.root)
        self.assertEqual(
            targets,
            {
                "docs/reference.md",
                "docs/guide page.md",
                "docs/titled.md",
                "docs/search.md",
                "docs/space name.md",
                "docs/guide/index.md",
            },
        )

    def test_external_absolute_fragment_image_and_escape_targets_are_ignored(self) -> None:
        text = "\n".join(
            (
                "[absolute](/README.md)",
                "[https](https://example.com)",
                "[mail](mailto:team@example.com)",
                "[escape](../../outside.md)",
                "[fragment](#heading)",
                "![image](image.png)",
            )
        )
        with RepositoryFixture(initialize_git=False) as repository:
            targets = SEED.markdown_targets("docs/index.md", text, repository.root)
        self.assertEqual(targets, set())

    def test_nonexistent_local_target_is_still_returned(self) -> None:
        with RepositoryFixture(initialize_git=False) as repository:
            targets = SEED.markdown_targets(
                "docs/index.md",
                "[missing](nested/missing.md)",
                repository.root,
            )
        self.assertEqual(targets, {"docs/nested/missing.md"})

    def test_seed_misses_reference_links_and_reads_links_inside_code_and_comments(self) -> None:
        text = """`[inline](inline.md)`

```markdown
[fenced](fenced.md)
```

<!-- [comment](comment.md) -->
[guide][guide-ref]
[guide-ref]: reference.md
"""
        with RepositoryFixture(initialize_git=False) as repository:
            targets = SEED.markdown_targets("docs/index.md", text, repository.root)
        self.assertEqual(
            targets,
            {"docs/inline.md", "docs/fenced.md", "docs/comment.md"},
        )


class SeedDocumentationCheckTests(unittest.TestCase):
    def test_seed_does_not_validate_missing_local_targets_or_fragments(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text(
                "docs/index.md",
                "[Missing](missing.md#unknown-heading)\n",
            )
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/index.md"],
                policy,
            )
        self.assertEqual((errors, count), ([], 1))

    def test_discovery_is_limited_to_lowercase_markdown_under_roots(self) -> None:
        policy = seed_policy(
            documentation_roots=["docs"],
            documentation_excluded_globs=["docs/excluded.md"],
        )
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "[Guide](guide.md)\n")
            repository.write_text("docs/guide.md", "# Guide\n")
            repository.write_text("docs/excluded.md", "# Excluded\n")
            repository.write_text("docs/upper.MD", "# Upper\n")
            repository.write_text("reference/outside.md", "# Outside\n")
            errors, count = SEED.check_docs(
                repository.root,
                [
                    "docs/index.md",
                    "docs/guide.md",
                    "docs/excluded.md",
                    "docs/upper.MD",
                    "docs/missing.md",
                    "reference/outside.md",
                ],
                policy,
            )
        self.assertEqual(errors, [])
        self.assertEqual(count, 2)

    def test_authored_document_symlink_is_rejected_and_not_counted(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("target.md", "# Target\n")
            try:
                repository.symlink("docs/link.md", "../target.md")
            except OSError as exc:
                self.skipTest(f"symlinks unavailable: {exc}")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/index.md", "docs/link.md"],
                policy,
            )
        self.assertEqual(errors, ["docs/link.md: authored documentation may not be a symlink"])
        self.assertEqual(count, 1)

    def test_every_discovered_document_parent_requires_an_index(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/guide.md", "# Guide\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/guide.md"],
                policy,
            )
        self.assertEqual(
            errors,
            [
                "docs: missing required index.md",
                "docs/index.md: does not directly link sibling document docs/guide.md",
            ],
        )
        self.assertEqual(count, 1)

    def test_index_must_directly_link_each_sibling_in_sorted_order(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("docs/zeta.md", "# Zeta\n")
            repository.write_text("docs/alpha.md", "# Alpha\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/zeta.md", "docs/index.md", "docs/alpha.md"],
                policy,
            )
        self.assertEqual(count, 3)
        self.assertEqual(
            errors,
            [
                "docs/index.md: does not directly link sibling document docs/alpha.md",
                "docs/index.md: does not directly link sibling document docs/zeta.md",
            ],
        )

    def test_direct_sibling_links_satisfy_requirement(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text(
                "docs/index.md",
                "[Alpha](alpha.md)\n[Zeta](zeta.md)\n",
            )
            repository.write_text("docs/alpha.md", "# Alpha\n")
            repository.write_text("docs/zeta.md", "# Zeta\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/index.md", "docs/alpha.md", "docs/zeta.md"],
                policy,
            )
        self.assertEqual((errors, count), ([], 3))

    def test_link_from_non_index_document_does_not_satisfy_sibling_requirement(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "[Router](router.md)\n")
            repository.write_text("docs/router.md", "[Guide](guide.md)\n")
            repository.write_text("docs/guide.md", "# Guide\n")
            errors, _count = SEED.check_docs(
                repository.root,
                ["docs/index.md", "docs/router.md", "docs/guide.md"],
                policy,
            )
        self.assertIn(
            "docs/index.md: does not directly link sibling document docs/guide.md",
            errors,
        )

    def test_index_must_link_immediate_child_indexes_in_sorted_order(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("docs/zeta/index.md", "# Zeta\n")
            repository.write_text("docs/alpha/index.md", "# Alpha\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/zeta/index.md", "docs/index.md", "docs/alpha/index.md"],
                policy,
            )
        self.assertEqual(count, 3)
        self.assertEqual(
            errors,
            [
                "docs/index.md: does not directly link child index docs/alpha/index.md",
                "docs/index.md: does not directly link child index docs/zeta/index.md",
            ],
        )

    def test_directory_links_satisfy_child_index_requirement(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "[Alpha](alpha/)\n")
            repository.write_text("docs/alpha/index.md", "# Alpha\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/index.md", "docs/alpha/index.md"],
                policy,
            )
        self.assertEqual((errors, count), ([], 2))

    def test_only_immediate_child_index_is_required_at_each_level(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "[A](a/)\n")
            repository.write_text("docs/a/index.md", "[B](b/)\n")
            repository.write_text("docs/a/b/index.md", "# B\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/index.md", "docs/a/index.md", "docs/a/b/index.md"],
                policy,
            )
        self.assertEqual((errors, count), ([], 3))

    def test_seed_omits_intermediate_directory_without_direct_documents(self) -> None:
        policy = seed_policy(documentation_roots=["docs"])
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("docs/a/b/index.md", "[Topic](topic.md)\n")
            repository.write_text("docs/a/b/topic.md", "# Topic\n")
            errors, count = SEED.check_docs(
                repository.root,
                ["docs/index.md", "docs/a/b/index.md", "docs/a/b/topic.md"],
                policy,
            )
        self.assertEqual((errors, count), ([], 3))


class SeedEntrypointLinkTests(unittest.TestCase):
    def test_missing_entrypoint_is_reported(self) -> None:
        policy = seed_policy(required_entrypoint_links={"README.md": ["docs/index.md"]})
        with RepositoryFixture(initialize_git=False) as repository:
            errors, count = SEED.check_docs(repository.root, [], policy)
        self.assertEqual(count, 0)
        self.assertEqual(errors, ["README.md: required entrypoint is missing"])

    def test_missing_required_targets_follow_policy_declaration_order(self) -> None:
        policy = seed_policy(
            required_entrypoint_links={
                "README.md": ["docs/zeta.md", "docs/alpha.md"],
                "AGENTS.md": ["docs/index.md"],
            }
        )
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("README.md", "# Readme\n")
            repository.write_text("AGENTS.md", "# Agents\n")
            errors, _count = SEED.check_docs(repository.root, [], policy)
        self.assertEqual(
            errors,
            [
                "README.md: missing required link to docs/zeta.md",
                "README.md: missing required link to docs/alpha.md",
                "AGENTS.md: missing required link to docs/index.md",
            ],
        )

    def test_normalized_file_and_directory_links_satisfy_entrypoint_targets(self) -> None:
        policy = seed_policy(
            required_entrypoint_links={
                "README.md": ["docs/index.md", "docs/guide.md"],
            }
        )
        with RepositoryFixture(initialize_git=False) as repository:
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("README.md", "[Docs](docs/)\n[Guide](docs/guide.md#start)\n")
            errors, count = SEED.check_docs(repository.root, [], policy)
        self.assertEqual((errors, count), ([], 0))


if __name__ == "__main__":
    unittest.main()
