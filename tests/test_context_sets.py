from __future__ import annotations

import unittest

from repo_context.diagnostics import (
    CONTEXT_HARD_BYTES,
    CONTEXT_MEMBER_MISSING,
    CONTEXT_WARN_BYTES,
)
from repo_context.model import (
    ContextSet,
    FileKind,
    FileRule,
    InventoryEntry,
    InventorySource,
    LimitState,
    Severity,
    WorktreeKind,
)
from repo_context.sizes import compile_size_policy, evaluate_sizes
from tests.support.sizes import TODAY, policy_with, regular


class ContextSetTests(unittest.TestCase):
    def test_context_membership_is_deduplicated_and_missing_exact_states_are_reported(self) -> None:
        context = ContextSet(
            "bundle",
            ("ctx/a.txt", "absent.txt", "deleted.txt", "sparse.txt", "link.txt", "other.txt"),
            ("ctx/*.txt", "**/a.txt"),
            10,
            20,
        )
        entries = (
            regular("ctx/a.txt", 5),
            regular("ctx/b.txt", 7),
            InventoryEntry("deleted.txt", InventorySource.DELETED, WorktreeKind.MISSING),
            InventoryEntry("sparse.txt", InventorySource.TRACKED, WorktreeKind.MISSING),
            InventoryEntry("link.txt", InventorySource.TRACKED, WorktreeKind.SYMLINK),
            InventoryEntry("other.txt", InventorySource.UNTRACKED, WorktreeKind.OTHER),
        )
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(context_sets=(context,))),
            entries,
            lambda entry: b"x" * entry.size_bytes,
            evaluation_date=TODAY,
        )
        result = evaluation.contexts[0]
        self.assertEqual(tuple(item.path for item in result.members), tuple(sorted({
            "absent.txt",
            "ctx/a.txt",
            "ctx/b.txt",
            "deleted.txt",
            "link.txt",
            "other.txt",
            "sparse.txt",
        })))
        self.assertEqual(result.total_bytes, 12)
        self.assertEqual(result.limit_state, LimitState.WARNING)
        self.assertEqual(result.missing_exact_paths, (
            "absent.txt",
            "deleted.txt",
            "link.txt",
            "other.txt",
            "sparse.txt",
        ))
        codes = tuple(item.code for item in evaluation.diagnostics)
        self.assertEqual(codes.count(CONTEXT_MEMBER_MISSING), 5)
        self.assertEqual(codes.count(CONTEXT_WARN_BYTES), 1)
        missing_states = {
            item.location.path: dict(item.details)["state"]
            for item in evaluation.diagnostics
            if item.code == CONTEXT_MEMBER_MISSING
        }
        self.assertEqual(
            missing_states,
            {
                "absent.txt": "absent",
                "deleted.txt": "deleted",
                "link.txt": "symlink",
                "other.txt": "other",
                "sparse.txt": "sparse_missing",
            },
        )

    def test_unscanned_and_binary_regular_members_count_without_a_content_read(self) -> None:
        rules = (
            FileRule(
                "generated",
                ("generated/**",),
                FileKind.GENERATED,
                False,
                None,
                None,
                "generated",
            ),
            FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),
        )
        context = ContextSet("bundle", ("generated/blob.bin",), (), 4, 5)
        reads: list[str] = []
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(file_rules=rules, context_sets=(context,))),
            (regular("generated/blob.bin", 6),),
            lambda entry: reads.append(entry.path) or b"ignored",
            evaluation_date=TODAY,
        )
        self.assertEqual(reads, [])
        self.assertEqual(evaluation.contexts[0].total_bytes, 6)
        self.assertEqual(evaluation.contexts[0].limit_state, LimitState.HARD)
        hard = evaluation.diagnostics[0]
        self.assertEqual(hard.code, CONTEXT_HARD_BYTES)
        self.assertEqual(hard.severity, Severity.ERROR)
        self.assertEqual(
            dict(hard.details),
            {
                "context_index": 0,
                "context_name": "bundle",
                "total_bytes": 6,
                "warn_bytes": 4,
                "hard_bytes": 5,
                "member_count": 1,
            },
        )

    def test_context_threshold_boundaries_match_file_threshold_rules(self) -> None:
        contexts = (
            ContextSet("at-warn", ("warn.txt",), (), 10, 20),
            ContextSet("over-warn", ("warn-plus.txt",), (), 10, 20),
            ContextSet("at-hard", ("hard.txt",), (), 10, 20),
            ContextSet("over-hard", ("hard-plus.txt",), (), 10, 20),
        )
        entries = (
            regular("warn.txt", 10),
            regular("warn-plus.txt", 11),
            regular("hard.txt", 20),
            regular("hard-plus.txt", 21),
        )
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(warn_bytes=100, hard_bytes=200, context_sets=contexts)),
            entries,
            lambda entry: b"a" * entry.size_bytes,
            evaluation_date=TODAY,
        )
        self.assertEqual(
            tuple((item.name, item.limit_state) for item in evaluation.contexts),
            (
                ("at-warn", LimitState.WITHIN),
                ("over-warn", LimitState.WARNING),
                ("at-hard", LimitState.WARNING),
                ("over-hard", LimitState.HARD),
            ),
        )
        self.assertEqual(
            tuple(item.code for item in evaluation.diagnostics),
            (CONTEXT_WARN_BYTES, CONTEXT_WARN_BYTES, CONTEXT_HARD_BYTES),
        )
        self.assertTrue(
            all(
                item.severity is Severity.WARNING
                for item in evaluation.diagnostics
                if item.code == CONTEXT_WARN_BYTES
            )
        )

    def test_unmatched_patterns_and_pattern_only_nonregular_members_are_not_missing(self) -> None:
        contexts = (
            ContextSet("pattern-only", (), ("docs/*.md",), 10, 20),
            ContextSet("unmatched", (), ("notes/*.md",), 10, 20),
        )
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(context_sets=contexts)),
            (
                InventoryEntry(
                    "docs/link.md",
                    InventorySource.TRACKED,
                    WorktreeKind.SYMLINK,
                ),
            ),
            lambda _entry: self.fail("a symlink must not be read"),
            evaluation_date=TODAY,
        )
        self.assertEqual(
            tuple(item.path for item in evaluation.contexts[0].members),
            ("docs/link.md",),
        )
        self.assertEqual(evaluation.contexts[0].missing_exact_paths, ())
        self.assertEqual(evaluation.contexts[1].members, ())
        self.assertEqual(evaluation.diagnostics, ())


if __name__ == "__main__":
    unittest.main()
