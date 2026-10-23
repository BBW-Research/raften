"""Debt structure is bounded before the allocating JSON decoder runs."""

import json
import unittest
from unittest.mock import patch

from raften.debt import parse_debt_manifest, render_debt_manifest, capture_debt_manifest
from raften.model import MigrationDebtEntry, MigrationDebtManifest
from raften.repository_errors import RepositoryAccessError
from tests.test_debt_manifest import _evaluate


class DebtResourceTests(unittest.TestCase):
    def assert_preflight_refusal(self, raw, resource, **ceilings):
        with patch.multiple("raften.resource_limits", **ceilings), patch("raften.debt.json.loads") as decode:
            with self.assertRaises(RepositoryAccessError) as caught:
                parse_debt_manifest(raw, source_path="custom.debt.json")
            decode.assert_not_called()
        diagnostic = caught.exception.diagnostics[0]
        self.assertEqual(diagnostic.code, "GIT010")
        self.assertEqual(dict(diagnostic.details)["resource"], resource)
        self.assertEqual(diagnostic.location.path, "custom.debt.json")

    def test_excessive_arrays_keys_nesting_and_numbers_refuse_before_decode(self):
        cases = (
            (b'{"entries":[' + b'0,' * 20 + b'0]}', "manifest_array_items", {"MAX_MANIFEST_ENTRIES": 20}),
            (b'{' + b'"k":0,' * 20 + b'"k":0}', "manifest_object_keys", {"MAX_MANIFEST_OBJECT_KEYS": 20}),
            (b'[' * 17 + b'0' + b']' * 17, "manifest_depth", {"MAX_MANIFEST_DEPTH": 16}),
            (b'{"schema_version":' + b'1' * 129 + b'}', "manifest_number_characters", {"MAX_MANIFEST_NUMBER_CHARACTERS": 128}),
            (b'{"schema_version":1,"entries":[]}', "manifest_tokens", {"MAX_MANIFEST_TOKENS": 8}),
        )
        for raw, resource, ceilings in cases:
            with self.subTest(resource=resource):
                self.assert_preflight_refusal(raw, resource, **ceilings)

    def test_exact_token_depth_key_and_array_limits_succeed(self):
        raw = b'{"schema_version":1,"entries":[]}'
        with patch.multiple("raften.resource_limits", MAX_MANIFEST_TOKENS=10,
                            MAX_MANIFEST_DEPTH=2, MAX_MANIFEST_OBJECT_KEYS=2,
                            MAX_MANIFEST_ENTRIES=0):
            self.assertEqual(parse_debt_manifest(raw).entries, ())

    def test_strings_do_not_contribute_fake_structure(self):
        entry = MigrationDebtEntry('a[]{}:,"\\\né.txt', 21, "sha256:" + "a" * 64)
        manifest = MigrationDebtManifest(1, (entry,))
        for ensure_ascii in (False, True):
            raw = json.dumps({"schema_version": 1, "entries": [{"path": entry.path,
                "size_bytes": 21, "content_identity": entry.content_identity}]}, ensure_ascii=ensure_ascii).encode()
            with patch.multiple("raften.resource_limits", MAX_MANIFEST_DEPTH=3,
                                MAX_MANIFEST_ENTRIES=1, MAX_MANIFEST_OBJECT_KEYS=3):
                self.assertEqual(parse_debt_manifest(raw), manifest)

    def test_render_and_capture_enforce_entry_limit_before_projection(self):
        entries = tuple(MigrationDebtEntry(name, 21, "sha256:" + "a" * 64) for name in ("a", "b"))
        with patch("raften.resource_limits.MAX_MANIFEST_ENTRIES", 1), \
                patch("raften.debt.json.JSONEncoder") as encoder:
            with self.assertRaises(RepositoryAccessError):
                render_debt_manifest(MigrationDebtManifest(1, entries))
            encoder.assert_not_called()
            with self.assertRaises(RepositoryAccessError):
                capture_debt_manifest(_evaluate({"a": b'a' * 21, "b": b'b' * 21}).files)
        with patch("raften.resource_limits.MAX_MANIFEST_ENTRIES", 2):
            self.assertEqual(parse_debt_manifest(render_debt_manifest(MigrationDebtManifest(1, entries))).entries, entries)
