"""Initialization must reject restored root and ancestor substitutions."""

import os
import select
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

from raften import initialization, init_transaction
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
    @unittest.skipUnless(hasattr(select, "kqueue"), "requires vnode rename notifications")
    def test_unrelated_ancestor_activity_does_not_invalidate_preflight(self):
        phases = ("open_repository", "inventory_worktree", "capture_clean_repository",
                  "evaluate_sizes", "repository_remains_clean")
        for phase in phases:
            with self.subTest(phase=phase), repositories() as (original, _decoy):
                real = getattr(initialization, phase)

                def sibling_activity(*args, **kwargs):
                    result = real(*args, **kwargs)
                    for parent in (original.root.parent, original.root.parent.parent):
                        sibling = parent / "unrelated-temporary-file"
                        sibling.write_text("background activity\n")
                        sibling = sibling.rename(parent / "renamed-temporary-file")
                        sibling.unlink()
                    return result

                with patch.object(initialization, phase, side_effect=sibling_activity):
                    result = initialization.initialize_repository(original.root)
                self.assertIsInstance(result, InitResult)
                self.assertTrue(original.path("raften.toml").is_file())

    @unittest.skipUnless(hasattr(select, "kqueue"), "requires vnode rename notifications")
    def test_ancestor_activity_preserves_path_scoped_collision_diagnostics(self):
        for capture, raced_path in ((False, "raften.debt.json"), (True, "raften.toml")):
            with self.subTest(capture=capture), repositories() as (original, _decoy):
                original.ignore("raften.debt.json")
                original.commit()
                real_open = initialization.open_repository
                real_install = init_transaction._install_artifact
                raced = False

                def sibling_activity(*args, **kwargs):
                    repository = real_open(*args, **kwargs)
                    sibling = original.root.parent / "background-file"
                    sibling.touch()
                    sibling.unlink()
                    return repository

                def collide(item, *, force):
                    nonlocal raced
                    if item.artifact.path == raced_path:
                        raced = True
                        original.write_text(raced_path, "concurrent owner data\n")
                    return real_install(item, force=force)

                with patch.object(initialization, "open_repository", side_effect=sibling_activity), \
                        patch.object(init_transaction, "_install_artifact", side_effect=collide):
                    result = initialization.initialize_repository(original.root, capture_debt=capture)
                self.assertTrue(raced)
                self.assertIsInstance(result, CommandFailure)
                self.assertEqual(result.diagnostics[0].code, "INIT002")
                self.assertIsNotNone(result.diagnostics[0].location)
                self.assertEqual(result.diagnostics[0].location.path, raced_path)
                self.assertEqual(original.path(raced_path).read_text(), "concurrent owner data\n")

    @unittest.skipUnless(hasattr(select, "kqueue"), "requires vnode rename notifications")
    def test_vnode_queue_errors_fail_closed_and_release_descriptors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch("raften.init_namespace.select.kqueue", side_effect=OSError("queue unavailable")):
                with self.assertRaises(InitializationError):
                    with bind_namespace(root):
                        self.fail("queue creation failure was ignored")
            for failure in ("register", "poll", "unexpected-event"):
                with self.subTest(failure=failure):
                    native_queue = select.kqueue()
                    queue = Mock(wraps=native_queue)
                    real_open = os.open
                    opened = []

                    def record_open(*args, **kwargs):
                        descriptor = real_open(*args, **kwargs)
                        opened.append(descriptor)
                        return descriptor

                    def control(changes, max_events, timeout):
                        if changes is not None and failure == "register" and len(opened) > 2:
                            raise OSError("watch unavailable")
                        if changes is None:
                            if failure == "poll":
                                raise OSError("queue unreadable")
                            if failure == "unexpected-event":
                                return [object()]
                        return native_queue.control(changes, max_events, timeout)

                    queue.control.side_effect = control
                    with patch("raften.init_namespace.select.kqueue", return_value=queue), \
                            patch("raften.init_namespace.os.open", side_effect=record_open):
                        with self.assertRaises(InitializationError):
                            with bind_namespace(root):
                                self.fail("unreliable queue was accepted")
                    self.assertTrue(native_queue.closed)
                    self.assertTrue(opened)
                    for descriptor in opened:
                        with self.assertRaises(OSError):
                            os.fstat(descriptor)

    def test_timestamp_fallback_still_rejects_restored_namespace_changes(self):
        for ancestor in (False, True):
            with self.subTest(ancestor=ancestor), repositories() as (original, decoy):
                live = original.root.parent if ancestor else original.root
                replacement = decoy.root.parent if ancestor else decoy.root
                with patch("raften.init_namespace.select.kqueue", None, create=True):
                    with bind_namespace(original.root.resolve()) as namespace:
                        with substituted(live, replacement):
                            pass
                        with self.assertRaises(InitializationError):
                            namespace.verify()

    @unittest.skipUnless(hasattr(select, "kqueue"), "requires vnode rename notifications")
    def test_later_watch_registration_preserves_queued_ancestor_rename(self):
        with repositories() as (original, decoy):
            ancestor = original.root.parent
            ancestor_identity = ancestor.stat().st_ino
            native_queue = select.kqueue()
            queue = Mock(wraps=native_queue)
            raced = False

            def control(changes, max_events, timeout):
                nonlocal raced
                events = native_queue.control(changes, max_events, timeout)
                if changes and os.fstat(changes[0].ident).st_ino == ancestor_identity:
                    raced = True
                    with substituted(ancestor, decoy.root.parent):
                        pass
                return events

            queue.control.side_effect = control
            with patch("raften.init_namespace.select.kqueue", return_value=queue):
                with self.assertRaises(InitializationError):
                    with bind_namespace(original.root.resolve()):
                        self.fail("a later watch consumed the pending ancestor rename")
            self.assertTrue(raced)
            self.assertTrue(native_queue.closed)

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
