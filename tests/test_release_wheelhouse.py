from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from release_tools.wheelhouse import (
    WheelhouseError,
    stage_locked_wheelhouse,
    verify_locked_wheelhouse,
)


class LockedWheelhouseTests(unittest.TestCase):
    def test_exact_hash_locked_wheels_are_staged_from_verified_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            wheels = {
                "build-1.5.0-py3-none-any.whl": b"reviewed build wheel",
                "pyproject_hooks-1.2.0-py3-none-any.whl": b"reviewed hooks wheel",
            }
            requirements = self._write_fixture(source, root / "release.txt", wheels)
            destination = root / "staged"

            staged = stage_locked_wheelhouse(source, requirements, destination)

            self.assertEqual(tuple(item.filename for item in staged), tuple(sorted(wheels)))
            self.assertEqual(
                {path.name: path.read_bytes() for path in destination.iterdir()},
                wheels,
            )

    def test_tampered_or_additional_wheels_are_rejected_before_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            filename = "setuptools-84.0.0-py3-none-any.whl"
            requirements = self._write_fixture(
                source,
                root / "release.txt",
                {filename: b"reviewed setuptools wheel"},
            )
            (source / filename).write_bytes(b"tampered")
            with self.assertRaisesRegex(WheelhouseError, "hash mismatch"):
                verify_locked_wheelhouse(source, requirements)

            (source / filename).write_bytes(b"reviewed setuptools wheel")
            (source / "setuptools-84.0.0-1-py3-none-any.whl").write_bytes(b"extra")
            with self.assertRaisesRegex(WheelhouseError, "do not exactly match"):
                verify_locked_wheelhouse(source, requirements)

    def test_lock_grammar_and_destination_ownership_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            requirements = root / "release.txt"
            requirements.write_text("build>=1.5 --hash=sha256:" + "0" * 64 + "\n")
            with self.assertRaisesRegex(WheelhouseError, "unsupported release lock line"):
                verify_locked_wheelhouse(source, requirements)

            wheels = {"build-1.5.0-py3-none-any.whl": b"reviewed build wheel"}
            requirements = self._write_fixture(source, requirements, wheels)
            destination = root / "staged"
            destination.mkdir()
            with self.assertRaisesRegex(WheelhouseError, "already exists"):
                stage_locked_wheelhouse(source, requirements, destination)

    def _write_fixture(
        self,
        source: Path,
        requirements: Path,
        wheels: dict[str, bytes],
    ) -> Path:
        lines = ["# fixture lock"]
        for filename, data in sorted(wheels.items()):
            (source / filename).write_bytes(data)
            stem = filename.removesuffix("-py3-none-any.whl")
            name, separator, version = stem.rpartition("-")
            self.assertEqual(separator, "-")
            lines.append(
                f"{name.replace('_', '-')}=={version} "
                f"--hash=sha256:{hashlib.sha256(data).hexdigest()}"
            )
        requirements.write_text("\n".join(lines) + "\n", encoding="ascii")
        return requirements


if __name__ == "__main__":
    unittest.main()
