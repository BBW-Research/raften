from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from release_tools.artifacts import Artifact
from release_tools.qualification import (
    QualificationFailure,
    _isolated_environment,
    verify_checksums,
)
from release_tools.smoke import _environment
from tests.support.paths import ROOT


class ReleaseQualificationTests(unittest.TestCase):
    def test_checksum_verification_requires_exact_sorted_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "z.pyz"
            second = root / "a.whl"
            first.write_bytes(b"z")
            second.write_bytes(b"a")
            artifacts = tuple(
                Artifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
                for path in (first, second)
            )
            (root / "SHA256SUMS").write_text(
                "".join(
                    f"{artifact.sha256}  {artifact.path.name}\n"
                    for artifact in reversed(artifacts)
                ),
                encoding="ascii",
            )
            verify_checksums(root, artifacts)
            (root / "SHA256SUMS").write_text("0" * 64 + "  a.whl\n", encoding="ascii")
            with self.assertRaisesRegex(QualificationFailure, "does not exactly match"):
                verify_checksums(root, artifacts)

    def test_smoke_environment_cannot_import_from_the_checkout(self) -> None:
        previous = {
            "PYTHONHOME": os.environ.get("PYTHONHOME"),
            "PYTHONPATH": os.environ.get("PYTHONPATH"),
            "VIRTUAL_ENV": os.environ.get("VIRTUAL_ENV"),
        }
        try:
            os.environ.update(
                {
                    "PYTHONHOME": "/untrusted/home",
                    "PYTHONPATH": str(ROOT / "src"),
                    "VIRTUAL_ENV": "/untrusted/environment",
                }
            )
            environment = _environment()
        finally:
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value

        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("PYTHONPATH", environment)
        self.assertNotIn("VIRTUAL_ENV", environment)

    def test_install_environment_discards_ambient_python_and_pip_controls(self) -> None:
        previous = dict(os.environ)
        try:
            os.environ.update(
                {
                    "PIP_CONSTRAINT": "/untrusted/constraints.txt",
                    "PIP_FIND_LINKS": "/untrusted/wheels",
                    "PYTHONWARNINGS": "error",
                }
            )
            environment = _isolated_environment(Path("/verified/wheels"), Path("/workspace"))
        finally:
            os.environ.clear()
            os.environ.update(previous)

        self.assertNotIn("PIP_CONSTRAINT", environment)
        self.assertNotIn("PYTHONWARNINGS", environment)
        self.assertEqual(environment["PIP_FIND_LINKS"], "/verified/wheels")
        self.assertEqual(environment["PIP_CONFIG_FILE"], os.devnull)

    def test_benchmark_wrapper_ignores_hostile_cwd_and_python_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            hostile = Path(directory)
            package = hostile / "release_tools"
            package.mkdir()
            (package / "__init__.py").write_text("")
            (package / "benchmark.py").write_text('print("HOSTILE_RELEASE_TOOLS")\n')
            environment = dict(os.environ)
            environment.update(
                {
                    "PYTHONHOME": "/untrusted/python-home",
                    "PYTHONPATH": str(hostile),
                }
            )
            result = subprocess.run(
                [
                    str(ROOT / "scripts" / "benchmark"),
                    "--count",
                    "100",
                    "--skip-git-inventory",
                ],
                cwd=hostile,
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                env=environment,
                timeout=30,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["schema_version"], 1)
        self.assertNotIn("HOSTILE_RELEASE_TOOLS", result.stdout)

    def test_linux_qualification_pins_images_and_disables_network(self) -> None:
        script = (ROOT / "scripts" / "qualify-linux").read_text(encoding="utf-8")
        self.assertIn("python:3.12.14-bookworm@sha256:581429e3", script)
        self.assertIn("python:3.13.14-bookworm@sha256:8b9a8b28", script)
        self.assertIn("--pull=never", script)
        self.assertIn("--network=none", script)
        self.assertIn("--read-only", script)
        self.assertIn("--cap-drop=ALL", script)

    def test_ci_qualifies_every_supported_platform_and_python_pair(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "repository-policy.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- ubuntu-24.04", workflow)
        self.assertIn("- macos-15", workflow)
        self.assertIn('- "3.12"', workflow)
        self.assertIn('- "3.13"', workflow)
        self.assertNotIn("windows-", workflow.lower())
        self.assertIn("scripts/build-release", workflow)
        self.assertIn("scripts/qualify-artifacts", workflow)
        self.assertIn("name: Required repository policy", workflow)

    def test_codeowners_assigns_every_sensitive_path_to_the_repository_owner(self) -> None:
        codeowners = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        entries = {
            fields[0]: fields[1:]
            for line in codeowners.splitlines()
            if (fields := line.split()) and not fields[0].startswith("#")
        }
        expected_patterns = {
            "/.github/",
            "/CHANGELOG.md",
            "/LICENSE",
            "/NOTICE",
            "/pyproject.toml",
            "/release_tools/",
            "/repo-context.toml",
            "/requirements/release.txt",
            "/scripts/build-release",
            "/scripts/fetch-release-tools",
            "/scripts/qualify-artifacts",
            "/scripts/qualify-linux",
        }

        self.assertEqual(set(entries), expected_patterns)
        self.assertTrue(all(owners == ["@taiqihe"] for owners in entries.values()))

    def test_release_scripts_keep_acquisition_separate_from_offline_builds(self) -> None:
        acquisition = (ROOT / "scripts" / "fetch-release-tools").read_text(encoding="utf-8")
        build = (ROOT / "scripts" / "build-release").read_text(encoding="utf-8")
        qualification = (ROOT / "release_tools" / "qualification.py").read_text(encoding="utf-8")
        self.assertIn("pip --isolated download", acquisition)
        self.assertIn("--require-hashes", acquisition)
        self.assertIn("PIP_NO_INDEX=1", build)
        self.assertIn("PIP_FIND_LINKS", build)
        self.assertIn("--no-index", build)
        self.assertIn('--find-links "$STAGED_WHEELHOUSE"', build)
        self.assertIn('"PIP_NO_INDEX": "1"', qualification)
        self.assertIn("stage_locked_wheelhouse", qualification)
        self.assertIn("release_tools.source_guard", build)
        self.assertGreaterEqual(build.count("/usr/bin/env -i"), 2)
        self.assertIn('"$PYTHON" -P -m', build)
        self.assertIn('"$PYTHON" -I -m pip', acquisition)
        self.assertNotIn("http://", build + qualification)
        self.assertNotIn("https://", build + qualification)


if __name__ == "__main__":
    unittest.main()
