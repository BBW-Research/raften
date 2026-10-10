"""Integration setup must leave Git metadata quiescent before evaluation."""

import json
import tempfile
import unittest
from pathlib import Path

from tests.support.repository import RepositoryFixture


class RepositoryFixtureTests(unittest.TestCase):
    def test_fixture_commits_do_not_start_automatic_maintenance(self) -> None:
        for enable_maintenance in (False, True):
            with self.subTest(enable_maintenance=enable_maintenance), \
                    RepositoryFixture() as repository, tempfile.TemporaryDirectory() as directory:
                if enable_maintenance:
                    repository.git("config", "maintenance.auto", "true")
                # Keep the positive control synchronous on both old and new Git.
                repository.git("config", "maintenance.autoDetach", "false")
                repository.git("config", "gc.autoDetach", "false")
                repository.write_text("seed.txt", "seed\n")
                repository.git("add", "--all")
                trace = Path(directory) / "events.json"
                repository.git_bytes(
                    "commit", "--quiet", "--message", "fixture",
                    environment_overrides={"GIT_TRACE2_EVENT": str(trace)},
                )
                events = (json.loads(line) for line in trace.read_text().splitlines())
                maintenance = tuple(event for event in events
                                    if event.get("event") == "child_start"
                                    and event.get("argv", [])[1:3] == ["maintenance", "run"])
                self.assertEqual(bool(maintenance), enable_maintenance)


if __name__ == "__main__":
    unittest.main()
