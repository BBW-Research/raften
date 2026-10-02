"""Delimiter complexity is checked by character work, not wall-clock timing."""

import unittest
from unittest.mock import patch

from raften.markdown import _mask_ignored_regions, parse_markdown
from raften.markdown_links import heading_display_text
from raften.repository_errors import RepositoryAccessError


class CountedText(str):
    reads = 0

    def __getitem__(self, key):
        value = super().__getitem__(key)
        self.reads += len(value)
        return value

    def find(self, sub, start=0, end=None):
        end = len(self) if end is None else end
        found = super().find(sub, start, end)
        self.reads += (end if found < 0 else found + len(sub)) - start
        return found


class MarkdownResourceTests(unittest.TestCase):
    def test_unmatched_backtick_runs_are_indexed_once(self) -> None:
        text = CountedText("x " + " ".join("`" * n for n in range(1, 180)))
        self.assertEqual(_mask_ignored_regions(text), (text, text))
        self.assertLess(text.reads, 15 * len(text))

    def test_heading_unmatched_brackets_and_runs_have_linear_work(self) -> None:
        for value in ("[" * 4000, "*" * 4000, "_" * 4000, "~" * 4000,
                      " ".join("`" * n for n in range(1, 180))):
            text = CountedText(value)
            self.assertEqual(heading_display_text(text), value)
            self.assertLess(text.reads, 20 * len(text))

    def test_unmatched_runs_remain_whole_and_balanced_markup_is_preserved(self) -> None:
        self.assertEqual(heading_display_text("``a`"), "``a`")
        self.assertEqual(heading_display_text('**[text](a "(")** `code`'), "text code")
        self.assertEqual(heading_display_text(r"\**text*"), "*text")

    def test_byte_ceiling_is_inclusive_and_checked_before_masking(self) -> None:
        with patch("raften.markdown_limits.MAX_MARKDOWN_BYTES", 12):
            parse_markdown("docs/a.md", "é" * 6)
            with patch("raften.markdown._mask_ignored_regions") as mask:
                with self.assertRaises(RepositoryAccessError) as caught:
                    parse_markdown("docs/a.md", "é" * 7)
                mask.assert_not_called()
        self.assertEqual(caught.exception.diagnostics[0].code, "DOC012")
        self.assertEqual(caught.exception.diagnostics[0].location.path, "docs/a.md")

    def test_unclosed_destinations_exhaust_shared_work_budget(self) -> None:
        with patch("raften.markdown_limits.MAX_MARKDOWN_WORK", 200):
            with self.assertRaises(RepositoryAccessError) as caught:
                parse_markdown("docs/a.md", "[](" * 40)
        self.assertEqual(dict(caught.exception.diagnostics[0].details),
                         {"resource": "markdown_work", "limit": 200})

    def test_nested_headings_and_failed_html_share_the_work_ceiling(self) -> None:
        for text in ("# " + "[" * 20 + "x" + "]" * 20, "# " + "<a " * 40):
            with self.subTest(text=text):
                with patch("raften.markdown_limits.MAX_MARKDOWN_WORK", 200):
                    with self.assertRaises(RepositoryAccessError) as caught:
                        parse_markdown("docs/a.md", text)
                self.assertEqual(caught.exception.diagnostics[0].code, "DOC012")
