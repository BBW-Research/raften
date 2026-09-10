from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from release_tools.smoke import smoke
from release_tools.zipapp_builder import build_zipapp
from raften import __version__
from tests.support.paths import ROOT


EPOCH = 1_788_220_800


class ReleaseZipappTests(unittest.TestCase):
    def test_builder_is_byte_deterministic_and_normalizes_every_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.pyz"
            second = Path(directory) / "second.pyz"
            names = build_zipapp(ROOT / "src", first, epoch=EPOCH)
            self.assertEqual(names, build_zipapp(ROOT / "src", second, epoch=EPOCH))
            first_bytes = first.read_bytes()
            second_bytes = second.read_bytes()

            self.assertEqual(hashlib.sha256(first_bytes).digest(), hashlib.sha256(second_bytes).digest())
            self.assertTrue(first_bytes.startswith(b"#!/usr/bin/env python3\n"))
            self.assertTrue(first.stat().st_mode & 0o111)
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(tuple(archive.namelist()), names)
                self.assertIn("__main__.py", names)
                self.assertIn("LICENSE", names)
                self.assertIn("NOTICE", names)
                self.assertIn("raften/cli.py", names)
                self.assertEqual(archive.read("LICENSE"), (ROOT / "LICENSE").read_bytes())
                self.assertEqual(archive.read("NOTICE"), (ROOT / "NOTICE").read_bytes())
                self.assertFalse(any("__pycache__" in name for name in names))
                timestamps = {entry.date_time for entry in archive.infolist()}
                self.assertEqual(timestamps, {(2026, 9, 1, 0, 0, 0)})
                self.assertTrue(all(entry.compress_type == zipfile.ZIP_STORED for entry in archive.infolist()))

    def test_zipapp_runs_all_public_commands_without_installation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "raften.pyz"
            build_zipapp(ROOT / "src", artifact, epoch=EPOCH)
            smoke((sys.executable, str(artifact)), expected_version=__version__)

    def test_builder_refuses_invalid_sources_existing_outputs_and_invalid_epochs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "artifact.pyz"
            with self.assertRaisesRegex(ValueError, "does not contain raften"):
                build_zipapp(root, output, epoch=EPOCH)
            source = root / "source" / "src"
            package = source / "raften"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            (source.parent / "NOTICE").write_text("notice\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "regular LICENSE"):
                build_zipapp(source, output, epoch=EPOCH)
            output.write_bytes(b"owned")
            with self.assertRaises(FileExistsError):
                build_zipapp(ROOT / "src", output, epoch=EPOCH)
            output.unlink()
            with self.assertRaisesRegex(ValueError, "representable"):
                build_zipapp(ROOT / "src", output, epoch=0)

    def test_builder_does_not_replace_a_destination_created_during_the_build(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "artifact.pyz"
            link = os.link

            def race(temporary: Path, destination: Path) -> None:
                destination.write_bytes(b"concurrent owner data")
                link(temporary, destination)

            with mock.patch.object(os, "link", side_effect=race), self.assertRaises(FileExistsError):
                build_zipapp(ROOT / "src", output, epoch=EPOCH)

            self.assertEqual(output.read_bytes(), b"concurrent owner data")

    def test_zipapp_version_uses_the_authoritative_package_constant(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "raften.pyz"
            build_zipapp(ROOT / "src", artifact, epoch=EPOCH)
            result = subprocess.run(
                [sys.executable, str(artifact), "--version"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"raften {__version__}\n")


if __name__ == "__main__":
    unittest.main()
