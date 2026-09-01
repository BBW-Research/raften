from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date

from repo_context.debt import capture_debt_manifest
from repo_context.diagnostics import (
    FILE_HARD_BYTES,
    RAT_BASE_TYPE_CHANGED,
    RAT_BASE_WITHIN_ORDINARY,
    RAT_COMPARISON_UNAVAILABLE,
    RAT_NEW_OVERSIZE,
    RAT_SIZE_REGRESSION,
)
from repo_context.model import (
    BaseTreeEntry,
    ContentState,
    ExactSelector,
    FileKind,
    FileRule,
    GitFileMode,
    GitObjectType,
    IntentionalException,
    MigrationStatus,
    RatchetBaselineSource,
    RatchetUnavailableReason,
)
from repo_context.ratchet import (
    evaluate_file_ratchet,
    is_all_zero_ref,
    reconcile_size_diagnostics,
)
from repo_context.sizes import compile_size_policy, evaluate_sizes
from tests.support.sizes import TODAY, policy_with, regular


def _current_evaluation(payloads: dict[str, bytes], *, policy=None):
    selected_policy = policy_with(warn_bytes=40, hard_bytes=50) if policy is None else policy
    evaluation = evaluate_sizes(
        compile_size_policy(selected_policy),
        tuple(regular(path, len(data)) for path, data in reversed(tuple(payloads.items()))),
        lambda entry: payloads[entry.path],
        evaluation_date=TODAY,
    )
    return selected_policy, evaluation


def _base_entry(
    path: str,
    token: str,
    *,
    mode: GitFileMode = GitFileMode.REGULAR,
    object_type: GitObjectType = GitObjectType.BLOB,
) -> BaseTreeEntry:
    return BaseTreeEntry(path, mode, object_type, token * 40)


class FileRatchetTests(unittest.TestCase):
    def test_file_ratchet_diagnostic_identities_are_frozen(self) -> None:
        self.assertEqual(
            (
                RAT_COMPARISON_UNAVAILABLE,
                RAT_NEW_OVERSIZE,
                RAT_BASE_WITHIN_ORDINARY,
                RAT_SIZE_REGRESSION,
                RAT_BASE_TYPE_CHANGED,
            ),
            ("RAT001", "RAT002", "RAT003", "RAT004", "RAT005"),
        )

    def test_new_oversized_authored_plaintext_is_rejected(self) -> None:
        current_policy, current = _current_evaluation({"new.txt": b"n" * 51})

        result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(),
            read_base=lambda _entry: self.fail("a missing base path must not be read"),
        )

        self.assertEqual(result.baseline_source, RatchetBaselineSource.GIT)
        self.assertEqual(tuple(item.code for item in result.diagnostics), (RAT_NEW_OVERSIZE,))
        self.assertEqual(result.files[0].migration_status, MigrationStatus.VIOLATION)
        self.assertEqual(dict(result.diagnostics[0].details)["reason"], "new_path")

    def test_base_version_must_itself_be_oversized_authored_plaintext(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 60})
        cases = (
            (
                "within_ordinary_limit",
                RAT_BASE_WITHIN_ORDINARY,
                _base_entry("legacy.txt", "a"),
                b"b" * 50,
            ),
            (
                "non_plaintext",
                RAT_BASE_TYPE_CHANGED,
                _base_entry("legacy.txt", "b"),
                b"\x00" * 100,
            ),
            (
                "non_plaintext",
                RAT_BASE_TYPE_CHANGED,
                _base_entry("legacy.txt", "c"),
                b"invalid-\xff" * 20,
            ),
            (
                "non_regular_type",
                RAT_BASE_TYPE_CHANGED,
                _base_entry("legacy.txt", "d", mode=GitFileMode.SYMLINK),
                b"target",
            ),
            (
                "non_regular_type",
                RAT_BASE_TYPE_CHANGED,
                _base_entry(
                    "legacy.txt",
                    "e",
                    mode=GitFileMode.GITLINK,
                    object_type=GitObjectType.COMMIT,
                ),
                b"unread",
            ),
        )
        for reason, code, entry, payload in cases:
            with self.subTest(reason=reason):
                reads: list[str] = []

                def read_base(selected: BaseTreeEntry) -> bytes:
                    reads.append(selected.path)
                    return payload

                result = evaluate_file_ratchet(
                    current_policy,
                    current.files,
                    evaluation_date=TODAY,
                    base_policy=current_policy,
                    base_entries=(entry,),
                    read_base=read_base,
                )

                self.assertEqual(tuple(item.code for item in result.diagnostics), (code,))
                self.assertEqual(dict(result.diagnostics[0].details)["reason"], reason)
                self.assertIsNone(result.files[0].ceiling_bytes)
                expected_reads = [] if reason == "non_regular_type" else ["legacy.txt"]
                self.assertEqual(reads, expected_reads)

    def test_equal_or_smaller_oversized_file_is_migration_debt(self) -> None:
        base_entry = _base_entry("legacy.txt", "a")
        for size in (100, 60):
            with self.subTest(size=size):
                current_policy, current = _current_evaluation({"legacy.txt": b"c" * size})
                result = evaluate_file_ratchet(
                    current_policy,
                    current.files,
                    evaluation_date=TODAY,
                    base_policy=current_policy,
                    base_entries=(base_entry,),
                    read_base=lambda _entry: b"b" * 100,
                )
                self.assertEqual(result.diagnostics, ())
                self.assertEqual(result.files[0].migration_status, MigrationStatus.DEBT)
                self.assertEqual(result.files[0].base_size_bytes, 100)
                self.assertEqual(result.files[0].ceiling_bytes, 100)

    def test_current_ordinary_limit_is_authoritative_not_the_base_policy_limit(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 60})
        base_policy = replace(
            current_policy,
            file_rules=(FileRule("authored", ("**",), FileKind.AUTHORED, True, 100, 200),),
        )
        result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=base_policy,
            base_entries=(_base_entry("legacy.txt", "a"),),
            read_base=lambda _entry: b"b" * 100,
        )

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.files[0].migration_status, MigrationStatus.DEBT)
        self.assertEqual(result.files[0].ordinary_hard_bytes, 50)

    def test_regular_and_executable_modes_share_one_regular_file_type(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 60})
        result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(_base_entry("legacy.txt", "a", mode=GitFileMode.EXECUTABLE),),
            read_base=lambda _entry: b"b" * 100,
        )
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.files[0].migration_status, MigrationStatus.DEBT)

    def test_partial_reduction_is_the_next_automatic_ceiling(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 61})
        result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(_base_entry("legacy.txt", "a"),),
            read_base=lambda _entry: b"b" * 60,
        )

        self.assertEqual(tuple(item.code for item in result.diagnostics), (RAT_SIZE_REGRESSION,))
        self.assertEqual(
            dict(result.diagnostics[0].details),
            {
                "base_size_bytes": 60,
                "current_size_bytes": 61,
                "ordinary_hard_bytes": 50,
            },
        )

    def test_returning_within_the_ordinary_limit_clears_debt(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 50})
        result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(_base_entry("legacy.txt", "a"),),
            read_base=lambda _entry: self.fail("a cleared path must not read its base blob"),
        )

        self.assertEqual(result.files, ())
        self.assertEqual(result.diagnostics, ())

    def test_only_current_oversized_authored_plaintext_enters_the_ratchet(self) -> None:
        rules = (
            FileRule("generated", ("generated/**",), FileKind.GENERATED, True, 40, 50),
            FileRule("authored", ("**",), FileKind.AUTHORED, True, 40, 50),
        )
        selected_policy = policy_with(file_rules=rules)
        current_policy, current = _current_evaluation(
            {
                "binary.bin": b"\x00" * 100,
                "generated/output.txt": b"g" * 100,
                "small.txt": b"s" * 50,
            },
            policy=selected_policy,
        )
        result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(),
            read_base=lambda _entry: self.fail("no ineligible path may be read"),
        )

        self.assertEqual(result.files, ())
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            {item.entry.path: item.content_state for item in current.files},
            {
                "binary.bin": ContentState.CONTAINS_NUL,
                "generated/output.txt": ContentState.PLAINTEXT,
                "small.txt": ContentState.PLAINTEXT,
            },
        )

    def test_unavailable_and_disabled_comparisons_are_explicit(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 60})
        unavailable = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            unavailable_reason=RatchetUnavailableReason.BASE_REF_ABSENT,
        )
        zero_sentinel = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            unavailable_reason=RatchetUnavailableReason.ZERO_SENTINEL,
        )
        disabled_policy = replace(
            current_policy,
            ratchet=replace(current_policy.ratchet, compare_file_sizes=False),
        )
        disabled = evaluate_file_ratchet(
            disabled_policy,
            current.files,
            evaluation_date=TODAY,
        )

        self.assertEqual(unavailable.baseline_source, RatchetBaselineSource.UNAVAILABLE)
        self.assertEqual(unavailable.files[0].migration_status, MigrationStatus.UNBASELINED)
        self.assertEqual(tuple(item.code for item in unavailable.diagnostics), (RAT_COMPARISON_UNAVAILABLE,))
        self.assertEqual(unavailable.diagnostics[0].severity.value, "note")
        self.assertEqual(dict(zero_sentinel.diagnostics[0].details)["reason"], "zero_sentinel")
        self.assertEqual(disabled.baseline_source, RatchetBaselineSource.DISABLED)
        self.assertEqual(disabled.files[0].migration_status, MigrationStatus.UNBASELINED)
        self.assertEqual(disabled.diagnostics, ())

    def test_first_adoption_manifest_is_used_only_without_a_base_policy(self) -> None:
        current_policy, captured = _current_evaluation({"legacy.txt": b"b" * 100})
        manifest = capture_debt_manifest(captured.files)
        _policy, current = _current_evaluation({"legacy.txt": b"c" * 60})
        manifest_result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            debt_manifest=manifest,
        )
        git_result = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(_base_entry("legacy.txt", "a"),),
            read_base=lambda _entry: b"b" * 50,
            debt_manifest=manifest,
        )

        self.assertEqual(manifest_result.baseline_source, RatchetBaselineSource.MANIFEST)
        self.assertEqual(manifest_result.diagnostics, ())
        self.assertEqual(manifest_result.files[0].migration_status, MigrationStatus.DEBT)
        self.assertEqual(git_result.baseline_source, RatchetBaselineSource.GIT)
        self.assertEqual(tuple(item.code for item in git_result.diagnostics), (RAT_BASE_WITHIN_ORDINARY,))
        self.assertEqual(git_result.files[0].base_size_bytes, 50)
        self.assertIsNone(git_result.files[0].ceiling_bytes)

    def test_manifest_rejects_new_paths_and_growth_but_allows_partial_reduction(self) -> None:
        current_policy, captured = _current_evaluation({"legacy.txt": b"b" * 100})
        manifest = capture_debt_manifest(captured.files)
        cases = (
            ({"legacy.txt": b"c" * 99}, ()),
            ({"legacy.txt": b"c" * 101}, (RAT_SIZE_REGRESSION,)),
            ({"legacy.txt": b"c" * 99, "new.txt": b"n" * 51}, (RAT_NEW_OVERSIZE,)),
        )
        for payloads, expected in cases:
            with self.subTest(payloads={path: len(data) for path, data in payloads.items()}):
                _policy, current = _current_evaluation(payloads)
                result = evaluate_file_ratchet(
                    current_policy,
                    current.files,
                    evaluation_date=TODAY,
                    debt_manifest=manifest,
                )
                self.assertEqual(tuple(item.code for item in result.diagnostics), expected)

    def test_proven_debt_suppresses_ctx002_but_violations_and_unavailable_comparison_do_not(self) -> None:
        current_policy, current = _current_evaluation({"legacy.txt": b"c" * 60})
        self.assertEqual(tuple(item.code for item in current.diagnostics), (FILE_HARD_BYTES,))
        debt = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(_base_entry("legacy.txt", "a"),),
            read_base=lambda _entry: b"b" * 100,
        )
        growth = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
            base_policy=current_policy,
            base_entries=(_base_entry("legacy.txt", "b"),),
            read_base=lambda _entry: b"b" * 59,
        )
        unavailable = evaluate_file_ratchet(
            current_policy,
            current.files,
            evaluation_date=TODAY,
        )

        self.assertEqual(reconcile_size_diagnostics(current.diagnostics, debt), ())
        self.assertEqual(tuple(item.code for item in reconcile_size_diagnostics(current.diagnostics, growth)), (FILE_HARD_BYTES,))
        self.assertEqual(tuple(item.code for item in reconcile_size_diagnostics(current.diagnostics, unavailable)), (FILE_HARD_BYTES,))

    def test_ordinary_oversize_is_classified_once_even_when_an_exception_disables_effective_scan(self) -> None:
        base = policy_with(warn_bytes=40, hard_bytes=50)
        exception = IntentionalException(
            ExactSelector("legacy.txt"),
            "maintainers",
            "temporary binary review",
            "issue-9",
            date(2026, 1, 1),
            None,
            False,
            None,
            None,
        )
        policy = replace(base, exceptions=replace(base.exceptions, records=(exception,)))
        calls: list[str] = []

        def read(entry):
            calls.append(entry.path)
            return b"x" * 60

        current = evaluate_sizes(
            compile_size_policy(policy),
            (regular("legacy.txt", 60),),
            read,
            evaluation_date=TODAY,
        )

        self.assertEqual(calls, ["legacy.txt"])
        self.assertEqual(current.files[0].content_state, ContentState.PLAINTEXT)
        self.assertIsNotNone(current.files[0].content_identity)
        self.assertEqual(current.diagnostics, ())
        self.assertEqual(tuple(item.path for item in capture_debt_manifest(current.files).entries), ("legacy.txt",))

    def test_all_zero_ref_recognizes_the_ci_sentinel_only(self) -> None:
        self.assertTrue(is_all_zero_ref("0" * 16))
        self.assertTrue(is_all_zero_ref("0" * 40))
        self.assertTrue(is_all_zero_ref("0" * 64))
        self.assertFalse(is_all_zero_ref(""))
        self.assertFalse(is_all_zero_ref("00000001"))
        self.assertFalse(is_all_zero_ref("main"))


if __name__ == "__main__":
    unittest.main()
