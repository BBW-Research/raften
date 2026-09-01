from __future__ import annotations

import copy
import json
import subprocess
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.support.repository import (
    RepositoryFixture,
    isolated_process_environment,
    seed_policy,
)
from tests.support.seed import SEED


def ratchet_policy() -> dict[str, object]:
    return seed_policy(
        max_text_bytes=100,
        index_max_bytes=40,
        entrypoint_limits={"README.md": 60},
        documentation_roots=["docs", "reference"],
        documentation_excluded_globs=["docs/vendor/**"],
        text_excluded_globs=["vendor/**"],
        required_entrypoint_links={
            "README.md": ["docs/index.md", "ARCHITECTURE.md"],
        },
        legacy_oversize={"legacy.txt": 200},
    )


class SeedBasePolicyLoadingTests(unittest.TestCase):
    def test_policy_is_loaded_from_committed_base_without_changing_worktree(self) -> None:
        old_policy = seed_policy(max_text_bytes=100)
        new_policy = seed_policy(max_text_bytes=90)
        with RepositoryFixture() as repository:
            repository.write_seed_policy(old_policy)
            base = repository.commit("base policy")
            repository.write_seed_policy(new_policy)
            before = repository.git("status", "--short").stdout
            with isolated_process_environment():
                loaded = SEED.policy_from_git(
                    repository.root,
                    base,
                    "config/repository_policy.v1.json",
                )
            after = repository.git("status", "--short").stdout
        self.assertEqual(loaded, old_policy)
        self.assertEqual(after, before)

    def test_missing_ref_or_policy_returns_none(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("README.md", "fixture\n")
            base = repository.commit("base")
            with isolated_process_environment():
                self.assertIsNone(
                    SEED.policy_from_git(
                        repository.root,
                        "missing-ref",
                        "config/repository_policy.v1.json",
                    )
                )
                self.assertIsNone(
                    SEED.policy_from_git(repository.root, base, "missing-policy.json")
                )

    def test_invalid_base_policy_raises_policy_error(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_bytes("config/repository_policy.v1.json", b"{")
            base = repository.commit("invalid policy")
            with isolated_process_environment():
                with self.assertRaisesRegex(SEED.PolicyError, "invalid policy JSON"):
                    SEED.policy_from_git(
                        repository.root,
                        base,
                        "config/repository_policy.v1.json",
                    )

    def test_base_policy_git_invocation_uses_argument_vector(self) -> None:
        policy_bytes = json.dumps(seed_policy()).encode("utf-8")
        completed = SimpleNamespace(returncode=0, stdout=policy_bytes, stderr=b"")
        root = Path("/fixture")
        with mock.patch.object(SEED.subprocess, "run", return_value=completed) as run:
            loaded = SEED.policy_from_git(root, "base", "config/policy.json")
        self.assertEqual(loaded, seed_policy())
        run.assert_called_once_with(
            ["git", "show", "base:config/policy.json"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


class SeedPolicyRatchetTests(unittest.TestCase):
    def test_global_and_entrypoint_limit_weakening_is_rejected(self) -> None:
        base = ratchet_policy()
        current = copy.deepcopy(base)
        current["max_text_bytes"] = 101
        current["index_max_bytes"] = 41
        current["entrypoint_limits"] = {}
        self.assertEqual(
            SEED.check_not_weakened(current, base),
            [
                "max_text_bytes may not increase",
                "index_max_bytes may not increase",
                "entrypoint limit may not be removed: README.md",
            ],
        )

        current = copy.deepcopy(base)
        current["entrypoint_limits"]["README.md"] = 61
        self.assertEqual(
            SEED.check_not_weakened(current, base),
            ["entrypoint limit may not increase: README.md"],
        )

    def test_documentation_roots_and_exclusions_may_not_weaken(self) -> None:
        base = ratchet_policy()
        current = copy.deepcopy(base)
        current["documentation_roots"].remove("reference")
        current["documentation_excluded_globs"].append("docs/generated/**")
        current["text_excluded_globs"].append("generated/**")
        self.assertEqual(
            SEED.check_not_weakened(current, base),
            [
                "documentation roots may not be removed",
                "documentation_excluded_globs may not expand: ['docs/generated/**']",
                "text_excluded_globs may not expand: ['generated/**']",
            ],
        )

    def test_required_entrypoint_targets_may_not_be_removed(self) -> None:
        base = ratchet_policy()
        current = copy.deepcopy(base)
        current["required_entrypoint_links"]["README.md"] = ["docs/index.md"]
        self.assertEqual(
            SEED.check_not_weakened(current, base),
            ["required entrypoint links may not be removed: README.md"],
        )

        current = copy.deepcopy(base)
        del current["required_entrypoint_links"]["README.md"]
        self.assertEqual(
            SEED.check_not_weakened(current, base),
            ["required entrypoint links may not be removed: README.md"],
        )

    def test_legacy_entries_may_not_be_added_or_increased(self) -> None:
        base = ratchet_policy()
        current = copy.deepcopy(base)
        current["legacy_oversize"]["new.txt"] = 300
        current["legacy_oversize"]["legacy.txt"] = 201
        self.assertEqual(
            SEED.check_not_weakened(current, base),
            [
                "new legacy oversized files are forbidden: ['new.txt']",
                "legacy ceiling may not increase: legacy.txt",
            ],
        )

    def test_tightening_and_additive_requirements_are_allowed(self) -> None:
        base = ratchet_policy()
        current = copy.deepcopy(base)
        current["max_text_bytes"] = 99
        current["index_max_bytes"] = 39
        current["entrypoint_limits"]["README.md"] = 59
        current["entrypoint_limits"]["AGENTS.md"] = 50
        current["documentation_roots"].append("guides")
        current["documentation_excluded_globs"].clear()
        current["text_excluded_globs"].clear()
        current["required_entrypoint_links"]["README.md"].append("AGENTS.md")
        current["required_entrypoint_links"]["AGENTS.md"] = ["docs/index.md"]
        current["legacy_oversize"]["legacy.txt"] = 199
        self.assertEqual(SEED.check_not_weakened(current, base), [])

    def test_seed_hardcodes_structured_data_exclusion_additions_as_allowed(self) -> None:
        base = ratchet_policy()
        current = copy.deepcopy(base)
        current["text_excluded_globs"].extend(
            ["config/*.json", "schemas/*.json"],
        )
        self.assertEqual(SEED.check_not_weakened(current, base), [])

    def test_multiple_findings_have_stable_category_and_path_order(self) -> None:
        base = ratchet_policy()
        base["entrypoint_limits"] = {"Z.md": 20, "A.md": 10}
        current = copy.deepcopy(base)
        current["max_text_bytes"] = 101
        current["index_max_bytes"] = 41
        current["entrypoint_limits"] = {}
        current["documentation_roots"] = ["docs"]
        current["documentation_excluded_globs"].extend(["z/**", "a/**"])
        current["text_excluded_globs"].extend(["z/**", "a/**"])
        current["required_entrypoint_links"] = {}
        current["legacy_oversize"]["z.txt"] = 300
        current["legacy_oversize"]["a.txt"] = 300
        current["legacy_oversize"]["legacy.txt"] = 201
        expected = [
            "max_text_bytes may not increase",
            "index_max_bytes may not increase",
            "entrypoint limit may not be removed: Z.md",
            "entrypoint limit may not be removed: A.md",
            "documentation roots may not be removed",
            "documentation_excluded_globs may not expand: ['a/**', 'z/**']",
            "text_excluded_globs may not expand: ['a/**', 'z/**']",
            "required entrypoint links may not be removed: README.md",
            "new legacy oversized files are forbidden: ['a.txt', 'z.txt']",
            "legacy ceiling may not increase: legacy.txt",
        ]
        self.assertEqual(SEED.check_not_weakened(current, base), expected)
        self.assertEqual(SEED.check_not_weakened(current, base), expected)


if __name__ == "__main__":
    unittest.main()
