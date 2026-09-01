from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[2]
SEED_PATH = ROOT / "tools" / "check_repository_policy.py"
BOOTSTRAP_POLICY_PATH = ROOT / "config" / "repository_policy.v1.json"


def load_seed() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "scene_maker_repository_policy",
        SEED_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load scene-maker seed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SEED = load_seed()
