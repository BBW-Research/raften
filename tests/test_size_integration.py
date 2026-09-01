from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from repo_context.config import starter_policy
from repo_context.diagnostics import (
    CONTEXT_HARD_BYTES,
    CONTEXT_MEMBER_MISSING,
    FILE_HARD_BYTES,
    FILE_WARN_BYTES,
)
from repo_context.inventory import (
    inventory_worktree,
    open_repository,
    read_worktree_bytes,
)
from repo_context.model import (
    ContentState,
    ContextSet,
    ExactSelector,
    FileKind,
    FileRule,
    IntentionalException,
    PathOverride,
)
from repo_context.sizes import (
    classification_counts,
    compile_size_policy,
    evaluate_sizes,
    explain_size_path,
    largest_governed_files,
)
from tests.support.repository import RepositoryFixture


class MixedRepositorySizeIntegrationTests(unittest.TestCase):
    def test_real_inventory_read_classification_budgets_context_and_audit_share_data(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("README.md", b"1234567")
            repository.write_bytes("generated/data.json", b"g" * 50)
            repository.write_bytes("LICENSE", b"legal")
            repository.commit("tracked files")
            repository.write_bytes("vendor/lib.txt", b"v" * 40)
            repository.write_bytes("fixtures/data.txt", b"f" * 11)
            repository.write_bytes("docs/guide.md", b"d" * 9)
            repository.write_bytes("binary.bin", b"\x00" * 100)

            policy = replace(
                starter_policy(),
                file_rules=(
                    FileRule("legal", ("LICENSE",), FileKind.LEGAL, True, 4, 30),
                    FileRule(
                        "generated",
                        ("generated/**",),
                        FileKind.GENERATED,
                        False,
                        None,
                        None,
                        "generated output",
                    ),
                    FileRule(
                        "vendored",
                        ("vendor/**",),
                        FileKind.VENDORED,
                        False,
                        None,
                        None,
                        "third-party source",
                    ),
                    FileRule("fixture", ("fixtures/**",), FileKind.FIXTURE, True, 5, 10),
                    FileRule("authored", ("**",), FileKind.AUTHORED, True, 8, 12),
                ),
                path_overrides=(
                    PathOverride(ExactSelector("README.md"), 5, 6),
                ),
                context_sets=(
                    ContextSet(
                        "bootstrap",
                        ("README.md", "missing.md"),
                        ("docs/*.md",),
                        13,
                        15,
                    ),
                ),
                exceptions=replace(
                    starter_policy().exceptions,
                    records=(
                        IntentionalException(
                            ExactSelector("fixtures/data.txt"),
                            "tests",
                            "fixture remains intentionally contiguous",
                            "issue-7",
                            date(2026, 8, 1),
                            None,
                            None,
                            15,
                            20,
                        ),
                    ),
                ),
            )
            compiled = compile_size_policy(policy)
            handle = open_repository(repository.root)
            snapshot = inventory_worktree(handle)
            calls: list[str] = []

            def read(entry):
                calls.append(entry.path)
                return read_worktree_bytes(handle, entry)

            evaluation = evaluate_sizes(
                compiled,
                snapshot.entries,
                read,
                evaluation_date=date(2026, 9, 1),
                retain_text_paths=frozenset({"docs/guide.md"}),
            )

        self.assertEqual(len(calls), len(set(calls)))
        self.assertNotIn("generated/data.json", calls)
        self.assertNotIn("vendor/lib.txt", calls)
        self.assertEqual(evaluation.documents[0].path, "docs/guide.md")
        files = {item.entry.path: item for item in evaluation.files}
        self.assertEqual(files["binary.bin"].content_state, ContentState.CONTAINS_NUL)
        self.assertEqual(files["generated/data.json"].content_state, ContentState.UNREAD)
        self.assertEqual(files["fixtures/data.txt"].policy.effective_hard_bytes, 20)
        self.assertEqual(files["README.md"].policy.ordinary_hard_bytes, 6)
        self.assertEqual(evaluation.contexts[0].total_bytes, 16)
        self.assertEqual(evaluation.contexts[0].missing_exact_paths, ("missing.md",))
        self.assertEqual(
            {item.code for item in evaluation.diagnostics},
            {
                CONTEXT_HARD_BYTES,
                CONTEXT_MEMBER_MISSING,
                FILE_HARD_BYTES,
                FILE_WARN_BYTES,
            },
        )
        self.assertEqual(
            tuple(item.entry.path for item in largest_governed_files(evaluation)),
            (
                "binary.bin",
                "generated/data.json",
                "vendor/lib.txt",
                "fixtures/data.txt",
                "docs/guide.md",
                "README.md",
                "LICENSE",
            ),
        )
        self.assertEqual(
            classification_counts(evaluation),
            (
                (FileKind.AUTHORED, 3),
                (FileKind.FIXTURE, 1),
                (FileKind.GENERATED, 1),
                (FileKind.LEGAL, 1),
                (FileKind.VENDORED, 1),
            ),
        )
        readme = explain_size_path(compiled, "README.md", date(2026, 9, 1), evaluation)
        fixture = explain_size_path(
            compiled,
            "fixtures/data.txt",
            date(2026, 9, 1),
            evaluation,
        )
        self.assertEqual(readme.policy.override_match.override_index, 0)
        self.assertEqual(readme.context_sets, ("bootstrap",))
        self.assertEqual(fixture.policy.exception_match.exception_index, 0)


if __name__ == "__main__":
    unittest.main()
