from __future__ import annotations

import ast
import unittest
from pathlib import Path

from repo_context import inventory
from tests.support.seed import ROOT


PACKAGE = ROOT / "src/repo_context"


class PhaseTwoArchitectureBoundaryTests(unittest.TestCase):
    def test_inventory_facade_preserves_the_phase_two_public_api(self) -> None:
        self.assertEqual(
            inventory.__all__,
            (
                "InventorySnapshot",
                "RepositoryAccessError",
                "RepositoryHandle",
                "decode_git_path",
                "find_base_entry",
                "inventory_worktree",
                "inspect_repository_path",
                "list_base_tree",
                "open_repository",
                "read_base_blob",
                "read_worktree_bytes",
                "repository_is_clean",
                "resolve_base_revision",
                "validate_git_repository_path",
                "worktree_path",
            ),
        )
        for name in inventory.__all__:
            self.assertTrue(hasattr(inventory, name), name)

    def test_only_inventory_imports_or_calls_subprocess(self) -> None:
        offenders: list[str] = []
        for source_path in sorted(PACKAGE.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), source_path.name)
            for node in ast.walk(tree):
                is_import = isinstance(node, ast.Import) and any(
                    alias.name == "subprocess" for alias in node.names
                )
                is_from_import = (
                    isinstance(node, ast.ImportFrom) and node.module == "subprocess"
                )
                if (is_import or is_from_import) and source_path.name != "inventory.py":
                    offenders.append(source_path.name)
        self.assertEqual(offenders, [])

    def test_inventory_helpers_do_not_import_the_inventory_facade(self) -> None:
        helper_names = (
            "git_executable.py",
            "git_records.py",
            "repository_errors.py",
            "worktree.py",
        )
        offenders: list[str] = []
        for name in helper_names:
            source_path = PACKAGE / name
            tree = ast.parse(source_path.read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                imported_inventory = (
                    isinstance(node, ast.Import)
                    and any(
                        alias.name == "repo_context.inventory"
                        for alias in node.names
                    )
                ) or (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "repo_context.inventory"
                )
                if imported_inventory:
                    offenders.append(name)
        self.assertEqual(offenders, [])

    def test_policy_glob_interpretation_is_confined_to_matcher(self) -> None:
        offenders: list[str] = []
        for source_path in sorted(PACKAGE.glob("*.py")):
            if source_path.name == "matcher.py":
                continue
            tree = ast.parse(source_path.read_text(encoding="utf-8"), source_path.name)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    imported = (
                        [alias.name for alias in node.names]
                        if isinstance(node, ast.Import)
                        else [node.module or ""]
                    )
                    if any(name in {"fnmatch", "glob"} for name in imported):
                        offenders.append(source_path.name)
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"glob", "rglob"}
                ):
                    offenders.append(source_path.name)
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "match"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "Path"
                ):
                    offenders.append(source_path.name)
        self.assertEqual(offenders, [])

    def test_size_policy_and_budget_evaluation_have_no_repository_io_dependency(self) -> None:
        forbidden_modules = {
            "os",
            "pathlib",
            "subprocess",
            "repo_context.inventory",
            "repo_context.worktree",
        }
        offenders: list[tuple[str, str]] = []
        for name in ("size_policy.py", "sizes.py"):
            source_path = PACKAGE / name
            tree = ast.parse(source_path.read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                offenders.extend(
                    (name, module)
                    for module in imported
                    if module in forbidden_modules
                )
        self.assertEqual(offenders, [])

    def test_ratchet_and_debt_modules_have_no_repository_io_dependency(self) -> None:
        forbidden_modules = {
            "os",
            "pathlib",
            "subprocess",
            "repo_context.inventory",
            "repo_context.worktree",
        }
        offenders: list[tuple[str, str]] = []
        for name in (
            "debt.py",
            "policy_comparison.py",
            "policy_domains.py",
            "policy_ratchet.py",
            "ratchet.py",
        ):
            source_path = PACKAGE / name
            tree = ast.parse(source_path.read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                offenders.extend(
                    (name, module)
                    for module in imported
                    if module in forbidden_modules
                )
        self.assertEqual(offenders, [])

    def test_markdown_and_documentation_graph_have_no_repository_io_dependency(self) -> None:
        forbidden_modules = {
            "os",
            "pathlib",
            "subprocess",
            "repo_context.inventory",
            "repo_context.worktree",
        }
        offenders: list[tuple[str, str]] = []
        for name in (
            "markdown.py",
            "markdown_lines.py",
            "markdown_links.py",
            "docs.py",
            "document_checks.py",
        ):
            source_path = PACKAGE / name
            tree = ast.parse(source_path.read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                offenders.extend(
                    (name, module)
                    for module in imported
                    if module in forbidden_modules
                )
        self.assertEqual(offenders, [])

    def test_runner_and_initialization_do_not_depend_on_presentation(self) -> None:
        forbidden_modules = {
            "repo_context.cli",
            "repo_context.report",
            "repo_context.report_common",
            "repo_context.report_data",
            "repo_context.report_emergency",
            "repo_context.report_json",
            "repo_context.report_sarif",
            "repo_context.report_text",
        }
        offenders: list[tuple[str, str]] = []
        for name in (
            "runner.py",
            "initialization.py",
            "init_recovery.py",
            "init_safety.py",
            "init_transaction.py",
        ):
            source_path = PACKAGE / name
            tree = ast.parse(source_path.read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                offenders.extend(
                    (name, module)
                    for module in imported
                    if module in forbidden_modules
                )
        self.assertEqual(offenders, [])

    def test_report_modules_are_pure_projections_without_repository_access(self) -> None:
        forbidden_modules = {
            "os",
            "pathlib",
            "subprocess",
            "repo_context.cli",
            "repo_context.initialization",
            "repo_context.inventory",
            "repo_context.runner",
            "repo_context.worktree",
        }
        offenders: list[tuple[str, str]] = []
        for name in (
            "report.py",
            "report_common.py",
            "report_data.py",
            "report_emergency.py",
            "report_json.py",
            "report_sarif.py",
            "report_text.py",
        ):
            source_path = PACKAGE / name
            tree = ast.parse(source_path.read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                offenders.extend(
                    (name, module)
                    for module in imported
                    if module in forbidden_modules
                )
        self.assertEqual(offenders, [])

    def test_output_format_modules_do_not_depend_on_each_other(self) -> None:
        modules = {
            "report_json.py": "repo_context.report_json",
            "report_sarif.py": "repo_context.report_sarif",
            "report_text.py": "repo_context.report_text",
        }
        offenders: list[tuple[str, str]] = []
        for name, own_module in modules.items():
            tree = ast.parse((PACKAGE / name).read_text(encoding="utf-8"), name)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = tuple(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imported = (node.module or "",)
                else:
                    continue
                offenders.extend(
                    (name, module)
                    for module in imported
                    if module in modules.values() and module != own_module
                )
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
