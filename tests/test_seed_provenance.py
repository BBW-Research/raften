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


if __name__ == "__main__":
    unittest.main()
