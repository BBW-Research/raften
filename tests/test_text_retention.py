from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from repo_context.config import starter_policy
from repo_context.model import ContentState, FileKind, FileRule, InventoryEntry, InventorySource, WorktreeKind
from repo_context.sizes import compile_size_policy, evaluate_sizes


class ExplicitTextRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = replace(
            starter_policy(),
            file_rules=(
                FileRule(
                    "generated-docs",
                    ("docs/**",),
                    FileKind.GENERATED,
                    False,
                    None,
                    None,
                    "generated documentation",
                ),
                FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
            ),
            path_overrides=(),
            context_sets=(),
        )
        self.entry = InventoryEntry(
            "docs/generated.md",
            InventorySource.TRACKED,
            WorktreeKind.REGULAR,
            size_bytes=5,
        )

    def test_requested_unscanned_text_is_read_once_without_budget_diagnostics(self) -> None:
        calls: list[str] = []

        def read(entry: InventoryEntry) -> bytes:
            calls.append(entry.path)
            return b"# Doc"

        result = evaluate_sizes(
            compile_size_policy(self.policy),
            (self.entry,),
            read,
            evaluation_date=date(2026, 9, 1),
            retain_text_paths=frozenset({self.entry.path}),
        )

        self.assertEqual(calls, [self.entry.path])
        self.assertEqual(result.files[0].content_state, ContentState.PLAINTEXT)
        self.assertIsNone(result.files[0].limit_state)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.documents[0].text, "# Doc")

    def test_unrequested_unscanned_text_is_not_read(self) -> None:
        result = evaluate_sizes(
            compile_size_policy(self.policy),
            (self.entry,),
            lambda _entry: self.fail("unrequested content was read"),
            evaluation_date=date(2026, 9, 1),
        )

        self.assertEqual(result.files[0].content_state, ContentState.UNREAD)
        self.assertEqual(result.documents, ())

    def test_retained_nonplaintext_content_is_classified_without_a_document(self) -> None:
        result = evaluate_sizes(
            compile_size_policy(self.policy),
            (self.entry,),
            lambda _entry: b"bad\x00text",
            evaluation_date=date(2026, 9, 1),
            retain_text_paths=frozenset({self.entry.path}),
        )

        self.assertEqual(result.files[0].content_state, ContentState.CONTAINS_NUL)
        self.assertIsNone(result.files[0].limit_state)
        self.assertEqual(result.documents, ())


if __name__ == "__main__":
    unittest.main()
