from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from raften.config import starter_policy
from raften.diagnostics import (
    CFG_EFFECTIVE_POLICY,
    CFG_UNCLASSIFIED_PATH,
    EXC_EXPIRED,
    FILE_HARD_BYTES,
    FILE_WARN_BYTES,
)
from raften.model import (
    ContentState,
    ContextSet,
    ExactSelector,
    FileKind,
    FileRule,
    IntentionalException,
    InventoryEntry,
    InventorySource,
    LimitState,
    Severity,
    WorktreeKind,
)
from raften.sizes import (
    classification_counts,
    classify_content,
    compile_size_policy,
    evaluate_sizes,
    explain_size_path,
    largest_governed_files,
)
from tests.support.sizes import TODAY, policy_with, regular


class ContentClassificationTests(unittest.TestCase):
    def test_plaintext_requires_no_nul_and_strict_utf8(self) -> None:
        cases = (
            (b"", ContentState.PLAINTEXT, ""),
            (b"plain\n", ContentState.PLAINTEXT, "plain\n"),
            (b"\xef\xbb\xbftext", ContentState.PLAINTEXT, "\ufefftext"),
            ("你好\r\n".encode(), ContentState.PLAINTEXT, "你好\r\n"),
            (b"\x00text", ContentState.CONTAINS_NUL, None),
            (b"text\x00", ContentState.CONTAINS_NUL, None),
            (b"\x00\xff", ContentState.CONTAINS_NUL, None),
            (b"bad-\xff", ContentState.INVALID_UTF8, None),
            (b"truncated-\xe2\x82", ContentState.INVALID_UTF8, None),
        )
        for data, state, text in cases:
            with self.subTest(data=data):
                classified = classify_content(data)
                self.assertEqual(classified.state, state)
                self.assertEqual(classified.text, text)
                self.assertEqual(classified.size_bytes, len(data))


class FileBudgetTests(unittest.TestCase):
    def test_warning_and_hard_boundaries_emit_only_the_strongest_diagnostic(self) -> None:
        payloads = {
            "warn-minus.txt": b"a" * 9,
            "warn.txt": b"a" * 10,
            "warn-plus.txt": b"a" * 11,
            "hard-minus.txt": b"a" * 19,
            "hard.txt": b"a" * 20,
            "hard-plus.txt": b"a" * 21,
        }
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with()),
            tuple(regular(path, len(data)) for path, data in reversed(tuple(payloads.items()))),
            lambda entry: payloads[entry.path],
            evaluation_date=TODAY,
        )
        states = {item.entry.path: item.limit_state for item in evaluation.files}
        self.assertEqual(states["warn-minus.txt"], LimitState.WITHIN)
        self.assertEqual(states["warn.txt"], LimitState.WITHIN)
        self.assertEqual(states["warn-plus.txt"], LimitState.WARNING)
        self.assertEqual(states["hard-minus.txt"], LimitState.WARNING)
        self.assertEqual(states["hard.txt"], LimitState.WARNING)
        self.assertEqual(states["hard-plus.txt"], LimitState.HARD)
        self.assertEqual(
            tuple((item.location.path, item.code) for item in evaluation.diagnostics),
            (
                ("hard-minus.txt", FILE_WARN_BYTES),
                ("hard-plus.txt", FILE_HARD_BYTES),
                ("hard.txt", FILE_WARN_BYTES),
                ("warn-plus.txt", FILE_WARN_BYTES),
            ),
        )
        hard = next(item for item in evaluation.diagnostics if item.code == FILE_HARD_BYTES)
        self.assertEqual(hard.severity, Severity.ERROR)
        self.assertEqual(
            dict(hard.details),
            {
                "size_bytes": 21,
                "warn_bytes": 10,
                "hard_bytes": 20,
                "kind": "authored",
                "rule_index": 0,
                "rule_name": "authored",
                "override_index": None,
                "exception_index": None,
            },
        )
        warnings = tuple(
            item for item in evaluation.diagnostics if item.code == FILE_WARN_BYTES
        )
        self.assertTrue(all(item.severity is Severity.WARNING for item in warnings))

    def test_raw_multibyte_and_crlf_bytes_are_not_normalized(self) -> None:
        payloads = {
            "multibyte.txt": "ééé".encode("utf-8"),
            "windows.txt": b"a\r\na\r\na\r\n",
        }
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(warn_bytes=5, hard_bytes=8)),
            tuple(regular(path, len(data)) for path, data in payloads.items()),
            lambda entry: payloads[entry.path],
            evaluation_date=TODAY,
        )
        assessments = {item.entry.path: item for item in evaluation.files}
        self.assertEqual(assessments["multibyte.txt"].size_bytes, 6)
        self.assertEqual(assessments["multibyte.txt"].limit_state, LimitState.WARNING)
        self.assertEqual(assessments["windows.txt"].size_bytes, 9)
        self.assertEqual(assessments["windows.txt"].limit_state, LimitState.HARD)

    def test_multibyte_and_crlf_payloads_cover_exact_threshold_boundaries(self) -> None:
        payloads = {
            "multibyte-hard-plus.txt": "éééa".encode(),
            "multibyte-hard.txt": "ééé".encode(),
            "multibyte-warn-minus.txt": "éa".encode(),
            "multibyte-warn-plus.txt": "ééa".encode(),
            "multibyte-warn.txt": "éé".encode(),
            "crlf-hard-plus.txt": b"\r\n\r\n\r\na",
            "crlf-hard.txt": b"\r\n\r\n\r\n",
            "crlf-warn-minus.txt": b"\r\na",
            "crlf-warn-plus.txt": b"\r\n\r\na",
            "crlf-warn.txt": b"\r\n\r\n",
        }
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(warn_bytes=4, hard_bytes=6)),
            tuple(regular(path, len(data)) for path, data in payloads.items()),
            lambda entry: payloads[entry.path],
            evaluation_date=TODAY,
        )
        states = {item.entry.path: item.limit_state for item in evaluation.files}
        for prefix in ("multibyte", "crlf"):
            with self.subTest(prefix=prefix):
                self.assertEqual(states[f"{prefix}-warn-minus.txt"], LimitState.WITHIN)
                self.assertEqual(states[f"{prefix}-warn.txt"], LimitState.WITHIN)
                self.assertEqual(states[f"{prefix}-warn-plus.txt"], LimitState.WARNING)
                self.assertEqual(states[f"{prefix}-hard.txt"], LimitState.WARNING)
                self.assertEqual(states[f"{prefix}-hard-plus.txt"], LimitState.HARD)

    def test_binary_unscanned_and_nonregular_entries_do_not_emit_file_limits(self) -> None:
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
            FileRule("authored", ("**",), FileKind.AUTHORED, True, 4, 5),
        )
        entries = (
            regular("binary.dat", 10),
            regular("generated/schema.json", 100),
            InventoryEntry("link", InventorySource.TRACKED, WorktreeKind.SYMLINK),
            InventoryEntry("removed", InventorySource.DELETED, WorktreeKind.MISSING),
        )
        reads: list[str] = []

        def read(entry: InventoryEntry) -> bytes:
            reads.append(entry.path)
            return b"\x00" * entry.size_bytes

        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(file_rules=rules)),
            entries,
            read,
            evaluation_date=TODAY,
        )
        by_path = {item.entry.path: item for item in evaluation.files}
        self.assertEqual(reads, ["binary.dat"])
        self.assertEqual(by_path["binary.dat"].content_state, ContentState.CONTAINS_NUL)
        self.assertEqual(by_path["generated/schema.json"].content_state, ContentState.UNREAD)
        self.assertIsNone(by_path["link"].content_state)
        self.assertIsNone(by_path["removed"].content_state)
        self.assertEqual(evaluation.diagnostics, ())

    def test_extensions_have_no_implicit_classification_or_exemption(self) -> None:
        payloads = {
            "schema.json": b"a" * 6,
            "archive.lock": b"a" * 6,
            "image.png": b"a" * 6,
        }
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(warn_bytes=4, hard_bytes=5)),
            tuple(regular(path, len(data)) for path, data in payloads.items()),
            lambda entry: payloads[entry.path],
            evaluation_date=TODAY,
        )
        self.assertEqual(
            tuple(item.policy.kind for item in evaluation.files),
            (FileKind.AUTHORED, FileKind.AUTHORED, FileKind.AUTHORED),
        )
        self.assertEqual(tuple(item.code for item in evaluation.diagnostics), (FILE_HARD_BYTES,) * 3)

    def test_each_scanned_file_is_read_once_and_retained_text_reuses_that_read(self) -> None:
        entries = (regular("a.md", 4), regular("b.txt", 4))
        calls: dict[str, int] = {}

        def read(entry: InventoryEntry) -> bytes:
            calls[entry.path] = calls.get(entry.path, 0) + 1
            return b"x\r\n\n"

        evaluation = evaluate_sizes(
            compile_size_policy(policy_with()),
            entries,
            read,
            evaluation_date=TODAY,
            retain_text_paths=frozenset({"a.md"}),
        )
        self.assertEqual(calls, {"a.md": 1, "b.txt": 1})
        self.assertEqual(tuple((item.path, item.text) for item in evaluation.documents), (("a.md", "x\r\n\n"),))

    def test_unclassified_inventory_path_is_a_configuration_diagnostic(self) -> None:
        policy = policy_with(
            file_rules=(
                FileRule("python", ("**/*.py",), FileKind.AUTHORED, True, 10, 20),
            )
        )
        evaluation = evaluate_sizes(
            compile_size_policy(policy),
            (regular("README.md", 4),),
            lambda _entry: b"text",
            evaluation_date=TODAY,
        )
        self.assertEqual(evaluation.files[0].policy, None)
        self.assertEqual(evaluation.diagnostics[0].code, CFG_UNCLASSIFIED_PATH)
        self.assertEqual(evaluation.diagnostics[0].location.path, "README.md")
        self.assertEqual(
            dict(evaluation.diagnostics[0].details),
            {"source": "tracked", "worktree_kind": "regular"},
        )


class ExceptionEvaluationTests(unittest.TestCase):
    def test_expired_exception_emits_a_structured_error_at_the_injected_date(self) -> None:
        exception = IntentionalException(
            ExactSelector("large.txt"),
            "owner",
            "temporary",
            "issue-1",
            date(2026, 1, 1),
            date(2026, 8, 31),
            None,
            30,
            40,
        )
        policy = replace(
            policy_with(),
            exceptions=replace(
                starter_policy().exceptions,
                records=(exception,),
            ),
        )
        evaluation = evaluate_sizes(
            compile_size_policy(policy),
            (regular("large.txt", 1),),
            lambda _entry: b"x",
            evaluation_date=TODAY,
        )
        expired = next(item for item in evaluation.diagnostics if item.code == EXC_EXPIRED)
        self.assertEqual(expired.severity, Severity.ERROR)
        self.assertEqual(expired.field_path, "exceptions.record[0].expires_on")
        self.assertEqual(
            dict(expired.details),
            {
                "exception_index": 0,
                "expires_on": "2026-08-31",
                "evaluation_date": "2026-09-01",
            },
        )
        self.assertIsNone(evaluation.files[0].policy.exception_match)

    def test_exception_cannot_create_an_incomplete_effective_scanned_policy(self) -> None:
        rule = FileRule(
            "generated",
            ("generated/**",),
            FileKind.GENERATED,
            False,
            None,
            None,
            "generated",
        )
        exception = IntentionalException(
            ExactSelector("generated/data.txt"),
            "owner",
            "scan temporarily",
            "issue-2",
            date(2026, 1, 1),
            None,
            True,
            None,
            None,
        )
        policy = replace(
            policy_with(file_rules=(rule,)),
            exceptions=replace(starter_policy().exceptions, records=(exception,)),
        )
        reads: list[str] = []
        evaluation = evaluate_sizes(
            compile_size_policy(policy),
            (regular("generated/data.txt", 5),),
            lambda entry: reads.append(entry.path) or b"data!",
            evaluation_date=TODAY,
        )
        self.assertEqual(reads, [])
        self.assertEqual(evaluation.diagnostics[0].code, CFG_EFFECTIVE_POLICY)
        self.assertEqual(evaluation.diagnostics[0].location.path, "generated/data.txt")
        self.assertEqual(
            dict(evaluation.diagnostics[0].details),
            {
                "rule_index": 0,
                "override_index": None,
                "exception_index": 0,
                "effective_scan": True,
                "effective_warn_bytes": None,
                "effective_hard_bytes": None,
            },
        )

    def test_exception_limits_cannot_govern_a_path_that_remains_unscanned(self) -> None:
        rule = FileRule(
            "generated",
            ("generated/**",),
            FileKind.GENERATED,
            False,
            None,
            None,
            "generated",
        )
        exception = IntentionalException(
            ExactSelector("generated/data.txt"),
            "owner",
            "temporary limits",
            "issue-3",
            date(2026, 1, 1),
            None,
            None,
            30,
            40,
        )
        policy = replace(
            policy_with(file_rules=(rule,)),
            exceptions=replace(starter_policy().exceptions, records=(exception,)),
        )
        reads: list[str] = []
        evaluation = evaluate_sizes(
            compile_size_policy(policy),
            (regular("generated/data.txt", 5),),
            lambda entry: reads.append(entry.path) or b"data!",
            evaluation_date=TODAY,
        )
        self.assertEqual(reads, [])
        self.assertEqual(evaluation.diagnostics[0].code, CFG_EFFECTIVE_POLICY)
        self.assertFalse(evaluation.files[0].policy.effective_scan)


class AuditAndExplainTests(unittest.TestCase):
    def test_audit_helpers_sort_largest_files_and_count_explicit_kinds(self) -> None:
        rules = (
            FileRule("fixture", ("fixtures/**",), FileKind.FIXTURE, True, 100, 200),
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
        entries = (
            regular("z.txt", 8),
            regular("a.txt", 8),
            regular("fixtures/data.txt", 12),
            regular("generated/schema.json", 20),
        )
        evaluation = evaluate_sizes(
            compile_size_policy(policy_with(file_rules=rules)),
            entries,
            lambda entry: b"a" * entry.size_bytes,
            evaluation_date=TODAY,
        )
        self.assertEqual(
            tuple(item.entry.path for item in largest_governed_files(evaluation)),
            ("generated/schema.json", "fixtures/data.txt", "a.txt", "z.txt"),
        )
        self.assertEqual(
            classification_counts(evaluation),
            (
                (FileKind.AUTHORED, 2),
                (FileKind.FIXTURE, 1),
                (FileKind.GENERATED, 1),
            ),
        )

    def test_explain_data_covers_existing_and_nonexistent_paths(self) -> None:
        context = ContextSet("bootstrap", ("README.md",), ("docs/*.md",), 100, 200)
        compiled = compile_size_policy(policy_with(context_sets=(context,)))
        evaluation = evaluate_sizes(
            compiled,
            (regular("README.md", 4),),
            lambda _entry: b"text",
            evaluation_date=TODAY,
        )
        existing = explain_size_path(compiled, "README.md", TODAY, evaluation)
        missing = explain_size_path(compiled, "docs/guide.md", TODAY, evaluation)
        self.assertEqual(existing.context_sets, ("bootstrap",))
        self.assertIsNotNone(existing.assessment)
        self.assertEqual(existing.policy.rule_match.rule_index, 0)
        self.assertEqual(missing.context_sets, ("bootstrap",))
        self.assertIsNone(missing.assessment)
        self.assertEqual(missing.policy.kind, FileKind.AUTHORED)


if __name__ == "__main__":
    unittest.main()
