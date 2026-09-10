from __future__ import annotations

import hashlib
import unittest

from raften.config import load_policy
from raften.model import FileKind
from tests.support.paths import ROOT


class PilotPolicyTests(unittest.TestCase):
    def test_every_pilot_policy_is_strict_separate_and_has_no_exceptions(self) -> None:
        policies = {}
        for name in ("scene-maker", "nano-dllm", "research-vault"):
            with self.subTest(name=name):
                path = ROOT / "tests" / "fixtures" / "pilots" / name / "repo-context.toml"
                policy = load_policy(path)
                policies[name] = path.read_bytes()
                self.assertEqual(policy.version, 1)
                self.assertEqual(policy.file_rules[-1].kind, FileKind.AUTHORED)
                self.assertEqual(policy.file_rules[-1].patterns, ("**",))
                self.assertTrue(policy.file_rules[-1].scan)
                self.assertEqual(policy.exceptions.records, ())
                self.assertTrue(policy.ratchet.compare_file_sizes)
                self.assertTrue(policy.ratchet.forbid_new_oversize)

        self.assertEqual(len(set(policies.values())), 3)

    def test_pilots_use_configuration_instead_of_engine_special_cases(self) -> None:
        production = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((ROOT / "src" / "raften").glob("*.py"))
        ).lower()
        self.assertNotIn("scene-maker", production)
        self.assertNotIn("nano-dllm", production)
        self.assertNotIn("research-vault", production)

    def test_documented_pilot_inputs_are_hash_frozen(self) -> None:
        expected = {
            "nano-dllm/repo-context.toml": "02d2f8287e86543875ba0a962d0fde3eb4404f602e6afb0de4e2734a851d62f2",
            "nano-dllm/docs/index.md": "d4a4c3fccc1d20df1eade6bfbc589fb7819eb26dc4444b6fd1cbf3d1c05c1005",
            "research-vault/repo-context.toml": "3fddfed64f1fc23c5090eb5d1a07f504bdc731151b25647963a6a7132315ba51",
            "research-vault/docs/index.md": "7e25d0844f7a0e86af6060f06f635395e796e22bdf7ab832cd0ba39833663d10",
            "scene-maker/repo-context.toml": "2869d79ea5b1d20e89f5553a6bd9891178d2e37ea9d7703ae6b236b52e0069cd",
        }
        root = ROOT / "tests" / "fixtures" / "pilots"
        for relative, expected_hash in expected.items():
            with self.subTest(relative=relative):
                self.assertEqual(
                    hashlib.sha256((root / relative).read_bytes()).hexdigest(),
                    expected_hash,
                )


if __name__ == "__main__":
    unittest.main()
