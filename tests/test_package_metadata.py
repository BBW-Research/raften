from __future__ import annotations

import tomllib
import unittest

from repo_context import __version__
from tests.support.paths import ROOT


class PackageMetadataTests(unittest.TestCase):
    def test_metadata_preserves_distinct_distribution_cli_and_import_names(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["name"], "repo-context-policy")
        self.assertEqual(project["dynamic"], ["version"])
        self.assertEqual(metadata["project"]["scripts"], {"repo-context": "repo_context.cli:main"})
        self.assertEqual(metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"], "repo_context.__version__")
        self.assertEqual(__version__, "1.0.0")

    def test_metadata_declares_the_exact_runtime_support_contract(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        classifiers = set(project["classifiers"])
        self.assertEqual(project["requires-python"], ">=3.12,<3.14")
        self.assertEqual(project["dependencies"], [])
        self.assertIn("Programming Language :: Python :: 3.12", classifiers)
        self.assertIn("Programming Language :: Python :: 3.13", classifiers)
        self.assertIn("Operating System :: MacOS", classifiers)
        self.assertIn("Operating System :: POSIX :: Linux", classifiers)
        self.assertIn("Programming Language :: Python :: Implementation :: CPython", classifiers)
        self.assertFalse(any("Windows" in item for item in classifiers))


if __name__ == "__main__":
    unittest.main()
