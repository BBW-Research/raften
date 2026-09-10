from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.support.paths import ROOT
from tests.support.repository import isolated_environment


CHILD_MARKER = "RAFTEN_ARCHIVE_BOOTSTRAP_CHILD"


class ArchiveBootstrapTests(unittest.TestCase):
    def test_fresh_unpacked_archive_validates_offline(self) -> None:
        if os.environ.get(CHILD_MARKER) == "1":
            self.skipTest("nested bootstrap recursion is disabled")

        with tempfile.TemporaryDirectory(prefix="raften-bootstrap-") as temporary:
            subprocess.run(
                ["git", "-C", temporary, "init", "--quiet"],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                env=isolated_environment(),
                timeout=30,
            )
            archive = Path(temporary) / "raften archive"
            shutil.copytree(
                ROOT,
                archive,
                ignore=shutil.ignore_patterns(
                    ".git",
                    "__pycache__",
                    "*.pyc",
                    ".DS_Store",
                ),
            )
            environment = isolated_environment(
                **{
                    CHILD_MARKER: "1",
                    "ALL_PROXY": "http://127.0.0.1:9",
                    "HTTP_PROXY": "http://127.0.0.1:9",
                    "HTTPS_PROXY": "http://127.0.0.1:9",
                    "NO_PROXY": "",
                    "PYTHONPATH": "/nonexistent/ambient-pythonpath",
                    "all_proxy": "http://127.0.0.1:9",
                    "http_proxy": "http://127.0.0.1:9",
                    "https_proxy": "http://127.0.0.1:9",
                    "no_proxy": "",
                }
            )
            environment.pop("BASE_REF", None)
            result = subprocess.run(
                [str(archive / "scripts/bootstrap")],
                cwd=Path(temporary),
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=120,
            )
            top_level = subprocess.run(
                ["git", "-C", archive, "rev-parse", "--show-toplevel"],
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=30,
            ).stdout.strip()
            nested_repository_is_root = Path(top_level).resolve() == archive.resolve()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(nested_repository_is_root)
        self.assertIn("Summary: 0 errors", result.stdout)
        self.assertIn("OK", result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
