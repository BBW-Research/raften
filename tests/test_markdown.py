from __future__ import annotations

import unittest
from unittest import mock

from raften import markdown, markdown_links
from raften.markdown import parse_markdown
from raften.model import AnchorKind, LinkKind


class MarkdownLinkExtractionTests(unittest.TestCase):
    def test_inline_destinations_are_normalized_without_losing_source_details(self) -> None:
        document = parse_markdown(
            "docs/api/index.md",
            "\n".join(
                (
                    "[inline](guide.md)",
                    "[angle](<guide page.md>)",
                    '[title](titled.md "A title")',
                    "[query](search%20page.md?mode=full#results%20list)",
                    "[directory](child/)",
                    "[parent](../overview.md)",
                    r"[escaped](guide\(v1\).md)",
                    "![image](images/diagram%20one.svg)",
                    "[self](#top)",
                    "[empty]()",
                    "[remote](https://example.com/docs)",
                )
            ),
        )

        self.assertEqual(
            tuple(
                (
                    link.kind,
                    link.target_path,
                    link.fragment,
                    link.resolution_error,
                )
                for link in document.links
            ),
            (
                (LinkKind.NAVIGATION, "docs/api/guide.md", None, None),
                (LinkKind.NAVIGATION, "docs/api/guide page.md", None, None),
                (LinkKind.NAVIGATION, "docs/api/titled.md", None, None),
                (
                    LinkKind.NAVIGATION,
                    "docs/api/search page.md",
                    "results list",
                    None,
                ),
                (LinkKind.NAVIGATION, "docs/api/child/index.md", None, None),
                (LinkKind.NAVIGATION, "docs/overview.md", None, None),
                (LinkKind.NAVIGATION, "docs/api/guide(v1).md", None, None),
                (
                    LinkKind.IMAGE,
                    "docs/api/images/diagram one.svg",
                    None,
                    None,
                ),
                (LinkKind.NAVIGATION, "docs/api/index.md", "top", None),
                (LinkKind.NAVIGATION, "docs/api/index.md", None, None),
            ),
        )
        self.assertEqual(document.links[0].raw_destination, "guide.md")
        self.assertEqual(document.links[0].source.line, 1)
        self.assertEqual(document.links[0].source.column, 1)
        self.assertEqual(document.links[7].source.column, 2)

    def test_full_collapsed_shortcut_and_image_references_use_first_definition(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            """[Guide][guide]
[Collapsed][]
[Shortcut]
![Diagram][asset]

[GUIDE]: guide.md
[collapsed]: <space page.md#intro>
[shortcut]: shortcut.md "A title"
[asset]: images/diagram.svg
[guide]: ignored.md
""",
        )

        self.assertEqual(
            tuple((link.kind, link.target_path, link.fragment) for link in document.links),
            (
                (LinkKind.NAVIGATION, "docs/guide.md", None),
                (LinkKind.NAVIGATION, "docs/space page.md", "intro"),
                (LinkKind.NAVIGATION, "docs/shortcut.md", None),
                (LinkKind.IMAGE, "docs/images/diagram.svg", None),
            ),
        )

    def test_reference_labels_collapse_whitespace_and_escaped_brackets_are_balanced(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[A \\] label][ a\t  ]\r\n\r\n[A ]: guide.md\r\n",
        )

        self.assertEqual(tuple(link.target_path for link in document.links), ("docs/guide.md",))
        self.assertEqual(document.links[0].source.line, 1)
        self.assertEqual(document.links[0].source.column, 1)

    def test_code_fences_code_spans_comments_and_escaped_openers_are_ignored(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            r"""`[inline](inline.md)` and ``[long](long.md)``

```markdown
[fenced](fenced.md)
```

~~~
[tilde](tilde.md)
~~~

<!-- [comment](comment.md)
[continued](continued.md) -->
\[escaped](escaped.md)
[real](real.md)
""",
        )

        self.assertEqual(
            tuple(link.target_path for link in document.links),
            ("docs/real.md",),
        )
        self.assertEqual(document.links[0].source.line, 14)

    def test_fence_markers_inside_comments_and_comment_markers_inside_fences_do_not_leak_state(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            """<!--
```
-->
[After comment](after-comment.md)

```text
<!--
```
[After fence](after-fence.md)
""",
        )

        self.assertEqual(
            tuple(link.target_path for link in document.links),
            ("docs/after-comment.md", "docs/after-fence.md"),
        )

    def test_cr_and_crlf_are_physical_lines_for_state_and_source_locations(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "~~~\r[hidden](hidden.md)\r~~~\r[one](one.md)\r\n[two](two.md)\r[ref][target]\r[target]: ref.md\r",
        )

        self.assertEqual(
            tuple((link.target_path, link.source.line) for link in document.links),
            (
                ("docs/one.md", 4),
                ("docs/two.md", 5),
                ("docs/ref.md", 6),
            ),
        )

    def test_angle_destination_cannot_cross_a_cr_physical_line(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[ordinary](<first\rsecond>)\r[real](real.md)\r",
        )

        self.assertEqual(
            tuple((link.target_path, link.source.line) for link in document.links),
            (("docs/real.md", 3),),
        )

    def test_comment_markers_inside_code_and_backticks_inside_comments_do_not_leak_state(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            """`<!--` [After code](after-code.md)
<!-- `code` --> [After comment](after-comment.md)
""",
        )

        self.assertEqual(
            tuple(link.target_path for link in document.links),
            ("docs/after-code.md", "docs/after-comment.md"),
        )

    def test_escaped_comment_opener_is_ordinary_text(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            r"\<!-- [Visible](visible.md)",
        )

        self.assertEqual(
            tuple(link.target_path for link in document.links),
            ("docs/visible.md",),
        )

    def test_unsafe_local_destinations_are_retained_but_external_links_are_omitted(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "\n".join(
                (
                    "[safe](../README.md)",
                    "[escape](../../outside.md)",
                    "[absolute](/README.md)",
                    "[encoded escape](%2e%2e/%2e%2e/outside.md)",
                    "[bad percent](bad%ZZ.md)",
                    "[bad utf8](bad%FF.md)",
                    r"[backslash](bad\path.md)",
                    "[remote](https://example.com)",
                    "[mail](mailto:team@example.com)",
                    "[network](//example.com/path)",
                )
            ),
        )

        self.assertEqual(document.links[0].target_path, "README.md")
        self.assertIsNone(document.links[0].resolution_error)
        self.assertEqual(len(document.links), 7)
        for link in document.links[1:]:
            self.assertIsNone(link.target_path)
            self.assertIsNotNone(link.resolution_error)

    def test_unicode_and_encoded_uri_components_are_decoded_before_path_validation(self) -> None:
        document = parse_markdown(
            "docs/指南/index.md",
            "\n".join(
                (
                    "[raw](章节.md)",
                    "[unicode](%E7%AB%A0%E8%8A%82.md#%E8%AF%A6%E6%83%85)",
                    "[slash](nested%2Fpage.md)",
                    "[question](what%3F.md)",
                    "[hash](hash%23.md)",
                    "[parent](%2e%2e/overview.md)",
                    "[nul](bad%00.md)",
                )
            ),
        )

        self.assertEqual(
            tuple((link.target_path, link.fragment) for link in document.links[:-1]),
            (
                ("docs/指南/章节.md", None),
                ("docs/指南/章节.md", "详情"),
                ("docs/指南/nested/page.md", None),
                ("docs/指南/what?.md", None),
                ("docs/指南/hash#.md", None),
                ("docs/overview.md", None),
            ),
        )
        self.assertIsNotNone(document.links[-1].resolution_error)

    def test_path_ending_in_parent_component_can_resolve_to_repository_index(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[Root](../tmp/..)\n",
            known_directories=frozenset({"docs", "tmp"}),
        )

        self.assertEqual(document.links[0].target_path, "index.md")
        self.assertTrue(document.links[0].directory_hint)

    def test_duplicate_occurrences_are_preserved_in_source_order(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[First](guide.md) and [Second](guide.md)\n",
        )

        self.assertEqual(
            tuple((link.target_path, link.source.column) for link in document.links),
            (("docs/guide.md", 1), ("docs/guide.md", 23)),
        )

    def test_percent_entity_scheme_and_drive_transforms_follow_the_safe_order(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "\n".join(
                (
                    "[literal percent](&percnt;2e&percnt;2e/out.md)",
                    "[encoded entity](%26sol%3Broot.md)",
                    "[encoded external](https%3A%2F%2Fexample.com)",
                    "[drive](C:secret.md)",
                    "[literal remote percent](https://example.com/%ZZ)",
                    "[network remote percent](//example.com/%ZZ)",
                    "[remote drive segment](https://example.com/C:/guide)",
                    "[encoded remote drive segment](https%3A%2F%2Fexample.com%2FC%3A%2Fguide)",
                )
            ),
        )

        self.assertEqual(len(document.links), 3)
        self.assertEqual(document.links[0].target_path, "docs/%2e%2e/out.md")
        self.assertIsNone(document.links[0].resolution_error)
        self.assertIsNone(document.links[1].target_path)
        self.assertIsNotNone(document.links[1].resolution_error)
        self.assertEqual(document.links[2].raw_destination, "C:secret.md")
        self.assertIsNotNone(document.links[2].resolution_error)

    def test_image_nested_in_navigation_label_is_a_distinct_link_occurrence(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[![Badge](missing.svg)](guide.md)\n",
        )

        self.assertEqual(
            tuple((link.kind, link.target_path, link.source.column) for link in document.links),
            (
                (LinkKind.NAVIGATION, "docs/guide.md", 1),
                (LinkKind.IMAGE, "docs/missing.svg", 3),
            ),
        )

    def test_links_and_images_inside_ordinary_balanced_brackets_are_retained(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[outer [Guide](guide.md)]\n[outer ![Badge][badge]]\n\n[badge]: badge.svg\n",
        )

        self.assertEqual(
            tuple((link.kind, link.target_path) for link in document.links),
            (
                (LinkKind.NAVIGATION, "docs/guide.md"),
                (LinkKind.IMAGE, "docs/badge.svg"),
            ),
        )

    def test_nested_navigation_is_not_an_independent_link_occurrence(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "[Outer [Inner](inner.md)](outer.md)\n",
        )

        self.assertEqual(
            tuple((link.kind, link.target_path) for link in document.links),
            ((LinkKind.NAVIGATION, "docs/outer.md"),),
        )

    def test_navigation_inside_image_alt_text_is_not_a_link_occurrence(self) -> None:
        document = parse_markdown(
            "docs/index.md",
            "![Alt [Guide](guide.md)](image.png)\n",
        )

        self.assertEqual(
            tuple((link.kind, link.target_path) for link in document.links),
            ((LinkKind.IMAGE, "docs/image.png"),),
        )

    def test_deep_balanced_ordinary_brackets_have_bounded_reference_label_work(self) -> None:
        original = markdown_links._normalize_reference_label
        normalized_characters = 0

        def counting_normalizer(value: str) -> str:
            nonlocal normalized_characters
            normalized_characters += len(value)
            return original(value)

        text = "[" * 4_000 + "target" + "]" * 4_000 + "\n[target]: target.md\n"
        with mock.patch.object(
            markdown_links,
            "_normalize_reference_label",
            counting_normalizer,
        ):
            document = parse_markdown("docs/index.md", text)

        self.assertEqual(tuple(link.target_path for link in document.links), ("docs/target.md",))
        self.assertLess(normalized_characters, 600_000)

    def test_reference_labels_are_bounded_to_999_characters(self) -> None:
        supported = "a" * 999
        too_long = "b" * 1_000
        document = parse_markdown(
            "docs/index.md",
            f"[Supported][{supported}]\n[Too long][{too_long}]\n[{supported}]: supported.md\n[{too_long}]: ignored.md\n",
        )

        self.assertEqual(
            tuple(link.target_path for link in document.links),
            ("docs/supported.md",),
        )


class MarkdownAnchorExtractionTests(unittest.TestCase):
    def test_atx_setext_duplicate_unicode_and_explicit_anchors_are_deterministic(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            """# Hello, World!
## Hello, World!

Setext Title
------------

### 中文 标题
<a id="explicit"></a>
<span id='quoted-id'>text</span>
<div id=bare-id>text</div>
""",
        )

        self.assertEqual(
            tuple((anchor.kind, anchor.value) for anchor in document.anchors),
            (
                (AnchorKind.HEADING, "hello-world"),
                (AnchorKind.HEADING, "hello-world-1"),
                (AnchorKind.HEADING, "setext-title"),
                (AnchorKind.HEADING, "中文-标题"),
                (AnchorKind.EXPLICIT, "explicit"),
                (AnchorKind.EXPLICIT, "quoted-id"),
                (AnchorKind.EXPLICIT, "bare-id"),
            ),
        )
        self.assertEqual(document.anchors[0].source.line, 1)
        self.assertEqual(document.anchors[2].source.line, 4)
        self.assertEqual(document.anchors[4].source.line, 8)

    def test_literal_suffix_and_explicit_id_collisions_allocate_the_first_free_slug(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            """# Name
# Name-1
# Name
<a id="name-2"></a>
# Name
`<span id="ignored-code"></span>`
<!-- <span id="ignored-comment"></span> -->
""",
        )

        self.assertEqual(
            tuple(anchor.value for anchor in document.anchors),
            ("name", "name-1", "name-2", "name-2", "name-3"),
        )

    def test_heading_display_text_keeps_labels_code_entities_unicode_and_symbols(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            "# Use *strong* `code` [Guide](guide.md) &amp; <span>HTML</span> 🚀\n# snake_case and ~~strike~~\n# 2 < 3 > 1\n# !!!\n",
        )

        self.assertEqual(
            tuple(anchor.value for anchor in document.anchors),
            (
                "use-strong-code-guide-html-🚀",
                "snake_case-and-strike",
                "2-<-3->-1",
            ),
        )

    def test_heading_display_removes_supported_inline_html_spans(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            "# A <!DOCTYPE html> B\n# A <?target data?> B\n# A <![CDATA[raw]]> B\n",
        )

        self.assertEqual(
            tuple(anchor.value for anchor in document.anchors),
            ("a-b", "a-b-1", "a-b-2"),
        )

    def test_deeply_nested_heading_markup_does_not_use_unbounded_recursion(self) -> None:
        nested = "[" * 2_000 + "Heading" + "]" * 2_000
        document = parse_markdown("docs/guide.md", f"# {nested}\n")

        self.assertEqual(tuple(anchor.value for anchor in document.anchors), ("heading",))

    def test_multiline_inline_code_cannot_create_block_heading_anchors(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            "`code\n# Fake ATX\n`\n\n``code\nFake setext\n---\n``\n\n# Real `code`\n",
        )

        self.assertEqual(tuple(anchor.value for anchor in document.anchors), ("real-code",))

    def test_link_syntax_and_escaped_tags_cannot_create_explicit_anchors(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            """[angle](<span id=angle>)
[title](guide.md "<span id=title>")
[reference][defined]

[defined]: <span id=definition>
![<span id=image-alt>](image.svg)
\\<span id=escaped>
<https://example.com id=autolink>
<user@example.com id=email>
<x+y id=malformed>
<span id=real></span>
""",
        )

        self.assertEqual(tuple(anchor.value for anchor in document.anchors), ("real",))

    def test_nested_heading_markup_decodes_character_references_once(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            "# &amp;amp;\n# **&amp;amp;**\n# [&amp;amp;](guide.md)\n",
        )

        self.assertEqual(
            tuple(anchor.value for anchor in document.anchors),
            ("amp", "amp-1", "amp-2"),
        )

    def test_heading_display_distinguishes_resolved_and_unresolved_full_references(self) -> None:
        document = parse_markdown(
            "docs/guide.md",
            "# [Guide][defined]\n# [Guide][missing]\n\n[defined]: target.md\n",
        )

        self.assertEqual(
            tuple(anchor.value for anchor in document.anchors),
            ("guide", "guidemissing"),
        )

    def test_duplicate_heading_allocation_uses_a_bounded_number_of_membership_probes(self) -> None:
        class CountingSet(set[str]):
            probes = 0

            def __contains__(self, value: object) -> bool:
                type(self).probes += 1
                return super().__contains__(value)

        with mock.patch.object(markdown, "set", CountingSet, create=True):
            document = markdown.parse_markdown(
                "docs/guide.md",
                "# Same\n" * 200,
            )

        self.assertEqual(document.anchors[-1].value, "same-199")
        self.assertLess(CountingSet.probes, 600)


if __name__ == "__main__":
    unittest.main()
