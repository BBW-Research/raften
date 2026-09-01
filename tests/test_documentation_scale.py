from __future__ import annotations

import unittest
from dataclasses import replace

from repo_context.config import starter_policy
from repo_context.docs import compile_documentation_policy, documentation_text_paths, evaluate_documentation
from repo_context.model import DocumentationSettings, InventoryEntry, InventorySource, TextDocument, WorktreeKind


def regular(path: str, size: int = 1) -> InventoryEntry:
    return InventoryEntry(
        path,
        InventorySource.TRACKED,
        WorktreeKind.REGULAR,
        size_bytes=size,
    )


class DocumentationScaleTests(unittest.TestCase):
    def test_text_selection_is_deterministic_for_one_hundred_thousand_paths(self) -> None:
        entries = tuple(regular(f"src/generated/file-{index:06d}.py") for index in range(100_000)) + (
            regular("docs/index.md"),
            regular("reference.md"),
        )

        retained = documentation_text_paths(
            compile_documentation_policy(starter_policy()),
            tuple(reversed(entries)),
        )

        self.assertEqual(retained, frozenset({"docs/index.md", "reference.md"}))

    def test_deep_hierarchy_uses_iterative_ancestor_and_reachability_models(self) -> None:
        nested_directory = "docs/" + "/".join(f"level-{index}" for index in range(1_000))
        topic_path = f"{nested_directory}/topic.md"
        root_text = f"[Deep topic](../{topic_path})\n"
        topic_text = "# Topic\n"
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
        entries = (
            regular("docs/index.md", len(root_text.encode("utf-8"))),
            regular(topic_path, len(topic_text.encode("utf-8"))),
        )

        result = evaluate_documentation(
            compile_documentation_policy(policy),
            entries,
            (
                TextDocument("docs/index.md", root_text, len(root_text.encode("utf-8"))),
                TextDocument(topic_path, topic_text, len(topic_text.encode("utf-8"))),
            ),
        )

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(len(result.directories), 1_001)
        self.assertEqual(result.unreachable_paths, ())


if __name__ == "__main__":
    unittest.main()
