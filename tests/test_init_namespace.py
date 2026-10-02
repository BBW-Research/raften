"""Initialization must reject restored root and ancestor substitutions."""

import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from raften import initialization
from raften.init_namespace import bind_namespace
from raften.init_safety import InitializationError
from raften.run_model import CommandFailure, InitResult
from tests.support.repository import RepositoryFixture


@contextmanager
def repositories():
    with tempfile.TemporaryDirectory() as directory, RepositoryFixture() as original, RepositoryFixture() as decoy:
        arena = Path(directory)
        for name, repository in (("live", original), ("decoy", decoy)):
            parent = arena / name
            parent.mkdir()
            target = parent / "repo"
            repository.root.rename(target)
            repository.root = target
            repository.write_text("file.txt", "original\n")
            repository.commit()
        yield original, decoy


@contextmanager
def substituted(live, decoy):
    held = live.with_name(live.name + "-held")
    live.rename(held)
    decoy.rename(live)
    restored = False

    def restore():
        nonlocal restored
        if not restored:
            live.rename(decoy)
            held.rename(live)
            restored = True

    try:
        yield restore
    finally:
        restore()


class InitializationNamespaceTests(unittest.TestCase):
    def test_descriptors_close_after_success_failure_and_partial_acquisition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for fail in (False, True):
                descriptors = []
                try:
                    with bind_namespace(root) as namespace:
                        descriptors = [fd for fd, _stamp in namespace.witnesses]
                        if fail:
                            raise RuntimeError("injected")
                except RuntimeError:
                    pass
                for descriptor in descriptors:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)
            real_open = os.open
            opened = []

            def record_open(*args, **kwargs):
                descriptor = real_open(*args, **kwargs)
                opened.append(descriptor)
                return descriptor

            with patch("raften.init_namespace.os.open", side_effect=record_open):
                with self.assertRaises(InitializationError):
                    with bind_namespace(root / "missing"):
                        self.fail("missing directory was accepted")
            self.assertTrue(opened)
            for descriptor in opened:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_symlink_selected_root_and_linked_worktree_still_initialize(self):
        with repositories() as (original, decoy):
            alias = original.root.parent / "alias"
            alias.symlink_to(original.root, target_is_directory=True)
            self.assertIsInstance(initialization.initialize_repository(alias), InitResult)
            linked = decoy.root.parent / "linked"
            decoy.git("worktree", "add", "--detach", str(linked), "HEAD")
            self.assertIsInstance(initialization.initialize_repository(linked), InitResult)

    def test_restored_namespace_change_is_rejected_at_each_validation_phase(self):
        phases = ("open_repository", "inventory_worktree", "capture_clean_repository",
                  "evaluate_sizes", "repository_remains_clean")
        for ancestor in (False, True):
            for phase in phases:
                with self.subTest(ancestor=ancestor, phase=phase), repositories() as (original, decoy):
                    live = original.root.parent if ancestor else original.root
                    replacement = decoy.root.parent if ancestor else decoy.root
                    real = getattr(initialization, phase)

                    def bounce(*args, **kwargs):
                        result = real(*args, **kwargs)
                        with substituted(live, replacement):
                            pass
                        return result

                    with patch.object(initialization, phase, side_effect=bounce):
                        result = initialization.initialize_repository(original.root)
                    self.assertIsInstance(result, CommandFailure)
                    self.assertEqual(result.diagnostics[0].code, "INIT002")
                    self.assertFalse(original.path("raften.toml").exists())
                    self.assertFalse(decoy.path("raften.toml").exists())

    def test_decoy_preflight_cannot_authorize_force_or_debt_writes_in_original(self):
        for ancestor in (False, True):
            for capture in (False, True):
                with self.subTest(ancestor=ancestor, capture=capture), repositories() as (original, decoy):
                    original.write_text("raften.toml", "original policy\n")
                    original.commit()
                    original.write_text("file.txt", "dirty original\n")
                    live = original.root.parent if ancestor else original.root
                    replacement = decoy.root.parent if ancestor else decoy.root
                    real_initialize = initialization._initialize_anchored
                    real_write = initialization._write_artifacts

                    def evaluate_decoy(*args, **kwargs):
                        with substituted(live, replacement) as restore:
                            def restored_write(*write_args, **write_kwargs):
                                restore()
                                return real_write(*write_args, **write_kwargs)
                            with patch.object(initialization, "_write_artifacts", side_effect=restored_write):
                                return real_initialize(*args, **kwargs)

                    with patch.object(initialization, "_initialize_anchored", side_effect=evaluate_decoy):
                        result = initialization.initialize_repository(original.root, force=True, capture_debt=capture)
                    self.assertIsInstance(result, CommandFailure)
                    self.assertEqual(result.diagnostics[0].code, "INIT002")
                    self.assertEqual(original.path("raften.toml").read_text(), "original policy\n")
                    self.assertFalse(original.path("raften.debt.json").exists())
                    self.assertFalse(decoy.path("raften.toml").exists())
