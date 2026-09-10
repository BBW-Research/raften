from __future__ import annotations

import hashlib
import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from release_tools.artifacts import (
    Artifact,
    stage_release_artifacts,
    verify_artifacts,
    write_checksums,
)
from release_tools.zipapp_builder import build_zipapp
from tests.support.paths import ROOT


class ReleaseArtifactTests(unittest.TestCase):
    def test_verifier_accepts_minimal_safe_release_archives(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self._wheel(output / "raften-1.0.0-py3-none-any.whl")
            self._sdist(output / "raften-1.0.0.tar.gz")
            build_zipapp(ROOT / "src", output / "raften-1.0.0.pyz", epoch=1_788_220_800)

            artifacts = verify_artifacts(
                output,
                expected_name="raften",
                expected_version="1.0.0",
            )
            checksums = write_checksums(output, artifacts)
            checksum_text = checksums.read_text(encoding="ascii")

        self.assertEqual(len(artifacts), 3)
        self.assertEqual(len(checksum_text.splitlines()), 3)
        self.assertEqual(
            {line.split("  ")[1] for line in checksum_text.splitlines()},
            {artifact.path.name for artifact in artifacts},
        )

    def test_checksum_manifest_is_sorted_and_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "z.pyz"
            second = root / "a.whl"
            first.write_bytes(b"z")
            second.write_bytes(b"a")
            artifacts = (
                Artifact(first, hashlib.sha256(b"z").hexdigest()),
                Artifact(second, hashlib.sha256(b"a").hexdigest()),
            )
            manifest = write_checksums(root, artifacts)
            text = manifest.read_text(encoding="ascii")
            with self.assertRaises(FileExistsError):
                write_checksums(root, artifacts)

        self.assertEqual([line.split("  ")[1] for line in text.splitlines()], ["a.whl", "z.pyz"])

    def test_checksum_manifest_preserves_a_destination_created_during_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact_path = root / "artifact.pyz"
            artifact_path.write_bytes(b"artifact")
            artifacts = (Artifact(artifact_path, hashlib.sha256(b"artifact").hexdigest()),)
            destination = root / "SHA256SUMS"
            path_open = Path.open

            def race(path: Path, mode: str = "r", *args, **kwargs):
                if path == destination and mode == "x":
                    with path_open(path, "x", encoding="ascii") as stream:
                        stream.write("concurrent owner data\n")
                return path_open(path, mode, *args, **kwargs)

            with mock.patch.object(Path, "open", autospec=True, side_effect=race):
                with self.assertRaises(FileExistsError):
                    write_checksums(root, artifacts)

            self.assertEqual(destination.read_text(), "concurrent owner data\n")

    def test_verifier_rejects_unsafe_archive_members(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self._wheel(output / "raften-1.0.0-py3-none-any.whl", unsafe=True)
            self._sdist(output / "raften-1.0.0.tar.gz")
            build_zipapp(ROOT / "src", output / "raften-1.0.0.pyz", epoch=1_788_220_800)
            with self.assertRaisesRegex(ValueError, "unsafe archive member"):
                verify_artifacts(
                    output,
                    expected_name="raften",
                    expected_version="1.0.0",
                )

    def test_verifier_rejects_unrelated_artifact_directory_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self._wheel(output / "raften-1.0.0-py3-none-any.whl")
            self._sdist(output / "raften-1.0.0.tar.gz")
            build_zipapp(ROOT / "src", output / "raften-1.0.0.pyz", epoch=1_788_220_800)
            (output / "unreviewed.bin").write_bytes(b"unexpected")
            with self.assertRaisesRegex(ValueError, "unexpected files"):
                verify_artifacts(
                    output,
                    expected_name="raften",
                    expected_version="1.0.0",
                )

    def test_verifier_rejects_a_wheel_without_the_project_license(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self._wheel(
                output / "raften-1.0.0-py3-none-any.whl",
                include_project_license=False,
            )
            self._sdist(output / "raften-1.0.0.tar.gz")
            build_zipapp(ROOT / "src", output / "raften-1.0.0.pyz", epoch=1_788_220_800)
            with self.assertRaisesRegex(ValueError, "missing the project license"):
                verify_artifacts(
                    output,
                    expected_name="raften",
                    expected_version="1.0.0",
                )

    def test_qualification_stages_candidate_bytes_before_using_them(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            originals = {
                "package-1.0.0-py3-none-any.whl": b"wheel",
                "package-1.0.0.tar.gz": b"source",
                "package-1.0.0.pyz": b"zipapp",
                "SHA256SUMS": b"manifest",
            }
            for name, data in originals.items():
                (source / name).write_bytes(data)
            destination = stage_release_artifacts(source, root / "staged")
            for name in originals:
                (source / name).write_bytes(b"replaced")

            self.assertEqual(
                {path.name: path.read_bytes() for path in destination.iterdir()},
                originals,
            )

    def _wheel(
        self,
        path: Path,
        *,
        unsafe: bool = False,
        include_project_license: bool = True,
    ) -> None:
        metadata = """Metadata-Version: 2.4
Name: raften
Version: 1.0.0
Requires-Python: <3.14,>=3.12
License-Expression: MIT
License-File: LICENSE
License-File: NOTICE
Classifier: Operating System :: MacOS
Classifier: Operating System :: POSIX :: Linux
Classifier: Programming Language :: Python :: 3.12
Classifier: Programming Language :: Python :: 3.13
Classifier: Programming Language :: Python :: Implementation :: CPython

fixture
"""
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("raften/__init__.py", "")
            archive.writestr("raften/cli.py", "")
            archive.writestr("raften-1.0.0.dist-info/METADATA", metadata)
            archive.writestr(
                "raften-1.0.0.dist-info/entry_points.txt",
                "[console_scripts]\nraften = raften.cli:main\n",
            )
            archive.writestr(
                "raften-1.0.0.dist-info/WHEEL",
                "Wheel-Version: 1.0\nTag: py3-none-any\n",
            )
            archive.writestr("raften-1.0.0.dist-info/RECORD", "")
            if include_project_license:
                archive.writestr(
                    "raften-1.0.0.dist-info/licenses/LICENSE",
                    "license\n",
                )
            archive.writestr("raften-1.0.0.dist-info/licenses/NOTICE", "notice\n")
            if unsafe:
                archive.writestr("../escape", "x")

    def _sdist(self, path: Path) -> None:
        root = "raften-1.0.0"
        files = {
            f"{root}/CHANGELOG.md": b"# Changelog\n",
            f"{root}/LICENSE": b"license\n",
            f"{root}/README.md": b"# fixture\n",
            f"{root}/NOTICE": b"notice\n",
            f"{root}/pyproject.toml": b"[project]\nname='raften'\n",
            f"{root}/src/raften/__init__.py": b"",
            f"{root}/src/raften/cli.py": b"",
        }
        with tarfile.open(path, "w:gz") as archive:
            for name, data in files.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))


if __name__ == "__main__":
    unittest.main()
