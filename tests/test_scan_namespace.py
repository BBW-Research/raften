"""Normal commands retain one root namespace until evaluation completes."""

import contextlib
import os
import select
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from raften import inventory, runner
from raften.init_namespace import bind_namespace
from raften.run_model import CommandFailure, RepositoryRun
from tests.support.repository import RepositoryFixture
from tests.support.sizes import TODAY
from tests.support.target import install_clean_target


class ScanNamespaceTests(unittest.TestCase):
    def assert_changed(self, outcome):
        self.assertTrue(isinstance(outcome, CommandFailure), type(outcome).__name__)
        self.assertEqual(outcome.diagnostics[0].code, "GIT005")

    def test_coherent_root_or_ancestor_decoy_after_git_inventory_refuses(self):
        for ancestor in (False, True):
            for explain in (False, True):
                with self.subTest(ancestor=ancestor, explain=explain), \
                        RepositoryFixture() as fixture, RepositoryFixture() as decoy, \
                        tempfile.TemporaryDirectory() as directory:
                    arena = Path(directory).resolve()
                    for name, repository in (("live", fixture), ("decoy", decoy)):
                        parent = arena / name
                        parent.mkdir()
                        repository.root.rename(parent / "repo")
                        repository.root = parent / "repo"
                        install_clean_target(repository)
                    fixture.write_text("README.md", "x" * 30_000)
                    live = fixture.root.parent if ancestor else fixture.root
                    foreign = decoy.root.parent if ancestor else decoy.root
                    held = live.with_name("held")
                    inspect = inventory._inspect_worktree_entry
                    swapped = False
                    def substitute(*args, **kwargs):
                        nonlocal swapped
                        if not swapped:
                            live.rename(held)
                            foreign.rename(live)
                            swapped = True
                        return inspect(*args, **kwargs)
                    try:
                        with patch("raften.inventory._inspect_worktree_entry", side_effect=substitute):
                            outcome = (runner.explain_repository_path(fixture.root, "README.md", evaluation_date=TODAY)
                                       if explain else runner.run_repository(fixture.root, evaluation_date=TODAY))
                        self.assert_changed(outcome)
                    finally:
                        if swapped:
                            live.rename(foreign)
                            held.rename(live)

    def test_restored_root_renames_at_each_phase_refuse(self):
        for phase in ("open_repository", "inventory_worktree", "evaluate_sizes", "evaluate_documentation", "_evaluate_baseline"):
            with self.subTest(phase=phase), RepositoryFixture() as fixture:
                install_clean_target(fixture)
                original = getattr(runner, phase)
                def substitute(*args, **kwargs):
                    result = original(*args, **kwargs)
                    held = fixture.root.with_name(fixture.root.name + "-held")
                    fixture.root.rename(held)
                    held.rename(fixture.root)
                    return result
                with patch.object(runner, phase, side_effect=substitute):
                    self.assert_changed(runner.run_repository(fixture.root, evaluation_date=TODAY))

    def test_expected_failure_revalidates_namespace(self):
        with RepositoryFixture() as fixture:
            install_clean_target(fixture)
            fixture.write_text("raften.toml", "invalid toml")
            parse = runner.parse_policy
            def substitute(*args, **kwargs):
                held = fixture.root.with_name(fixture.root.name + "-held")
                fixture.root.rename(held)
                held.rename(fixture.root)
                return parse(*args, **kwargs)
            with patch("raften.runner.parse_policy", side_effect=substitute):
                self.assert_changed(runner.run_repository(fixture.root, evaluation_date=TODAY))

    def test_guard_descriptors_close_on_success_expected_and_unexpected_failure(self):
        for failure in ("none", "configuration", "unexpected"):
            with self.subTest(failure=failure), RepositoryFixture() as fixture:
                install_clean_target(fixture)
                if failure == "configuration":
                    fixture.write_text("raften.toml", "invalid toml")
                guards = []
                @contextlib.contextmanager
                def capture(root):
                    with bind_namespace(root) as guard:
                        guards.append(guard)
                        yield guard
                with patch("raften.runner.bind_namespace", side_effect=capture):
                    if failure == "unexpected":
                        with patch("raften.runner.evaluate_sizes", side_effect=RuntimeError("probe")):
                            with self.assertRaisesRegex(RuntimeError, "probe"):
                                runner.run_repository(fixture.root, evaluation_date=TODAY)
                    else:
                        runner.run_repository(fixture.root, evaluation_date=TODAY)
                self.assertEqual(len(guards), 1)
                for descriptor, _ in guards[0].witnesses:
                    with self.assertRaises(OSError):
                        os.fstat(descriptor)

    def test_symlink_root_and_linked_worktree_remain_supported(self):
        with RepositoryFixture() as fixture, tempfile.TemporaryDirectory() as directory:
            install_clean_target(fixture)
            fixture.commit()
            alias = Path(directory) / "alias"
            alias.symlink_to(fixture.root, target_is_directory=True)
            linked = Path(directory) / "linked"
            fixture.git("worktree", "add", "--quiet", "--detach", str(linked))
            for candidate in (alias, linked):
                with self.subTest(candidate=candidate):
                    self.assertIsInstance(runner.run_repository(candidate, evaluation_date=TODAY), RepositoryRun)

    def test_root_content_change_and_timestamp_fallback_refuse(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback), RepositoryFixture() as fixture:
                install_clean_target(fixture)
                original = runner.evaluate_sizes
                def change(*args, **kwargs):
                    result = original(*args, **kwargs)
                    fixture.write_text("late.txt", "late\n")
                    return result
                with contextlib.ExitStack() as stack:
                    if fallback:
                        stack.enter_context(patch("raften.init_namespace.select", SimpleNamespace(kqueue=None)))
                    stack.enter_context(patch("raften.runner.evaluate_sizes", side_effect=change))
                    self.assert_changed(runner.run_repository(fixture.root, evaluation_date=TODAY))

    def test_partial_anchor_acquisition_closes_descriptors(self):
        with RepositoryFixture() as fixture:
            install_clean_target(fixture)
            opened = []
            original = os.open
            def fail_later(*args, **kwargs):
                if len(opened) == 2:
                    raise OSError("anchor probe")
                descriptor = original(*args, **kwargs)
                opened.append(descriptor)
                return descriptor
            with patch("raften.init_namespace.os.open", side_effect=fail_later):
                self.assert_changed(runner.run_repository(fixture.root, evaluation_date=TODAY))
            self.assertEqual(len(opened), 2)
            for descriptor in opened:
                with self.assertRaises(OSError):
                    os.fstat(descriptor)

    def test_ancestor_sibling_activity_matches_namespace_backend(self):
        for fallback in (False, True):
            with self.subTest(fallback=fallback), RepositoryFixture() as fixture:
                install_clean_target(fixture)
                original = runner.evaluate_sizes
                sibling = fixture.root.with_name(fixture.root.name + "-sibling")
                def change(*args, **kwargs):
                    result = original(*args, **kwargs)
                    sibling.mkdir()
                    sibling.rmdir()
                    return result
                with contextlib.ExitStack() as stack:
                    if fallback:
                        stack.enter_context(patch("raften.init_namespace.select", SimpleNamespace(kqueue=None)))
                    stack.enter_context(patch("raften.runner.evaluate_sizes", side_effect=change))
                    outcome = runner.run_repository(fixture.root, evaluation_date=TODAY)
                if fallback or not hasattr(select, "kqueue"):
                    self.assert_changed(outcome)
                else:
                    self.assertIsInstance(outcome, RepositoryRun)
