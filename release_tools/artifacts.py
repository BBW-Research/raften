"""Validate release archives and emit their deterministic checksum manifest."""

from __future__ import annotations

import argparse
import email.parser
import hashlib
import re
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, slots=True)
class Artifact:
    path: Path
    sha256: str


def verify_artifacts(directory: Path, *, expected_name: str, expected_version: str) -> tuple[Artifact, ...]:
    """Verify one wheel, one source archive, and one dependency-free zipapp."""

    wheel, source_archive, zipapp, _manifest = _select_release_files(directory)

    _verify_wheel(wheel, expected_name, expected_version)
    _verify_sdist(source_archive, expected_name, expected_version)
    _verify_zipapp(zipapp)
    return tuple(
        Artifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (source_archive, wheel, zipapp)
    )


def stage_release_artifacts(source: Path, destination: Path) -> Path:
    """Copy the exact candidate set once before validating or executing it."""

    wheel, source_archive, zipapp, manifest = _select_release_files(
        source,
        require_manifest=True,
    )
    assert manifest is not None
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"staged artifact destination already exists: {destination}")
    destination.mkdir(mode=0o700)
    for path in sorted((wheel, source_archive, zipapp, manifest), key=lambda item: item.name):
        data = path.read_bytes()
        with (destination / path.name).open("xb") as stream:
            stream.write(data)
    return destination


def write_checksums(directory: Path, artifacts: tuple[Artifact, ...]) -> Path:
    destination = directory / "SHA256SUMS"
    lines = tuple(
        f"{artifact.sha256}  {artifact.path.name}\n"
        for artifact in sorted(artifacts, key=lambda item: item.path.name)
    )
    with destination.open("x", encoding="ascii", newline="\n") as stream:
        stream.write("".join(lines))
    return destination


def _verify_wheel(path: Path, expected_name: str, expected_version: str) -> None:
    with zipfile.ZipFile(path) as archive:
        names = tuple(archive.namelist())
        _verify_member_names(names)
        metadata_names = tuple(name for name in names if name.endswith(".dist-info/METADATA"))
        entrypoint_names = tuple(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        wheel_names = tuple(name for name in names if name.endswith(".dist-info/WHEEL"))
        record_names = tuple(name for name in names if name.endswith(".dist-info/RECORD"))
        if tuple(map(len, (metadata_names, entrypoint_names, wheel_names, record_names))) != (
            1,
            1,
            1,
            1,
        ):
            raise ValueError("wheel must contain one METADATA, entry_points.txt, WHEEL, and RECORD")
        metadata = email.parser.BytesParser().parsebytes(archive.read(metadata_names[0]))
        if _canonical_name(metadata["Name"] or "") != _canonical_name(expected_name):
            raise ValueError("wheel project name does not match release metadata")
        if metadata["Version"] != expected_version:
            raise ValueError("wheel version does not match release metadata")
        if metadata["License-Expression"] != "MIT":
            raise ValueError("wheel must declare the MIT license expression")
        if tuple(metadata.get_all("License-File") or ()) != ("LICENSE", "NOTICE"):
            raise ValueError("wheel must declare exactly LICENSE and NOTICE")
        python_specifiers = tuple(
            item.strip()
            for item in (metadata["Requires-Python"] or "").split(",")
        )
        if len(python_specifiers) != 2 or frozenset(python_specifiers) != {">=3.12", "<3.14"}:
            raise ValueError("wheel must require exactly supported Python 3.12 and 3.13")
        if metadata.get_all("Requires-Dist"):
            raise ValueError("wheel must not declare runtime dependencies")
        classifiers = frozenset(metadata.get_all("Classifier") or ())
        required_classifiers = {
            "Operating System :: MacOS",
            "Operating System :: POSIX :: Linux",
            "Programming Language :: Python :: 3.12",
            "Programming Language :: Python :: 3.13",
            "Programming Language :: Python :: Implementation :: CPython",
        }
        if not required_classifiers.issubset(classifiers):
            raise ValueError("wheel metadata is missing supported-platform classifiers")
        if any("Windows" in classifier for classifier in classifiers):
            raise ValueError("wheel metadata may not claim Windows support")
        entrypoints = archive.read(entrypoint_names[0]).decode("utf-8")
        if "raften = raften.cli:main" not in entrypoints:
            raise ValueError("wheel does not expose the raften command")
        required = {"raften/__init__.py", "raften/cli.py"}
        if not required.issubset(names):
            raise ValueError("wheel is missing required package modules")
        if not any(name.endswith(".dist-info/licenses/LICENSE") for name in names):
            raise ValueError("wheel is missing the project license")
        if not any(name.endswith(".dist-info/licenses/NOTICE") for name in names):
            raise ValueError("wheel is missing the upstream license notice")


def _verify_sdist(path: Path, expected_name: str, expected_version: str) -> None:
    with tarfile.open(path, "r:gz") as archive:
        members = archive.getmembers()
        names = tuple(member.name for member in members)
        _verify_member_names(names)
        roots = {PurePosixPath(name).parts[0] for name in names if PurePosixPath(name).parts}
        if len(roots) != 1:
            raise ValueError("sdist must contain one top-level directory")
        root = next(iter(roots))
        expected_root = f"{_canonical_name(expected_name).replace('-', '_')}-{expected_version}"
        if _canonical_name(root) != _canonical_name(expected_root):
            raise ValueError("sdist root does not match release metadata")
        required = {
            f"{root}/CHANGELOG.md",
            f"{root}/LICENSE",
            f"{root}/README.md",
            f"{root}/NOTICE",
            f"{root}/pyproject.toml",
            f"{root}/src/raften/__init__.py",
            f"{root}/src/raften/cli.py",
        }
        if not required.issubset(names):
            raise ValueError("sdist is missing required source files")
        if any(member.issym() or member.islnk() for member in members):
            raise ValueError("sdist may not contain links")
        if any(not member.isdir() and not member.isfile() for member in members):
            raise ValueError("sdist may contain only directories and regular files")
        if any(len(PurePosixPath(name).parts) > 1 and PurePosixPath(name).parts[1] == "tests" for name in names):
            raise ValueError("sdist may not contain the repository test suite")


def _verify_zipapp(path: Path) -> None:
    if not path.read_bytes().startswith(b"#!/usr/bin/env python3\n"):
        raise ValueError("zipapp must carry the portable Python shebang")
    with zipfile.ZipFile(path) as archive:
        names = tuple(archive.namelist())
        _verify_member_names(names)
        if names != tuple(sorted(names)):
            raise ValueError("zipapp entries must be sorted")
        required = {"LICENSE", "NOTICE", "__main__.py", "raften/cli.py"}
        if not required.issubset(names):
            raise ValueError("zipapp is missing its entrypoint, package, or legal files")
        if any(entry.compress_type != zipfile.ZIP_STORED for entry in archive.infolist()):
            raise ValueError("zipapp entries must use deterministic stored encoding")
        if len({entry.date_time for entry in archive.infolist()}) != 1:
            raise ValueError("zipapp entry timestamps must be normalized")


def _verify_member_names(names: tuple[str, ...]) -> None:
    if len(names) != len(set(names)):
        raise ValueError("release archive contains duplicate member names")
    for name in names:
        candidate = PurePosixPath(name)
        if not name or name.startswith("/") or "\\" in name or ".." in candidate.parts:
            raise ValueError(f"unsafe archive member: {name!r}")
        if ".git" in candidate.parts or "__pycache__" in candidate.parts or name.endswith(".pyc"):
            raise ValueError(f"release archive contains excluded state: {name!r}")


def _select_release_files(
    directory: Path,
    *,
    require_manifest: bool = False,
) -> tuple[Path, Path, Path, Path | None]:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"artifact directory is not a regular directory: {directory}")
    files = tuple(sorted(directory.iterdir(), key=lambda item: item.name))
    if any(not path.is_file() or path.is_symlink() for path in files):
        raise ValueError("artifact directory may contain only regular files")
    wheels = tuple(path for path in files if path.name.endswith(".whl"))
    source_archives = tuple(path for path in files if path.name.endswith(".tar.gz"))
    zipapps = tuple(path for path in files if path.name.endswith(".pyz"))
    manifests = tuple(path for path in files if path.name == "SHA256SUMS")
    if tuple(map(len, (wheels, source_archives, zipapps))) != (1, 1, 1):
        raise ValueError("artifact directory must contain exactly one wheel, sdist, and zipapp")
    if len(manifests) > 1 or (require_manifest and len(manifests) != 1):
        raise ValueError("qualified artifact directory must contain exactly one SHA256SUMS")
    allowed = {wheels[0], source_archives[0], zipapps[0], *manifests}
    unexpected = tuple(path.name for path in files if path not in allowed)
    if unexpected:
        raise ValueError(f"artifact directory contains unexpected files: {unexpected!r}")
    manifest = manifests[0] if manifests else None
    return wheels[0], source_archives[0], zipapps[0], manifest


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    options = parser.parse_args(arguments)
    artifacts = verify_artifacts(
        options.directory,
        expected_name=options.name,
        expected_version=options.version,
    )
    write_checksums(options.directory, artifacts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
