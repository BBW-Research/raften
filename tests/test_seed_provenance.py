from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_MANIFEST = ROOT / "reference" / "scene-maker" / "SOURCE.json"


class SeedProvenanceTests(unittest.TestCase):
    def test_manifest_identifies_the_accepted_scene_maker_snapshot(self) -> None:
        manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["repository"], "BBW-Research/scene-maker")
        self.assertEqual(
            manifest["source_commit"],
            "9e792124bc61f55150416b8bf803862c6c634c78",
        )
        self.assertEqual(
            set(manifest["copied_files"]),
            {
                "tools/check_repository_policy.py",
                "reference/scene-maker/repository-policy.yml",
                "reference/scene-maker/lychee.toml",
            },
        )

    def test_copied_files_match_recorded_git_blobs(self) -> None:
        manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        for local_path, record in manifest["copied_files"].items():
            with self.subTest(path=local_path):
                self.assertEqual(record["mode"], "verbatim")
                data = (ROOT / local_path).read_bytes()
                git_blob = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
                self.assertEqual(git_blob, record["git_blob_sha1"])
                if "sha256" in record:
                    self.assertEqual(hashlib.sha256(data).hexdigest(), record["sha256"])

    def test_clean_json_policy_is_fixture_scoped_after_self_hosting(self) -> None:
        manifest = json.loads(SOURCE_MANIFEST.read_text(encoding="utf-8"))
        retired = manifest["retired_adaptations"]
        self.assertIn("config/repository_policy.v1.json", retired)
        self.assertFalse((ROOT / "config/repository_policy.v1.json").exists())
        fixture = ROOT / "tests/fixtures/seed/clean-policy.json"
        self.assertIn(fixture.relative_to(ROOT).as_posix(), manifest["adapted_files"])
        recorded_hash = manifest["adapted_file_hashes"][
            fixture.relative_to(ROOT).as_posix()
        ]["sha256"]
        self.assertEqual(hashlib.sha256(fixture.read_bytes()).hexdigest(), recorded_hash)
        policy = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(policy["legacy_oversize"], {})


if __name__ == "__main__":
    unittest.main()
