from __future__ import annotations

import unittest
from dataclasses import replace

from raften.config import starter_policy
from raften.diagnostics import (
    CFG_INCONSISTENT,
    DOC_AUTHORED_SYMLINK,
    DOC_FRAGMENT_MISSING,
    DOC_LOCAL_TARGET_MISSING,
    DOC_MISSING_CHILD_INDEX_LINK,
    DOC_MISSING_DIRECTORY_INDEX,
    DOC_MISSING_ENTRYPOINT,
    DOC_MISSING_ENTRYPOINT_LINK,
    DOC_MISSING_SIBLING_LINK,
    DOC_UNREACHABLE,
    DOC_UNSAFE_DESTINATION,
    DOC_TEXT_UNAVAILABLE,
)
from raften.docs import (
    compile_documentation_policy,
    documentation_text_paths,
    evaluate_documentation,
)
from raften.model import (
    ContentState,
    DocumentationEdge,
    DocumentationSettings,
    Entrypoint,
    InventoryEntry,
    InventorySource,
    FileAssessment,
    TextDocument,
    WorktreeKind,
)


def regular(path: str, text: str) -> tuple[InventoryEntry, TextDocument]:
    encoded = text.encode("utf-8")
    return (
        InventoryEntry(
            path,
            InventorySource.TRACKED,
            WorktreeKind.REGULAR,
            size_bytes=len(encoded),
        ),
        TextDocument(path, text, len(encoded)),
    )


def policy_with(
    *,
    roots: tuple[str, ...] = ("docs/index.md",),
    exclude: tuple[str, ...] = (),
    entrypoints: tuple[Entrypoint, ...] = (),
    directory_indexes: bool = True,
    sibling_links: bool = True,
    child_links: bool = True,
    reachability: bool = True,
    local_targets: bool = True,
    fragments: bool = True,
    allow_symlinks: bool = False,
):
    return replace(
        starter_policy(),
        documentation=DocumentationSettings(
            roots,
            exclude,
            directory_indexes,
            sibling_links,
            child_links,
            reachability,
            local_targets,
            fragments,
            allow_symlinks,
        ),
        entrypoints=entrypoints,
    )


def evaluate(policy, files: dict[str, str], extras: tuple[InventoryEntry, ...] = ()):
    pairs = tuple(regular(path, text) for path, text in files.items())
    entries = tuple(item[0] for item in pairs) + extras
    documents = tuple(item[1] for item in pairs)
    compiled = compile_documentation_policy(policy)
    return evaluate_documentation(compiled, entries, documents)


class DocumentationHierarchyTests(unittest.TestCase):
    def test_clean_nested_hierarchy_builds_sorted_direct_edges(self) -> None:
        result = evaluate(
            policy_with(),
            {
                "docs/api/topic.md": "# Topic\n",
                "docs/index.md": "[Guide](guide.md)\n[API](api/)\n",
                "docs/guide.md": "# Guide\n",
                "docs/api/index.md": "[Topic](topic.md)\n",
            },
        )

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.governed_paths, (
            "docs/api/index.md",
            "docs/api/topic.md",
            "docs/guide.md",
            "docs/index.md",
        ))
        self.assertEqual(tuple(item.path for item in result.directories), ("docs", "docs/api"))
        self.assertEqual(
            tuple((edge.source_path, edge.target_path) for edge in result.edges),
            (
                ("docs/api/index.md", "docs/api/topic.md"),
                ("docs/index.md", "docs/api/index.md"),
                ("docs/index.md", "docs/guide.md"),
            ),
        )
        self.assertEqual(result.unreachable_paths, ())

    def test_repository_root_index_uses_an_explicit_empty_directory_sentinel(self) -> None:
        result = evaluate(
            policy_with(roots=("index.md",)),
            {
                "index.md": "[Docs](docs/)\n",
                "docs/index.md": "[Topic](topic.md)\n",
                "docs/topic.md": "# Topic\n",
            },
        )

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(tuple(item.path for item in result.directories), ("", "docs"))
        self.assertEqual(result.directories[0].index_path, "index.md")

    def test_empty_intermediate_ancestor_requires_index_routes_and_reachability(self) -> None:
        result = evaluate(
            policy_with(),
            {
                "docs/index.md": "# Docs\n",
                "docs/a/b/index.md": "[Topic](topic.md)\n",
                "docs/a/b/topic.md": "# Topic\n",
            },
        )

        by_code = {}
        for diagnostic in result.diagnostics:
            by_code.setdefault(diagnostic.code, []).append(diagnostic)
        self.assertEqual(
            tuple(item.location.path for item in by_code[DOC_MISSING_DIRECTORY_INDEX]),
            ("docs/a/index.md",),
        )
        self.assertEqual(
            tuple(item.location.path for item in by_code[DOC_MISSING_CHILD_INDEX_LINK]),
            ("docs/a/index.md", "docs/index.md"),
        )
        self.assertEqual(
            tuple(item.location.path for item in by_code[DOC_UNREACHABLE]),
            ("docs/a/b/index.md", "docs/a/b/topic.md"),
        )

    def test_only_direct_index_link_satisfies_sibling_requirement(self) -> None:
        result = evaluate(
            policy_with(),
            {
                "docs/index.md": "[Router](router.md)\n",
                "docs/router.md": "[Guide](guide.md)\n",
                "docs/guide.md": "# Guide\n",
            },
        )

        missing = tuple(
            item for item in result.diagnostics if item.code == DOC_MISSING_SIBLING_LINK
        )
        self.assertEqual(len(missing), 1)
        self.assertEqual(dict(missing[0].details)["target_path"], "docs/guide.md")
        self.assertEqual(result.unreachable_paths, ())

    def test_multiple_roots_exclusions_cycles_and_input_order_are_deterministic(self) -> None:
        policy = policy_with(
            roots=("docs/index.md", "reference/index.md"),
            exclude=("docs/excluded.md",),
            directory_indexes=False,
            sibling_links=False,
            child_links=False,
        )
        files = {
            "docs/index.md": "# Docs\n",
            "docs/b.md": "[A](a.md)\n",
            "docs/a.md": "[B](b.md)\n",
            "docs/excluded.md": "# Excluded\n",
            "reference/index.md": "# Reference\n",
        }
        forward = evaluate(policy, files)
        reverse = evaluate(policy, dict(reversed(tuple(files.items()))))

        self.assertEqual(forward, reverse)
        self.assertNotIn("docs/excluded.md", forward.governed_paths)
        self.assertEqual(forward.unreachable_paths, ("docs/a.md", "docs/b.md"))
        self.assertEqual(
            tuple(item.location.path for item in forward.diagnostics),
            ("docs/a.md", "docs/b.md"),
        )

    def test_exclusion_matching_a_configured_root_is_a_configuration_error_only(self) -> None:
        result = evaluate(policy_with(exclude=("docs/*.md",)), {"docs/index.md": "# Docs\n"})

        self.assertEqual(tuple(item.code for item in result.diagnostics), (CFG_INCONSISTENT,))
        self.assertEqual(result.diagnostics[0].field_path, "documentation.roots[0]")
        self.assertEqual(result.governed_paths, ())

    def test_missing_nonplaintext_and_nonregular_document_states_are_explicit(self) -> None:
        policy = policy_with(
            directory_indexes=False,
            sibling_links=False,
            child_links=False,
            reachability=False,
        )
        binary = InventoryEntry(
            "docs/binary.md",
            InventorySource.TRACKED,
            WorktreeKind.REGULAR,
            size_bytes=4,
        )
        other = InventoryEntry(
            "docs/pipe.md",
            InventorySource.TRACKED,
            WorktreeKind.OTHER,
        )
        deleted = InventoryEntry(
            "docs/deleted.md",
            InventorySource.DELETED,
            WorktreeKind.MISSING,
        )
        upper, upper_document = regular("docs/upper.MD", "# Upper\n")
        result = evaluate_documentation(
            compile_documentation_policy(policy),
            (binary, other, deleted, upper),
            (upper_document,),
            file_assessments=(
                FileAssessment(binary, None, ContentState.CONTAINS_NUL, 4, None),
            ),
        )

        unavailable = tuple(item for item in result.diagnostics if item.code == DOC_TEXT_UNAVAILABLE)
        self.assertEqual(
            tuple((item.location.path, dict(item.details)["state"]) for item in unavailable),
            (
                ("docs/binary.md", "contains_nul"),
                ("docs/index.md", "absent"),
                ("docs/pipe.md", "other"),
            ),
        )
        self.assertEqual(result.governed_paths, ("docs/binary.md",))

    def test_disabled_graph_flags_preserve_audit_data_without_policy_diagnostics(self) -> None:
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
                reachability=False,
                local_targets=False,
                fragments=False,
            ),
            {
                "docs/index.md": "[Broken](missing.md)\n",
                "docs/orphan.md": "# Orphan\n",
            },
        )

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(result.unreachable_paths, ("docs/orphan.md",))


class DocumentationTargetTests(unittest.TestCase):
    def test_targets_fragments_images_assets_and_unsafe_paths_are_distinct(self) -> None:
        asset = InventoryEntry(
            "assets/data.json",
            InventorySource.TRACKED,
            WorktreeKind.REGULAR,
            size_bytes=2,
        )
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "docs/index.md": """# Home
[Guide](guide.md#details)
[Missing](missing.md)
[Bad fragment](guide.md#absent)
![Missing image](images/missing.png)
[Asset](../assets/data.json)
[Unsafe](../../outside.md)
""",
                "docs/guide.md": "# Details\n",
            },
            (asset,),
        )

        self.assertEqual(
            tuple((edge.source_path, edge.target_path) for edge in result.edges),
            (("docs/index.md", "docs/guide.md"),),
        )
        self.assertEqual(
            tuple(item.code for item in result.diagnostics),
            (
                DOC_LOCAL_TARGET_MISSING,
                DOC_FRAGMENT_MISSING,
                DOC_LOCAL_TARGET_MISSING,
                DOC_UNSAFE_DESTINATION,
            ),
        )
        self.assertEqual(result.unreachable_paths, ())

    def test_implicit_directory_and_fragment_target_outside_the_graph_are_checked(self) -> None:
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "docs/index.md": "[API](api)\n[Reference](../reference.md#outside)\n",
                "docs/api/index.md": "# API\n",
                "reference.md": "# Outside\n",
            },
        )

        self.assertEqual(result.diagnostics, ())
        self.assertEqual(
            tuple((edge.source_path, edge.target_path) for edge in result.edges),
            (("docs/index.md", "docs/api/index.md"),),
        )

    def test_image_does_not_satisfy_sibling_navigation_or_reachability(self) -> None:
        result = evaluate(
            policy_with(),
            {
                "docs/index.md": "![Guide](guide.md)\n",
                "docs/guide.md": "# Guide\n",
            },
        )

        self.assertEqual(
            tuple(item.code for item in result.diagnostics),
            (DOC_UNREACHABLE, DOC_MISSING_SIBLING_LINK),
        )
        self.assertEqual(result.edges, ())

    def test_deleted_sparse_and_other_local_target_states_are_stable(self) -> None:
        extras = (
            InventoryEntry(
                "docs/deleted.md",
                InventorySource.DELETED,
                WorktreeKind.MISSING,
            ),
            InventoryEntry(
                "docs/sparse.md",
                InventorySource.TRACKED,
                WorktreeKind.MISSING,
            ),
            InventoryEntry(
                "docs/pipe.md",
                InventorySource.TRACKED,
                WorktreeKind.OTHER,
            ),
        )
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "docs/index.md": "[Deleted](deleted.md)\n[Sparse](sparse.md)\n[Pipe](pipe.md)\n",
            },
            extras,
        )

        targets = tuple(
            (dict(item.details)["target_path"], dict(item.details)["target_state"])
            for item in result.diagnostics
            if item.code == DOC_LOCAL_TARGET_MISSING
        )
        self.assertEqual(
            targets,
            (
                ("docs/deleted.md", "deleted"),
                ("docs/sparse.md", "sparse_missing"),
                ("docs/pipe.md", "other"),
            ),
        )

    def test_explicit_id_fragments_are_exact_and_case_sensitive(self) -> None:
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "docs/index.md": "[Exact](guide.md#Exact)\n[Wrong case](guide.md#exact)\n",
                "docs/guide.md": '<a id="Exact"></a>\n',
            },
        )

        fragments = tuple(item for item in result.diagnostics if item.code == DOC_FRAGMENT_MISSING)
        self.assertEqual(len(fragments), 1)
        self.assertEqual(dict(fragments[0].details)["fragment"], "exact")

    def test_non_markdown_entrypoint_does_not_supply_fragment_anchors(self) -> None:
        result = evaluate(
            policy_with(
                entrypoints=(Entrypoint("ENTRY", ("docs/index.md",)),),
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "ENTRY": "# Fake\n[Docs](docs/)\n",
                "docs/index.md": "[Entry](../ENTRY#fake)\n",
            },
        )

        self.assertEqual(tuple(item.code for item in result.diagnostics), (DOC_FRAGMENT_MISSING,))

    def test_nested_image_target_is_checked_independently_from_its_navigation_link(self) -> None:
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "docs/index.md": "[![Badge](missing.svg)](guide.md)\n",
                "docs/guide.md": "# Guide\n",
            },
        )

        self.assertEqual(tuple(item.code for item in result.diagnostics), (DOC_LOCAL_TARGET_MISSING,))
        self.assertEqual(result.edges, (DocumentationEdge("docs/index.md", "docs/guide.md"),))

    def test_navigation_inside_image_alt_text_cannot_create_a_graph_edge(self) -> None:
        asset = InventoryEntry(
            "docs/image.png",
            InventorySource.TRACKED,
            WorktreeKind.REGULAR,
            size_bytes=1,
        )
        result = evaluate(
            policy_with(
                directory_indexes=False,
                sibling_links=False,
                child_links=False,
            ),
            {
                "docs/index.md": "![Alt [Guide](guide.md)](image.png)\n",
                "docs/guide.md": "# Guide\n",
            },
            (asset,),
        )

        self.assertEqual(tuple(item.code for item in result.diagnostics), (DOC_UNREACHABLE,))
        self.assertEqual(result.edges, ())

    def test_entrypoints_use_navigation_links_but_do_not_become_graph_roots(self) -> None:
        policy = policy_with(
            entrypoints=(
                Entrypoint("README.md", ("docs/index.md", "docs/guide.md")),
                Entrypoint("MISSING.md", ("docs/index.md",)),
            ),
            directory_indexes=False,
            sibling_links=False,
            child_links=False,
        )
        result = evaluate(
            policy,
            {
                "README.md": "[Docs][root]\n\n[root]: docs/\n",
                "docs/index.md": "[Guide](guide.md)\n",
                "docs/guide.md": "# Guide\n",
            },
        )

        self.assertEqual(
            tuple(item.code for item in result.diagnostics),
            (DOC_MISSING_ENTRYPOINT, DOC_MISSING_ENTRYPOINT_LINK),
        )
        self.assertEqual(result.unreachable_paths, ())

    def test_authored_document_symlink_is_rejected_without_requesting_text(self) -> None:
        link = InventoryEntry(
            "docs/link.md",
            InventorySource.TRACKED,
            WorktreeKind.SYMLINK,
            symlink_target="../../outside.md",
        )
        policy = policy_with()
        compiled = compile_documentation_policy(policy)
        root_entry, root_document = regular("docs/index.md", "[Link](link.md)\n")

        self.assertEqual(
            documentation_text_paths(compiled, (root_entry, link)),
            frozenset({"docs/index.md"}),
        )
        result = evaluate_documentation(compiled, (root_entry, link), (root_document,))
        self.assertEqual(
            tuple(item.code for item in result.diagnostics),
            (DOC_AUTHORED_SYMLINK,),
        )


if __name__ == "__main__":
    unittest.main()
