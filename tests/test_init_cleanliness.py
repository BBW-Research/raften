from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import repo_context.initialization as initialization
import repo_context.inventory as inventory_module
import repo_context.sizes as sizes_module
from repo_context.inventory import RepositoryHandle
from repo_context.model import ClassifiedContent, InventoryEntry
from repo_context.run_model import InitResult
from tests.support.repository import RepositoryFixture


class InitializationCleanlinessTests(unittest.TestCase):
    def test_verification_is_interleaved_and_unscanned_content_is_streamed(self) -> None:
        with RepositoryFixture() as repository:
            repository.write_text("source-a.txt", "source a\n")
            repository.write_text("source-b.txt", "source b\n")
            repository.write_bytes("package-lock.json", b"x" * 2_000_000)
            repository.commit("source")
            read_paths: list[str] = []
            hashed_paths: list[str] = []
            events: list[str] = []
            read_content = inventory_module.read_worktree_bytes
            hash_content = inventory_module._hash_regular_blob
            classify_content = sizes_module.classify_content

            def record_read(
                repository_handle: RepositoryHandle,
                entry: InventoryEntry,
            ) -> bytes:
                read_paths.append(entry.path)
                events.append(f"read:{entry.path}")
                return read_content(repository_handle, entry)

            def record_hash(
                root: Path,
                entry: InventoryEntry,
                algorithm: str,
            ) -> str:
                hashed_paths.append(entry.path)
                return hash_content(root, entry, algorithm)

            def record_classification(raw: bytes) -> ClassifiedContent:
                events.append(f"classify:{raw.decode('ascii').strip().replace(' ', '-')}.txt")
                return classify_content(raw)

            with (
                mock.patch.object(
                    inventory_module,
                    "read_worktree_bytes",
                    side_effect=record_read,
                ),
                mock.patch.object(
                    inventory_module,
                    "_hash_regular_blob",
                    side_effect=record_hash,
                ),
                mock.patch.object(
                    sizes_module,
                    "classify_content",
                    side_effect=record_classification,
                ),
            ):
                outcome = initialization.initialize_repository(repository.root)

            self.assertIsInstance(outcome, InitResult)
            self.assertEqual(read_paths, ["source-a.txt", "source-b.txt"])
            self.assertEqual(hashed_paths, ["package-lock.json"])
            self.assertEqual(
                events,
                [
                    "read:source-a.txt",
                    "classify:source-a.txt",
                    "read:source-b.txt",
                    "classify:source-b.txt",
                ],
            )


if __name__ == "__main__":
    unittest.main()
