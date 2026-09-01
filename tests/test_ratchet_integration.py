from __future__ import annotations

import unittest

from repo_context.config import load_policy, parse_policy
from repo_context.debt import capture_debt_manifest
from repo_context.diagnostics import (
    GIT_BASE_REVISION,
    RAT_FILE_LIMIT_INCREASED,
    RAT_NEW_OVERSIZE,
    RAT_SIZE_REGRESSION,
)
from repo_context.git_records import find_base_entry
from repo_context.inventory import (
    RepositoryAccessError,
    inventory_worktree,
    list_base_tree,
    open_repository,
    read_base_blob,
    read_worktree_bytes,
    resolve_base_revision,
)
from repo_context.model import MigrationStatus
from repo_context.model import GitFileMode
from repo_context.policy_ratchet import compare_policies
from repo_context.ratchet import evaluate_file_ratchet
from repo_context.sizes import compile_size_policy, evaluate_sizes
from tests.support.config import ROOT_POLICY_TEXT, replace_once
from tests.support.repository import RepositoryFixture, seed_policy
from tests.support.seed import ROOT, SEED
from tests.support.sizes import TODAY


def _policy_text() -> str:
    limited = replace_once(
        ROOT_POLICY_TEXT,
        "warn_bytes = 20480\nhard_bytes = 25600",
        "warn_bytes = 40\nhard_bytes = 50",
    )
    return replace_once(
        limited,
        "\n[documentation]\n",
        """
[[path_override]]
path = "repo-context.toml"
warn_bytes = 4096
hard_bytes = 8192

[documentation]
""",
    )


def _evaluate(repository: RepositoryFixture):
    policy = parse_policy(repository.path("repo-context.toml").read_bytes())
    handle = open_repository(repository.root)
    snapshot = inventory_worktree(handle)
    sizes = evaluate_sizes(
        compile_size_policy(policy),
        snapshot.entries,
        lambda entry: read_worktree_bytes(handle, entry),
        evaluation_date=TODAY,
    )
    return handle, policy, snapshot, sizes


def _base_policy(handle, tree, commit_id: str):
    entry = find_base_entry(tree, "repo-context.toml")
    if entry is None:
        raise AssertionError("fixture base policy is missing")
    return parse_policy(
        read_base_blob(handle, entry),
        source_path=f"{commit_id}:repo-context.toml",
    )


class RatchetRepositoryIntegrationTests(unittest.TestCase):
    def test_repository_policy_and_file_ratchets_pass_against_head(self) -> None:
        current_policy = load_policy(ROOT / "repo-context.toml")
        handle = open_repository(ROOT)
        snapshot = inventory_worktree(handle)
        sizes = evaluate_sizes(
            compile_size_policy(current_policy),
            snapshot.entries,
            lambda entry: read_worktree_bytes(handle, entry),
            evaluation_date=TODAY,
        )
        revision = resolve_base_revision(handle, "HEAD")
        tree = list_base_tree(handle, revision)
        base_policy = _base_policy(handle, tree, revision.commit_id)
        files = evaluate_file_ratchet(
            current_policy,
            sizes.files,
            evaluation_date=TODAY,
            base_policy=base_policy,
            base_entries=tree,
            read_base=lambda entry: read_base_blob(handle, entry),
        )

        self.assertEqual(compare_policies(current_policy, base_policy), ())
        self.assertEqual(files.diagnostics, ())

    def test_policy_weakening_is_read_from_the_exact_base_blob_without_current_violations(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", ROOT_POLICY_TEXT)
            repository.write_text("AGENTS.md", "x\n")
            repository.write_text("ARCHITECTURE.md", "x\n")
            repository.write_text("docs/index.md", "# Docs\n")
            repository.write_text("small.txt", "small")
            base_commit = repository.commit("base policy")
            repository.write_text(
                "repo-context.toml",
                replace_once(ROOT_POLICY_TEXT, "hard_bytes = 25600", "hard_bytes = 26000"),
            )
            status_before = repository.status_bytes()
            handle, current_policy, _snapshot, sizes = _evaluate(repository)
            revision = resolve_base_revision(handle, base_commit)
            tree = list_base_tree(handle, revision)
            base_policy = _base_policy(handle, tree, revision.commit_id)
            diagnostics = compare_policies(current_policy, base_policy)
            status_after = repository.status_bytes()

        self.assertEqual(sizes.diagnostics, ())
        self.assertEqual(status_after, status_before)
        self.assertIn(RAT_FILE_LIMIT_INCREASED, {item.code for item in diagnostics})

    def test_git_blob_comparison_locks_in_each_partial_reduction_without_mutation(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", _policy_text())
            repository.write_bytes("legacy.txt", b"a" * 100)
            base_commit = repository.commit("legacy debt")
            repository.write_bytes("legacy.txt", b"b" * 60)
            status_before = repository.status_bytes()
            handle, current_policy, _snapshot, sizes = _evaluate(repository)
            revision = resolve_base_revision(handle, base_commit)
            tree = list_base_tree(handle, revision)
            base_policy = _base_policy(handle, tree, revision.commit_id)

            result = evaluate_file_ratchet(
                current_policy,
                sizes.files,
                evaluation_date=TODAY,
                base_policy=base_policy,
                base_entries=tree,
                read_base=lambda entry: read_base_blob(handle, entry),
            )
            status_after = repository.status_bytes()

            self.assertEqual(status_after, status_before)
            self.assertEqual(result.diagnostics, ())
            legacy = next(item for item in result.files if item.path == "legacy.txt")
            self.assertEqual(legacy.migration_status, MigrationStatus.DEBT)
            self.assertEqual(legacy.base_size_bytes, 100)

            repository.commit("partial reduction")
            repository.write_bytes("legacy.txt", b"c" * 61)
            handle, current_policy, _snapshot, sizes = _evaluate(repository)
            revision = resolve_base_revision(handle, "HEAD")
            tree = list_base_tree(handle, revision)
            result = evaluate_file_ratchet(
                current_policy,
                sizes.files,
                evaluation_date=TODAY,
                base_policy=_base_policy(handle, tree, revision.commit_id),
                base_entries=tree,
                read_base=lambda entry: read_base_blob(handle, entry),
            )
            seed_errors, _text_count = SEED.check_sizes(
                repository.root,
                ["legacy.txt"],
                seed_policy(max_text_bytes=50, legacy_oversize={"legacy.txt": 100}),
            )

        regression = next(item for item in result.diagnostics if item.location.path == "legacy.txt")
        self.assertEqual(seed_errors, [])
        self.assertEqual(regression.code, RAT_SIZE_REGRESSION)
        self.assertEqual(dict(regression.details)["base_size_bytes"], 60)
        self.assertEqual(dict(regression.details)["current_size_bytes"], 61)

    def test_first_adoption_manifest_applies_when_the_resolved_base_has_no_policy(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("legacy.txt", b"a" * 100)
            base_commit = repository.commit("pre-adoption")
            repository.write_text("repo-context.toml", _policy_text())
            _handle, current_policy, _snapshot, captured = _evaluate(repository)
            manifest = capture_debt_manifest(captured.files)
            repository.write_bytes("legacy.txt", b"b" * 60)
            status_before = repository.status_bytes()
            handle, current_policy, _snapshot, sizes = _evaluate(repository)
            revision = resolve_base_revision(handle, base_commit)
            tree = list_base_tree(handle, revision)
            result = evaluate_file_ratchet(
                current_policy,
                sizes.files,
                evaluation_date=TODAY,
                debt_manifest=manifest,
            )
            status_after = repository.status_bytes()

        self.assertIsNone(find_base_entry(tree, "repo-context.toml"))
        self.assertEqual(status_after, status_before)
        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.files[0].migration_status, MigrationStatus.DEBT)

    def test_clean_base_cannot_gain_its_first_oversized_authored_file(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", _policy_text())
            repository.write_text("small.txt", "small")
            base_commit = repository.commit("clean base")
            repository.write_bytes("new.txt", b"n" * 51)
            handle, current_policy, _snapshot, sizes = _evaluate(repository)
            revision = resolve_base_revision(handle, base_commit)
            tree = list_base_tree(handle, revision)
            result = evaluate_file_ratchet(
                current_policy,
                sizes.files,
                evaluation_date=TODAY,
                base_policy=_base_policy(handle, tree, revision.commit_id),
                base_entries=tree,
                read_base=lambda entry: read_base_blob(handle, entry),
            )

        finding = next(item for item in result.diagnostics if item.location.path == "new.txt")
        self.assertEqual(finding.code, RAT_NEW_OVERSIZE)

    def test_staged_and_unstaged_renames_are_delete_plus_add_even_for_the_same_blob(self) -> None:
        for staged in (False, True):
            with self.subTest(staged=staged), RepositoryFixture() as repository:
                repository.write_text("repo-context.toml", _policy_text())
                repository.write_bytes("old.txt", b"x" * 60)
                base_commit = repository.commit("old path")
                repository.rename("old.txt", "new.txt")
                if staged:
                    repository.git("add", "--all")
                handle, current_policy, _snapshot, sizes = _evaluate(repository)
                revision = resolve_base_revision(handle, base_commit)
                tree = list_base_tree(handle, revision)
                old_entry = find_base_entry(tree, "old.txt")
                result = evaluate_file_ratchet(
                    current_policy,
                    sizes.files,
                    evaluation_date=TODAY,
                    base_policy=_base_policy(handle, tree, revision.commit_id),
                    base_entries=tree,
                    read_base=lambda entry: read_base_blob(handle, entry),
                )

                self.assertIsNotNone(old_entry)
                finding = next(item for item in result.diagnostics if item.location.path == "new.txt")
                self.assertEqual(finding.code, RAT_NEW_OVERSIZE)

    def test_base_directory_replaced_by_oversized_file_is_a_type_change(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", _policy_text())
            repository.write_text("legacy.txt/child.txt", "base child\n")
            base_commit = repository.commit("base directory")
            repository.delete("legacy.txt/child.txt")
            repository.path("legacy.txt").rmdir()
            repository.write_bytes("legacy.txt", b"x" * 60)
            repository.git("add", "--all")
            handle, current_policy, _snapshot, sizes = _evaluate(repository)
            revision = resolve_base_revision(handle, base_commit)
            tree = list_base_tree(handle, revision)
            base_entry = find_base_entry(tree, "legacy.txt")
            result = evaluate_file_ratchet(
                current_policy,
                sizes.files,
                evaluation_date=TODAY,
                base_policy=_base_policy(handle, tree, revision.commit_id),
                base_entries=tree,
                read_base=lambda entry: read_base_blob(handle, entry),
            )

        self.assertIsNotNone(base_entry)
        self.assertEqual(base_entry.mode, GitFileMode.TREE)
        finding = next(item for item in result.diagnostics if item.location.path == "legacy.txt")
        self.assertEqual(finding.code, "RAT005")
        self.assertEqual(dict(finding.details)["base_mode"], "040000")

    def test_missing_or_shallow_unavailable_ref_is_an_operational_git_error(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("repo-context.toml", _policy_text())
            repository.commit("base")
            status_before = repository.status_bytes()
            handle = open_repository(repository.root)
            with self.assertRaises(RepositoryAccessError) as raised:
                resolve_base_revision(handle, "history-not-present")
            status_after = repository.status_bytes()

        self.assertEqual(raised.exception.diagnostics[0].code, GIT_BASE_REVISION)
        self.assertEqual(status_after, status_before)


if __name__ == "__main__":
    unittest.main()
