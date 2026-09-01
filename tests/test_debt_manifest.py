from __future__ import annotations

import hashlib
import json
import unittest

from repo_context.debt import (
    DebtManifestError,
    capture_debt_manifest,
    debt_manifest_path,
    parse_debt_manifest,
    render_debt_manifest,
)
from repo_context.diagnostics import (
    CFG_DUPLICATE_SELECTOR,
    CFG_MISSING_KEY,
    CFG_PARSE,
    CFG_PATH,
    CFG_TYPE,
    CFG_UNKNOWN_KEY,
    CFG_VALUE,
)
from repo_context.model import FileKind, FileRule, MigrationDebtEntry, MigrationDebtManifest
from repo_context.sizes import compile_size_policy, evaluate_sizes
from tests.support.sizes import TODAY, policy_with, regular


def _evaluate(payloads: dict[str, bytes], *, rules=None):
    policy = policy_with(
        warn_bytes=10,
        hard_bytes=20,
        file_rules=(
            FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20),
        )
        if rules is None
        else rules,
    )
    return evaluate_sizes(
        compile_size_policy(policy),
        tuple(regular(path, len(data)) for path, data in reversed(tuple(payloads.items()))),
        lambda entry: payloads[entry.path],
        evaluation_date=TODAY,
    )


class DebtManifestTests(unittest.TestCase):
    def test_capture_records_exact_sorted_paths_sizes_and_content_identities(self) -> None:
        payloads = {"z.txt": b"z" * 22, "a.txt": b"a\r\n" * 8, "small.txt": b"s" * 20}
        manifest = capture_debt_manifest(_evaluate(payloads).files)

        self.assertEqual(tuple(item.path for item in manifest.entries), ("a.txt", "z.txt"))
        self.assertEqual(manifest.entries[0].size_bytes, len(payloads["a.txt"]))
        self.assertEqual(
            manifest.entries[0].content_identity,
            f"sha256:{hashlib.sha256(payloads['a.txt']).hexdigest()}",
        )
        self.assertEqual(
            render_debt_manifest(manifest),
            (
                b'{\n  "schema_version": 1,\n  "entries": [\n'
                b'    {\n      "path": "a.txt",\n      "size_bytes": 24,\n'
                + f'      "content_identity": "sha256:{hashlib.sha256(payloads["a.txt"]).hexdigest()}"\n'.encode()
                + b"    },\n"
                + b'    {\n      "path": "z.txt",\n      "size_bytes": 22,\n'
                + f'      "content_identity": "sha256:{hashlib.sha256(payloads["z.txt"]).hexdigest()}"\n'.encode()
                + b"    }\n  ]\n}\n"
            ),
        )

    def test_round_trip_is_canonical_and_immutable(self) -> None:
        manifest = capture_debt_manifest(_evaluate({"legacy.txt": b"x" * 21}).files)
        rendered = render_debt_manifest(manifest)
        parsed = parse_debt_manifest(rendered, source_path="repo-context-debt.json")

        self.assertEqual(parsed, manifest)
        self.assertEqual(render_debt_manifest(parsed), rendered)
        with self.assertRaisesRegex(AttributeError, "cannot assign"):
            parsed.schema_version = 2

    def test_sidecar_path_is_derived_from_the_selected_config_path(self) -> None:
        self.assertEqual(debt_manifest_path("repo-context.toml"), "repo-context.debt.json")
        self.assertEqual(
            debt_manifest_path("config/custom.toml"),
            "config/custom.debt.json",
        )
        self.assertEqual(debt_manifest_path("policy"), "policy.debt.json")
        with self.assertRaises(ValueError):
            debt_manifest_path("../outside.toml")
        with self.assertRaises(ValueError):
            debt_manifest_path("config/*.toml")

    def test_entry_paths_round_trip_git_valid_literal_filename_data(self) -> None:
        payloads = {
            "legacy*.txt": b"a" * 21,
            "legacy\\name.txt": b"b" * 22,
            "line\nbreak\t?.txt": b"c" * 23,
        }
        manifest = capture_debt_manifest(_evaluate(payloads).files)
        rendered = render_debt_manifest(manifest)

        self.assertEqual(parse_debt_manifest(rendered), manifest)
        self.assertIn(b'"path": "legacy*.txt"', rendered)
        self.assertIn(b'"path": "legacy\\\\name.txt"', rendered)
        self.assertIn(b'"path": "line\\nbreak\\t?.txt"', rendered)

    def test_capture_omits_within_limit_binary_and_non_authored_files(self) -> None:
        rules = (
            FileRule("generated", ("generated/**",), FileKind.GENERATED, True, 10, 20),
            FileRule("authored", ("**",), FileKind.AUTHORED, True, 10, 20),
        )
        evaluation = _evaluate(
            {
                "binary.bin": b"\x00" * 30,
                "generated/data.txt": b"g" * 30,
                "small.txt": b"s" * 20,
            },
            rules=rules,
        )
        self.assertEqual(capture_debt_manifest(evaluation.files).entries, ())

    def test_parser_rejects_noncanonical_paths_duplicates_and_invalid_identities(self) -> None:
        template = b'{"schema_version":1,"entries":[{"path":"PATH","size_bytes":21,"content_identity":"HASH"}]}'
        valid_hash = b"sha256:" + b"a" * 64
        cases = (
            (template.replace(b"PATH", b"../escape" ).replace(b"HASH", valid_hash), CFG_PATH),
            (template.replace(b"PATH", b"\\ud800").replace(b"HASH", valid_hash), CFG_PATH),
            (template.replace(b"PATH", b"a.txt").replace(b"HASH", b"sha256:" + b"A" * 64), CFG_VALUE),
            (template.replace(b"PATH", b"a.txt").replace(b"HASH", b"short"), CFG_VALUE),
            (template.replace(b"PATH", b"a.txt").replace(b"HASH", valid_hash).replace(b"21", b"true"), CFG_TYPE),
        )
        for data, code in cases:
            with self.subTest(code=code, data=data):
                with self.assertRaises(DebtManifestError) as raised:
                    parse_debt_manifest(data)
                self.assertEqual(raised.exception.diagnostics[0].code, code)

        duplicate = (
            b'{"schema_version":1,"entries":['
            b'{"path":"a.txt","size_bytes":21,"content_identity":"' + valid_hash + b'"},'
            b'{"path":"a.txt","size_bytes":22,"content_identity":"' + valid_hash + b'"}]}'
        )
        with self.assertRaises(DebtManifestError) as raised:
            parse_debt_manifest(duplicate)
        self.assertEqual(raised.exception.diagnostics[0].code, CFG_DUPLICATE_SELECTOR)

    def test_parser_is_strict_about_json_shape_types_and_version(self) -> None:
        cases = (
            (b"not json", CFG_PARSE),
            (b'{"schema_version":1,"schema_version":1,"entries":[]}', CFG_PARSE),
            (
                b'{"schema_version":1,"entries":[{"path":"a.txt","size_bytes":NaN,"content_identity":"sha256:'
                + b"a" * 64
                + b'"}]}',
                CFG_PARSE,
            ),
            (b"[]", CFG_TYPE),
            (b'{"schema_version":2,"entries":[]}', CFG_VALUE),
            (b'{"schema_version":true,"entries":[]}', CFG_TYPE),
            (b'{"schema_version":1,"entries":{}}', CFG_TYPE),
            (b'{"schema_version":1}', CFG_MISSING_KEY),
            (b'{"schema_version":1,"entries":[],"extra":1}', CFG_UNKNOWN_KEY),
        )
        for data, first_code in cases:
            with self.subTest(data=data):
                with self.assertRaises(DebtManifestError) as raised:
                    parse_debt_manifest(data)
                self.assertEqual(raised.exception.diagnostics[0].code, first_code)

    def test_parser_uses_unambiguous_field_paths_and_structured_key_details(self) -> None:
        with self.assertRaises(DebtManifestError) as missing:
            parse_debt_manifest(b'{"schema_version":1}')
        missing_diagnostic = missing.exception.diagnostics[0]
        self.assertEqual(missing_diagnostic.field_path, "entries")
        self.assertEqual(dict(missing_diagnostic.details), {"key": "entries"})

        unusual_key = 'bad"\\\n'
        data = json.dumps(
            {"schema_version": 1, "entries": [], unusual_key: 1},
        ).encode("utf-8")
        with self.assertRaises(DebtManifestError) as unknown:
            parse_debt_manifest(data)
        unknown_diagnostic = unknown.exception.diagnostics[0]
        self.assertEqual(
            unknown_diagnostic.field_path,
            f"$[{json.dumps(unusual_key, ensure_ascii=True)}]",
        )
        self.assertEqual(dict(unknown_diagnostic.details), {"key": unusual_key})

        nested = (
            b'{"schema_version":1,"entries":['
            b'{"path":"a.txt","size_bytes":21,"content_identity":"sha256:'
            + b"a" * 64
            + b'","extra":1}]}'
        )
        with self.assertRaises(DebtManifestError) as nested_unknown:
            parse_debt_manifest(nested)
        self.assertEqual(
            nested_unknown.exception.diagnostics[0].field_path,
            "entries[0].extra",
        )

    def test_json_syntax_error_preserves_real_line_and_column(self) -> None:
        malformed = b'{\n  "schema_version": 1,\n  "entries": ]\n}'

        with self.assertRaises(DebtManifestError) as raised:
            parse_debt_manifest(malformed, source_path="policy.debt.json")

        location = raised.exception.diagnostics[0].location
        self.assertEqual((location.path, location.line, location.column), ("policy.debt.json", 3, 14))

    def test_renderer_rejects_noncanonical_direct_model_values(self) -> None:
        valid = MigrationDebtEntry("legacy.txt", 21, "sha256:" + "a" * 64)
        for manifest in (
            MigrationDebtManifest(True, (valid,)),
            MigrationDebtManifest(1, (MigrationDebtEntry("legacy.txt", True, valid.content_identity),)),
            MigrationDebtManifest(1, (MigrationDebtEntry("\ud800", 21, valid.content_identity),)),
        ):
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                render_debt_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
