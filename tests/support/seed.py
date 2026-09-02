from __future__ import annotations

import importlib.util
from types import ModuleType

from tests.support.paths import ROOT, SEED_PATH


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
