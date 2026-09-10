from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass
from datetime import date

from raften.config import starter_policy
from raften.docs import compile_documentation_policy, evaluate_documentation
from raften.markdown import parse_markdown
from raften.model import (
    BaseRevision,
    BaseTreeEntry,
    Diagnostic,
    ExactSelector,
    GitFileMode,
    GitIndexMetadata,
    GitObjectType,
    InventoryEntry,
    InventorySource,
    Link,
    LinkKind,
    MigrationDebtEntry,
    MigrationDebtManifest,
    MigrationStatus,
    FileRatchetAssessment,
    FileRatchetEvaluation,
    RatchetBaselineSource,
    RatchetUnavailableReason,
    Severity,
    SourceLocation,
    TextDocument,
    WorktreeKind,
    WorktreeIdentity,
)
from raften.run_model import CommandFailure, RunStatus
from raften.sizes import compile_size_policy, evaluate_sizes, explain_size_path


class ImmutableModelTests(unittest.TestCase):
    def test_policy_and_nested_records_are_frozen_slotted_dataclasses(self) -> None:
        policy = starter_policy()
        records = (
            policy,
            policy.repository,
            policy.output,
            policy.file_rules[0],
            policy.path_overrides[0],
            policy.documentation,
            policy.entrypoints[0],
            policy.context_sets[0],
            policy.ratchet,
            policy.exceptions,
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertTrue(is_dataclass(record))
                self.assertTrue(hasattr(type(record), "__slots__"))
                field = fields(record)[0]
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, field.name, getattr(record, field.name))

    def test_policy_collections_and_selectors_have_immutable_shapes(self) -> None:
        policy = starter_policy()
        self.assertIsInstance(policy.file_rules, tuple)
        self.assertIsInstance(policy.file_rules[0].patterns, tuple)
        self.assertIsInstance(policy.path_overrides, tuple)
        self.assertIsInstance(policy.entrypoints[0].required_targets, tuple)
        self.assertIsInstance(policy.context_sets[0].paths, tuple)
        self.assertIsInstance(policy.exceptions.records, tuple)
        self.assertIsInstance(policy.path_overrides[0].selector, ExactSelector)
        with self.assertRaises(TypeError):
            policy.file_rules[0].patterns[0] = "changed"  # type: ignore[index]

    def test_operational_records_are_typed_and_immutable(self) -> None:
        metadata = GitIndexMetadata(
            mode=GitFileMode.REGULAR,
            object_id="a" * 40,
        )
        inventory = InventoryEntry(
            path="README.md",
            source=InventorySource.TRACKED,
            kind=WorktreeKind.REGULAR,
            size_bytes=100,
            index=metadata,
        )
        location = SourceLocation("README.md", 2, 4)
        link = Link(location, LinkKind.NAVIGATION, "docs/", "docs/index.md", None)
        diagnostic = Diagnostic(
            code="CTX001",
            severity=Severity.ERROR,
            message="example",
            location=location,
            details=(("size_bytes", 100),),
        )
        result = CommandFailure(
            status=RunStatus.OPERATIONAL_ERROR,
            diagnostics=(diagnostic,),
        )
        self.assertEqual(inventory.source, InventorySource.TRACKED)
        self.assertEqual(inventory.index, metadata)
        self.assertEqual(link.kind, LinkKind.NAVIGATION)
        self.assertEqual(result.diagnostics[0].details, (("size_bytes", 100),))
        with self.assertRaises(FrozenInstanceError):
            result.status = RunStatus.INTERNAL_ERROR  # type: ignore[misc]

    def test_phase_five_debt_and_ratchet_records_are_immutable(self) -> None:
        self.assertEqual(
            RatchetUnavailableReason.ZERO_SENTINEL.value,
            "zero_sentinel",
        )
        debt_entry = MigrationDebtEntry("legacy.txt", 100, "sha256:" + "a" * 64)
        manifest = MigrationDebtManifest(1, (debt_entry,))
        file_result = FileRatchetAssessment(
            "legacy.txt",
            60,
            50,
            100,
            "git:" + "b" * 40,
            100,
            RatchetBaselineSource.GIT,
            MigrationStatus.DEBT,
        )
        evaluation = FileRatchetEvaluation(RatchetBaselineSource.GIT, (file_result,), ())

        for record in (debt_entry, manifest, file_result, evaluation):
            with self.subTest(record=type(record).__name__):
                self.assertTrue(is_dataclass(record))
                self.assertTrue(hasattr(type(record), "__slots__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, fields(record)[0].name, "changed")

    def test_inventory_and_base_git_records_preserve_typed_metadata(self) -> None:
        deleted = InventoryEntry(
            path="removed.txt",
            source=InventorySource.DELETED,
            kind=WorktreeKind.MISSING,
            index=GitIndexMetadata(GitFileMode.EXECUTABLE, "b" * 64),
        )
        revision = BaseRevision(requested_ref="main", commit_id="c" * 64)
        base_entry = BaseTreeEntry(
            path="removed.txt",
            mode=GitFileMode.EXECUTABLE,
            object_type=GitObjectType.BLOB,
            object_id="b" * 64,
        )
        self.assertEqual(deleted.source, InventorySource.DELETED)
        self.assertEqual(deleted.index.mode, GitFileMode.EXECUTABLE)
        self.assertFalse(deleted.index.skip_worktree)
        self.assertEqual(revision.requested_ref, "main")
        self.assertEqual(base_entry.object_type, GitObjectType.BLOB)
        for record in (deleted, deleted.index, revision, base_entry):
            self.assertTrue(is_dataclass(record))
            self.assertTrue(hasattr(type(record), "__slots__"))
            with self.assertRaises(FrozenInstanceError):
                setattr(record, fields(record)[0].name, "changed")

    def test_phase_three_policy_and_evaluation_records_are_immutable(self) -> None:
        identity = WorktreeIdentity(0o100644, 1, 2, 4, 3, 4)
        entry = InventoryEntry(
            "README.md",
            InventorySource.TRACKED,
            WorktreeKind.REGULAR,
            size_bytes=4,
            identity=identity,
        )
        compiled = compile_size_policy(starter_policy())
        evaluation_date = date(2026, 9, 1)
        evaluation = evaluate_sizes(
            compiled,
            (entry,),
            lambda _entry: b"text",
            evaluation_date=evaluation_date,
            retain_text_paths=frozenset({"README.md"}),
        )
        explanation = explain_size_path(
            compiled,
            "README.md",
            evaluation_date,
            evaluation,
        )
        records = (
            identity,
            evaluation,
            evaluation.files[0],
            evaluation.files[0].policy,
            evaluation.files[0].policy.rule_match,
            evaluation.files[0].policy.override_match,
            evaluation.contexts[0],
            evaluation.contexts[0].members[0],
            evaluation.documents[0],
            explanation,
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertTrue(is_dataclass(record))
                self.assertTrue(hasattr(type(record), "__slots__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, fields(record)[0].name, "changed")

    def test_phase_four_markdown_and_graph_records_are_immutable(self) -> None:
        index_text = "# Docs\n[Guide](guide.md)\n"
        guide_text = "# Guide\n"
        parsed = parse_markdown("docs/index.md", index_text)
        entries = (
            InventoryEntry(
                "docs/index.md",
                InventorySource.TRACKED,
                WorktreeKind.REGULAR,
                size_bytes=len(index_text.encode("utf-8")),
            ),
            InventoryEntry(
                "docs/guide.md",
                InventorySource.TRACKED,
                WorktreeKind.REGULAR,
                size_bytes=len(guide_text.encode("utf-8")),
            ),
        )
        graph = evaluate_documentation(
            compile_documentation_policy(starter_policy()),
            entries,
            (
                TextDocument("docs/index.md", index_text, len(index_text.encode("utf-8"))),
                TextDocument("docs/guide.md", guide_text, len(guide_text.encode("utf-8"))),
            ),
        )
        records = (
            parsed,
            parsed.links[0],
            parsed.anchors[0],
            graph,
            graph.directories[0],
            graph.edges[0],
        )
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertTrue(is_dataclass(record))
                self.assertTrue(hasattr(type(record), "__slots__"))
                with self.assertRaises(FrozenInstanceError):
                    setattr(record, fields(record)[0].name, "changed")


if __name__ == "__main__":
    unittest.main()
