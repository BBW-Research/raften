from __future__ import annotations

import ast
import unittest
from pathlib import Path

from tests.support.seed import ROOT


PACKAGE = ROOT / "src/repo_context"


class PhaseTwoArchitectureBoundaryTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
