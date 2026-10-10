from __future__ import annotations

import unittest
from unittest import mock

from raften.docs import compile_documentation_policy, evaluate_documentation
from raften.document_checks import documentation_edges
from raften.diagnostic_limits import DiagnosticBuffer
from raften.diagnostics import operational_diagnostic
from raften.markdown import parse_markdown
from raften.model import TextDocument
from raften.repository_errors import RepositoryAccessError
from raften.run_model import CommandFailure
from raften.runner import run_repository
from tests.support.repository import RepositoryFixture
from tests.support.target import install_clean_target
from tests.support.sizes import TODAY, policy_with, regular


class MarkdownCountTests(unittest.TestCase):
    def test_adjacent_links_and_omitted_external_links_have_fixed_counts(self) -> None:
        for link in ("[x](z)", "[x](https://example.test)"):
            with self.subTest(link=link):
                with self.assertRaises(RepositoryAccessError) as caught:
                    parse_markdown("docs/index.md", link * 4097)
                self.assertEqual(caught.exception.diagnostics[0].code, "DOC012")

    def test_heading_and_html_candidates_are_counted_before_anchor_retention(self) -> None:
        for text in ("# x\n" * 4097, '<i id="x"></i>' * 4097):
            with self.subTest(kind=text[:20]):
                with self.assertRaises(RepositoryAccessError):
                    parse_markdown("docs/index.md", text)

    def test_multiple_documents_share_one_link_envelope(self) -> None:
        texts = (TextDocument("docs/index.md", "[x](z)" * 2, 12),
                 TextDocument("docs/a.md", "[x](z)" * 2, 12))
        with mock.patch("raften.markdown_limits.MAX_TOTAL_LINKS", 3, create=True):
            with self.assertRaises(RepositoryAccessError):
                evaluate_documentation(compile_documentation_policy(policy_with()),
                                       tuple(regular(item.path, item.size_bytes) for item in texts), texts)

    def test_reference_destination_normalization_is_charged(self) -> None:
        text = '[x]: ' + "a" * 100 + '\n\n' + '[x] ' * 10
        with mock.patch("raften.markdown_limits.MAX_MARKDOWN_WORK", 500):
            with self.assertRaises(RepositoryAccessError):
                parse_markdown("docs/index.md", text)

    def test_inclusive_counts_and_shared_anchor_budget(self) -> None:
        with mock.patch("raften.markdown_limits.MAX_DOCUMENT_LINKS", 2):
            self.assertEqual(len(parse_markdown("a.md", "[x](z)" * 2).links), 2)
        texts = (TextDocument("docs/index.md", "# x\n" * 2, 8),
                 TextDocument("docs/a.md", "# x\n" * 2, 8))
        with mock.patch("raften.markdown_limits.MAX_TOTAL_ANCHORS", 3):
            with self.assertRaises(RepositoryAccessError):
                evaluate_documentation(compile_documentation_policy(policy_with()),
                                       tuple(regular(item.path, item.size_bytes) for item in texts), texts)

    def test_retained_destination_bytes_and_distinct_graph_edges_are_bounded(self) -> None:
        with mock.patch("raften.markdown_limits.MAX_DOCUMENT_LINK_BYTES", 40):
            with self.assertRaises(RepositoryAccessError):
                parse_markdown("docs/a.md", "[x](" + "z" * 30 + ")")
        governed = ("a.md", "b.md", "c.md")
        with mock.patch("raften.markdown_limits.MAX_GRAPH_EDGES", 1):
            parsed = {"a.md": parse_markdown("a.md", "[b](b.md)" * 3)}
            self.assertEqual(len(documentation_edges(governed, parsed)), 1)
            parsed["a.md"] = parse_markdown("a.md", "[b](b.md)[c](c.md)")
            with self.assertRaises(RepositoryAccessError):
                documentation_edges(governed, parsed)

    def test_directory_metadata_is_bounded_before_retention(self) -> None:
        with mock.patch("raften.markdown_limits.MAX_DIRECTORY_RECORDS", 2):
            with self.assertRaises(RepositoryAccessError):
                evaluate_documentation(compile_documentation_policy(policy_with()),
                                       (regular("docs/a/b/c.md", 0),), ())

    def test_diagnostic_producer_and_final_aggregation_stop_at_the_ceiling(self) -> None:
        consumed = []
        def values():
            for index in range(20):
                consumed.append(index)
                yield operational_diagnostic("GIT010", "bounded")
        with mock.patch("raften.resource_limits.MAX_COMMAND_DIAGNOSTICS", 2):
            with self.assertRaises(RepositoryAccessError):
                DiagnosticBuffer(values())
        self.assertEqual(consumed, [0, 1, 2])
        with RepositoryFixture() as repository:
            install_clean_target(repository)
            repository.write_text("docs/index.md", (repository.root / "docs/index.md").read_text()
                                  + "[missing](gone.md)\n")
            # Each stage has one diagnostic; their aggregate exceeds one.
            with mock.patch("raften.resource_limits.MAX_COMMAND_DIAGNOSTICS", 1):
                outcome = run_repository(repository.root, evaluation_date=TODAY)
        self.assertIsInstance(outcome, CommandFailure)
        self.assertEqual(outcome.diagnostics[0].code, "GIT010")


if __name__ == "__main__":
    unittest.main()
