from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, fields, is_dataclass

from repo_context.config import starter_policy
from repo_context.model import (
    Diagnostic,
    ExactSelector,
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
        inventory = InventoryEntry(
            path="README.md",
            source=InventorySource.TRACKED,
            kind=WorktreeKind.REGULAR,
            size_bytes=100,
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
        self.assertEqual(result.links[0].kind, LinkKind.NAVIGATION)
        self.assertEqual(result.diagnostics[0].details, (("size_bytes", 100),))
        with self.assertRaises(FrozenInstanceError):
            result.status = RunStatus.INTERNAL_ERROR  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
