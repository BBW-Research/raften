"""Install and exercise every release artifact without network access."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

from release_tools.artifacts import Artifact, stage_release_artifacts, verify_artifacts
from release_tools.smoke import smoke
from release_tools.wheelhouse import WheelhouseError, stage_locked_wheelhouse


class QualificationFailure(RuntimeError):
    """A release artifact failed an installation or integrity check."""


def qualify(
    artifact_directory: Path,
    wheelhouse: Path,
    requirements: Path,
    *,
    expected_name: str,
    expected_version: str,
) -> None:
    """Verify, install, and smoke-test one wheel, sdist, and zipapp."""

    if not wheelhouse.is_dir():
        raise ValueError(f"release wheelhouse does not exist: {wheelhouse}")
    with tempfile.TemporaryDirectory(prefix="raften-qualification-") as directory:
        workspace = Path(directory)
        staged_artifacts = stage_release_artifacts(
            artifact_directory,
            workspace / "artifacts",
        )
        artifacts = verify_artifacts(
            staged_artifacts,
            expected_name=expected_name,
            expected_version=expected_version,
        )
        verify_checksums(staged_artifacts, artifacts)
        installable = tuple(
            artifact.path
            for artifact in artifacts
            if artifact.path.name.endswith((".whl", ".tar.gz"))
        )
        zipapps = tuple(artifact.path for artifact in artifacts if artifact.path.suffix == ".pyz")
        if len(installable) != 2 or len(zipapps) != 1:
            raise QualificationFailure("release artifact selection is internally inconsistent")

        staged_wheelhouse = workspace / "wheelhouse"
        try:
            stage_locked_wheelhouse(wheelhouse, requirements, staged_wheelhouse)
        except WheelhouseError as error:
            raise QualificationFailure(str(error)) from error
        for artifact in installable:
            _qualify_installable(artifact, staged_wheelhouse, expected_version)
        smoke((sys.executable, str(zipapps[0])), expected_version=expected_version)


def verify_checksums(directory: Path, artifacts: tuple[Artifact, ...]) -> None:
    """Require an exact, sorted checksum manifest for the release artifacts."""

    manifest = directory / "SHA256SUMS"
    if not manifest.is_file() or manifest.is_symlink():
        raise QualificationFailure("SHA256SUMS is not a regular file")
    try:
        actual = manifest.read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        raise QualificationFailure(f"cannot read checksum manifest: {error}") from error
    expected = "".join(
        f"{artifact.sha256}  {artifact.path.name}\n"
        for artifact in sorted(artifacts, key=lambda item: item.path.name)
    )
    if actual != expected:
        raise QualificationFailure("SHA256SUMS does not exactly match the release artifacts")


def _qualify_installable(artifact: Path, wheelhouse: Path, expected_version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="raften-install-") as directory:
        workspace = Path(directory)
        environment = _isolated_environment(wheelhouse, workspace)
        environment_directory = workspace / "environment"
        venv.EnvBuilder(with_pip=True, clear=True, symlinks=True).create(environment_directory)
        python = environment_directory / "bin" / "python"
        command = environment_directory / "bin" / "raften"
        result = subprocess.run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--no-deps",
                str(artifact.resolve()),
            ],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=workspace,
            env=environment,
            timeout=120,
        )
        if result.returncode != 0:
            raise QualificationFailure(
                f"installation failed for {artifact.name}: "
                f"stdout={result.stdout!r}, stderr={result.stderr!r}"
            )
        smoke((str(command),), expected_version=expected_version)


def _isolated_environment(wheelhouse: Path, workspace: Path) -> dict[str, str]:
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.startswith("PIP_") or name.startswith("PYTHON") or name == "VIRTUAL_ENV":
            environment.pop(name, None)
    environment.update(
        {
            "HOME": str(workspace),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_FIND_LINKS": str(wheelhouse.resolve()),
            "PIP_NO_CACHE_DIR": "1",
            "PIP_NO_INDEX": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--requirements", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--version", required=True)
    options = parser.parse_args(arguments)
    qualify(
        options.artifacts,
        options.wheelhouse,
        options.requirements,
        expected_name=options.name,
        expected_version=options.version,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
