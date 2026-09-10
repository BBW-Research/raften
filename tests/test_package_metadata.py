from __future__ import annotations

import tomllib
import unittest

from raften import __version__
from tests.support.paths import ROOT


class PackageMetadataTests(unittest.TestCase):
    def test_metadata_uses_raften_for_distribution_cli_and_import(self) -> None:
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(project["name"], "raften")
        self.assertEqual(project["dynamic"], ["version"])
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertEqual(metadata["project"]["scripts"], {"raften": "raften.cli:main"})
        self.assertEqual(metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"], "raften.__version__")
        self.assertEqual(__version__, "1.0.0")

    def test_metadata_uses_the_canonical_repository_identity(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.assertEqual(
            project["urls"],
            {
                "Homepage": "https://github.com/BBW-Research/raften",
                "Issues": "https://github.com/BBW-Research/raften/issues",
                "Repository": "https://github.com/BBW-Research/raften",
            },
        )

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
