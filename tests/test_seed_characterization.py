from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / "tools" / "check_repository_policy.py"
POLICY_PATH = ROOT / "config" / "repository_policy.v1.json"


def load_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location("scene_maker_repository_policy", SEED_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scene-maker seed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEED = load_seed()


class SeedCharacterizationTests(unittest.TestCase):
    def test_noncanonical_parent_path_is_rejected(self) -> None:
        with self.assertRaises(SEED.PolicyError):
            SEED.canonical_rel("docs/../README.md")

    def test_inline_markdown_targets_are_resolved_relative_to_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "docs" / "guide").mkdir(parents=True)
            (root / "docs" / "guide" / "index.md").write_text("# Guide\n")
            targets = SEED.markdown_targets(
                "docs/index.md",
                "See [the guide](guide/) and [outside](https://example.com).",
                root,
            )
        self.assertEqual(targets, {"docs/guide/index.md"})

    def test_document_index_must_link_direct_sibling(self) -> None:
        policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "index.md").write_text("# Docs\n", encoding="utf-8")
            (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
            errors, count = SEED.check_docs(
                root,
                ["docs/guide.md", "docs/index.md"],
                policy,
            )
        self.assertEqual(count, 2)
        self.assertIn(
            "docs/index.md: does not directly link sibling document docs/guide.md",
            errors,
        )

    def test_policy_limit_increase_is_rejected(self) -> None:
        base = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        current = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        current["max_text_bytes"] += 1
        self.assertIn("max_text_bytes may not increase", SEED.check_not_weakened(current, base))


if __name__ == "__main__":
    unittest.main()
