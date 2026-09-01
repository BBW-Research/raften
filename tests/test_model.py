from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass

from repo_context.config import starter_policy
from repo_context.model import (
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
    RunResult,
    RunStatus,
    Severity,
    SourceLocation,
    WorktreeKind,
)


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
        result = RunResult(
            status=RunStatus.COMPLETE,
            diagnostics=(diagnostic,),
            inventory=(inventory,),
            links=(link,),
        )
        self.assertEqual(result.inventory[0].source, InventorySource.TRACKED)
        self.assertEqual(result.inventory[0].index, metadata)
        self.assertEqual(result.links[0].kind, LinkKind.NAVIGATION)
        self.assertEqual(result.diagnostics[0].details, (("size_bytes", 100),))
        with self.assertRaises(FrozenInstanceError):
            result.status = RunStatus.INTERNAL_ERROR  # type: ignore[misc]

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


if __name__ == "__main__":
    unittest.main()
