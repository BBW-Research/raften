from __future__ import annotations

import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

from repo_context.model import FileKind, LimitState, RatchetBaselineSource, Severity
from repo_context.run_model import RepositoryRun, RunStatus
from repo_context.runner import run_repository
from tests.support.paths import ROOT, SEED_PATH
from tests.support.repository import RepositoryFixture, isolated_environment
from tests.support.target import install_clean_target


EVALUATION_DATE = date(2026, 9, 2)
SEED_POLICY = ROOT / "tests/fixtures/seed/clean-policy.json"


def _root_has_head() -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=ROOT,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=isolated_environment(),
        timeout=30,
    )
    return result.returncode == 0


def _run(arguments: list[str], *, cwd: Path):
    return subprocess.run(
        arguments,
        cwd=cwd,
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=isolated_environment(PYTHONPATH="/nonexistent/ambient-pythonpath"),
        timeout=30,
    )


class RepositorySelfHostingTests(unittest.TestCase):
    def test_root_policy_explicitly_classifies_scanned_vendor_and_fixture_paths(self) -> None:
        outcome = run_repository(ROOT, evaluation_date=EVALUATION_DATE)

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        assessments = {item.entry.path: item for item in outcome.sizes.files}
        expected = {
            "tools/check_repository_policy.py": ("frozen-scene-maker", FileKind.VENDORED),
            "reference/scene-maker/repository-policy.yml": (
                "frozen-scene-maker",
                FileKind.VENDORED,
            ),
            "reference/scene-maker/lychee.toml": (
                "frozen-scene-maker",
                FileKind.VENDORED,
            ),
            "tests/fixtures/output/check-clean.txt": ("test-fixtures", FileKind.FIXTURE),
            "tests/fixtures/seed/clean-policy.json": ("test-fixtures", FileKind.FIXTURE),
        }
        for path, (rule_name, kind) in expected.items():
            with self.subTest(path=path):
                policy = assessments[path].policy
                self.assertIsNotNone(policy)
                assert policy is not None
                self.assertEqual(policy.rule_match.rule.name, rule_name)
                self.assertEqual(policy.kind, kind)
                self.assertTrue(policy.ordinary_scan)
                self.assertTrue(policy.effective_scan)
                self.assertEqual(policy.ordinary_warn_bytes, 20480)
                self.assertEqual(policy.ordinary_hard_bytes, 25600)

    def test_root_policy_covers_budgets_graph_context_and_ratchet(self) -> None:
        has_head = _root_has_head()
        outcome = run_repository(
            ROOT,
            base_ref="HEAD" if has_head else None,
            evaluation_date=EVALUATION_DATE,
        )

        self.assertIsInstance(outcome, RepositoryRun)
        assert isinstance(outcome, RepositoryRun)
        self.assertEqual(outcome.status, RunStatus.COMPLETE)
        self.assertEqual(
            tuple(item for item in outcome.diagnostics if item.severity is Severity.ERROR),
            (),
        )
        self.assertFalse(
            any(item.limit_state is LimitState.HARD for item in outcome.sizes.files)
        )
        self.assertEqual(outcome.documentation.diagnostics, ())
        self.assertEqual(outcome.documentation.unreachable_paths, ())

        bootstrap = next(item for item in outcome.sizes.contexts if item.name == "bootstrap")
        self.assertEqual(bootstrap.missing_exact_paths, ())
        self.assertIsNot(bootstrap.limit_state, LimitState.HARD)
        self.assertLessEqual(bootstrap.total_bytes, bootstrap.hard_bytes)

        if has_head:
            self.assertEqual(outcome.ratchet.baseline_source, RatchetBaselineSource.GIT)
            self.assertIsNotNone(outcome.base_commit_id)
            self.assertFalse(
                any(item.code.startswith("RAT") for item in outcome.diagnostics)
            )
        else:
            self.assertEqual(
                outcome.ratchet.baseline_source,
                RatchetBaselineSource.UNAVAILABLE,
            )
            self.assertEqual(
                tuple(item.code for item in outcome.diagnostics if item.code.startswith("RAT")),
                ("RAT001",),
            )

    def test_seed_and_target_both_accept_the_repository(self) -> None:
        base_arguments = ["--base-ref", "HEAD"] if _root_has_head() else []
        seed = _run(
            [
                "python3",
                str(SEED_PATH),
                "--config",
                SEED_POLICY.relative_to(ROOT).as_posix(),
                *base_arguments,
            ],
            cwd=ROOT,
        )
        target = _run(
            [
                str(ROOT / "scripts/context-check"),
                *base_arguments,
                "--evaluation-date",
                EVALUATION_DATE.isoformat(),
            ],
            cwd=ROOT,
        )

        self.assertEqual(seed.returncode, 0, seed.stderr)
        self.assertIn("repository policy passed", seed.stdout)
        self.assertEqual(target.returncode, 0, target.stderr)
        self.assertIn("Summary: 0 errors", target.stdout)

    def test_wrapper_uses_source_tree_from_an_unrelated_directory(self) -> None:
        with RepositoryFixture() as repository, tempfile.TemporaryDirectory() as outside:
            install_clean_target(repository)
            repository.commit("clean target")
            shadow = Path(outside) / "repo_context"
            shadow.mkdir()
            (shadow / "__init__.py").write_text("", encoding="utf-8")
            (shadow / "__main__.py").write_text(
                'print("SHADOW_PACKAGE_EXECUTED")\n',
                encoding="utf-8",
            )
            result = _run(
                [
                    str(ROOT / "scripts/context-check"),
                    "--repo",
                    str(repository.root),
                    "--base-ref",
                    "HEAD",
                    "--evaluation-date",
                    EVALUATION_DATE.isoformat(),
                ],
                cwd=Path(outside),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Summary: 0 errors", result.stdout)
        self.assertNotIn("SHADOW_PACKAGE_EXECUTED", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_normal_policy_entrypoints_do_not_select_the_seed_checker(self) -> None:
        normal_paths = (
            ROOT / "scripts/context-check",
            ROOT / "scripts/validate",
            ROOT / "scripts/bootstrap",
            ROOT / ".github/workflows/repository-policy.yml",
        )
        for path in normal_paths:
            with self.subTest(path=path.relative_to(ROOT)):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("check_repository_policy.py", text)

        wrapper = (ROOT / "scripts/context-check").read_text(encoding="utf-8")
        self.assertIn("python3 -P -m repo_context check", wrapper)
        self.assertIn('--repo "$ROOT"', wrapper)
        self.assertIn('PYTHONPATH="$ROOT/src"', wrapper)
        self.assertNotIn("${PYTHONPATH", wrapper)
        validation = (ROOT / "scripts/validate").read_text(encoding="utf-8")
        self.assertIn("compileall -q src tests", validation)
        self.assertNotIn("compileall -q src tests tools", validation)
        workflow = (ROOT / ".github/workflows/repository-policy.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("BASE_REF:", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("run: scripts/validate", workflow)

    def test_toml_is_authoritative_and_seed_json_is_fixture_scoped(self) -> None:
        self.assertTrue((ROOT / "repo-context.toml").is_file())
        self.assertFalse((ROOT / "config/repository_policy.v1.json").exists())
        self.assertTrue(SEED_POLICY.is_file())


if __name__ == "__main__":
    unittest.main()
