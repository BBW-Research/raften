from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from repo_context.config import load_policy, starter_policy
from repo_context.diagnostics import DOC_AUTHORED_SYMLINK
from repo_context.docs import compile_documentation_policy, documentation_text_paths, evaluate_documentation
from repo_context.inventory import inventory_worktree, open_repository, read_worktree_bytes
from repo_context.model import DocumentationSettings, Entrypoint, FileKind, FileRule
from repo_context.sizes import compile_size_policy, evaluate_sizes
from tests.support.repository import RepositoryFixture, seed_policy
from tests.support.seed import ROOT, SEED


TODAY = date(2026, 9, 1)


class DocumentationPipelineIntegrationTests(unittest.TestCase):
    def test_inventory_budget_retention_and_graph_share_each_verified_read(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text(
                "docs/index.md",
                "[Guide](guide.md)\n[Generated](generated.md)\n[API](api/)\n",
            )
            repository.write_text("docs/guide.md", "# Guide\n")
            repository.write_text("docs/generated.md", "# Generated\n")
            repository.write_text("docs/api/index.md", "[Topic](topic.md)\n")
            repository.write_text("docs/api/topic.md", "# Topic\n")
            repository.write_text("README.md", "[Docs](docs/)\n")
            repository.ignore("docs/ignored.md")
            repository.write_text("docs/ignored.md", "# Ignored\n")
            repository.commit("documentation")

            policy = replace(
                starter_policy(),
                file_rules=(
                    FileRule(
                        "generated-doc",
                        ("docs/generated.md",),
                        FileKind.GENERATED,
                        False,
                        None,
                        None,
                        "generated reference",
                    ),
                    FileRule("authored", ("**",), FileKind.AUTHORED, True, 10_000, 20_000),
                ),
                path_overrides=(),
                context_sets=(),
                entrypoints=(Entrypoint("README.md", ("docs/index.md",)),),
            )
            handle = open_repository(repository.root)
            snapshot = inventory_worktree(handle)
            compiled_docs = compile_documentation_policy(policy)
            retained = documentation_text_paths(compiled_docs, snapshot.entries)
            calls: list[str] = []

            def read(entry):
                calls.append(entry.path)
                return read_worktree_bytes(handle, entry)

            sizes = evaluate_sizes(
                compile_size_policy(policy),
                snapshot.entries,
                read,
                evaluation_date=TODAY,
                retain_text_paths=retained,
            )
            graph = evaluate_documentation(
                compiled_docs,
                snapshot.entries,
                sizes.documents,
                file_assessments=sizes.files,
            )

        self.assertIn("docs/generated.md", retained)
        self.assertNotIn("docs/ignored.md", retained)
        self.assertEqual(len(calls), len(set(calls)))
        self.assertTrue(set(retained).issubset(calls))
        self.assertEqual(graph.diagnostics, ())

    def test_authored_symlink_is_never_opened_by_the_shared_reader(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("docs/index.md", "[Escape](escape.md)\n")
            repository.write_text("outside.md", "# Outside\n")
            try:
                repository.symlink("docs/escape.md", "../../outside.md")
            except OSError as error:
                self.skipTest(f"symlinks unavailable: {error}")
            repository.commit("symlink documentation")

            policy = replace(
                starter_policy(),
                path_overrides=(),
                context_sets=(),
                entrypoints=(),
            )
            handle = open_repository(repository.root)
            snapshot = inventory_worktree(handle)
            compiled_docs = compile_documentation_policy(policy)
            retained = documentation_text_paths(compiled_docs, snapshot.entries)
            calls: list[str] = []

            def read(entry):
                calls.append(entry.path)
                return read_worktree_bytes(handle, entry)

            sizes = evaluate_sizes(
                compile_size_policy(policy),
                snapshot.entries,
                read,
                evaluation_date=TODAY,
                retain_text_paths=retained,
            )
            graph = evaluate_documentation(
                compiled_docs,
                snapshot.entries,
                sizes.documents,
                file_assessments=sizes.files,
            )

        self.assertNotIn("docs/escape.md", calls)
        self.assertEqual(
            tuple(item.code for item in graph.diagnostics),
            (DOC_AUTHORED_SYMLINK,),
        )

    def test_repository_documentation_passes_the_phase_four_engine(self) -> None:
        policy = load_policy(ROOT / "repo-context.toml")
        handle = open_repository(ROOT)
        snapshot = inventory_worktree(handle)
        compiled_docs = compile_documentation_policy(policy)
        retained = documentation_text_paths(compiled_docs, snapshot.entries)
        sizes = evaluate_sizes(
            compile_size_policy(policy),
            snapshot.entries,
            lambda entry: read_worktree_bytes(handle, entry),
            evaluation_date=TODAY,
            retain_text_paths=retained,
        )
        graph = evaluate_documentation(
            compiled_docs,
            snapshot.entries,
            sizes.documents,
            file_assessments=sizes.files,
        )

        self.assertEqual(graph.diagnostics, ())
        self.assertIn("docs/specs/markdown-graph-v1.md", graph.governed_paths)


class SourceDifferenceIntegrationTests(unittest.TestCase):
    def test_reference_links_count_while_code_and_comment_links_do_not(self) -> None:
        policy = replace(
            starter_policy(),
            documentation=DocumentationSettings(
                ("docs/index.md",),
                (),
                False,
                False,
                False,
                True,
                True,
                True,
                False,
            ),
            entrypoints=(),
        )
        with RepositoryFixture() as repository:
            repository.write_text(
                "docs/index.md",
                """`[Code](missing-code.md)`
<!-- [Comment](missing-comment.md) -->
[Guide][guide]

[guide]: guide.md
""",
            )
            repository.write_text("docs/guide.md", "# Guide\n")
            repository.commit("reference link")
            handle = open_repository(repository.root)
            snapshot = inventory_worktree(handle)
            compiled_docs = compile_documentation_policy(policy)
            retained = documentation_text_paths(compiled_docs, snapshot.entries)
            sizes = evaluate_sizes(
                compile_size_policy(policy),
                snapshot.entries,
                lambda entry: read_worktree_bytes(handle, entry),
                evaluation_date=TODAY,
                retain_text_paths=retained,
            )
            graph = evaluate_documentation(compiled_docs, snapshot.entries, sizes.documents)

        self.assertEqual(graph.diagnostics, ())
        self.assertEqual(
            tuple((edge.source_path, edge.target_path) for edge in graph.edges),
            (("docs/index.md", "docs/guide.md"),),
        )

    def test_intermediate_directory_gap_passes_seed_but_fails_target_hierarchy(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("docs/a/b/index.md", "[Topic](topic.md)\n")
            repository.write_text("docs/a/b/topic.md", "# Topic\n")
            repository.commit("deep documentation")
            seed_errors, _count = SEED.check_docs(
                repository.root,
                ("docs/index.md", "docs/a/b/index.md", "docs/a/b/topic.md"),
                seed_policy(documentation_roots=["docs"]),
            )
            policy = replace(starter_policy(), entrypoints=(), context_sets=())
            handle = open_repository(repository.root)
            snapshot = inventory_worktree(handle)
            compiled_docs = compile_documentation_policy(policy)
            retained = documentation_text_paths(compiled_docs, snapshot.entries)
            sizes = evaluate_sizes(
                compile_size_policy(policy),
                snapshot.entries,
                lambda entry: read_worktree_bytes(handle, entry),
                evaluation_date=TODAY,
                retain_text_paths=retained,
            )
            graph = evaluate_documentation(compiled_docs, snapshot.entries, sizes.documents)

        self.assertEqual(seed_errors, [])
        self.assertEqual(
            {item.code for item in graph.diagnostics},
            {"DOC003", "DOC005", "DOC011"},
        )

    def test_missing_target_and_fragment_are_target_only_failures(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("docs/index.md", "[Missing](missing.md#unknown)\n")
            repository.commit("broken documentation")
            seed_errors, _count = SEED.check_docs(
                repository.root,
                ("docs/index.md",),
                seed_policy(documentation_roots=["docs"]),
            )
            policy = replace(starter_policy(), entrypoints=(), context_sets=())
            handle = open_repository(repository.root)
            snapshot = inventory_worktree(handle)
            compiled_docs = compile_documentation_policy(policy)
            retained = documentation_text_paths(compiled_docs, snapshot.entries)
            sizes = evaluate_sizes(
                compile_size_policy(policy),
                snapshot.entries,
                lambda entry: read_worktree_bytes(handle, entry),
                evaluation_date=TODAY,
                retain_text_paths=retained,
            )
            graph = evaluate_documentation(compiled_docs, snapshot.entries, sizes.documents)

        self.assertEqual(seed_errors, [])
        self.assertEqual(tuple(item.code for item in graph.diagnostics), ("DOC009",))


if __name__ == "__main__":
    unittest.main()
