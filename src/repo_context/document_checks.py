"""Policy diagnostics and traversal over an immutable documentation graph."""

from __future__ import annotations

from collections import defaultdict, deque

from repo_context.diagnostics import (
    DOC_FRAGMENT_MISSING,
    DOC_LOCAL_TARGET_MISSING,
    DOC_MISSING_CHILD_INDEX_LINK,
    DOC_MISSING_DIRECTORY_INDEX,
    DOC_MISSING_ENTRYPOINT,
    DOC_MISSING_ENTRYPOINT_LINK,
    DOC_MISSING_SIBLING_LINK,
    DOC_TEXT_UNAVAILABLE,
    DOC_UNREACHABLE,
    DOC_UNSAFE_DESTINATION,
    policy_diagnostic,
)
from repo_context.model import (
    ContentState,
    Diagnostic,
    DocumentationDirectory,
    DocumentationEdge,
    DocumentationSettings,
    FileAssessment,
    InventoryEntry,
    InventorySource,
    JsonValue,
    Link,
    LinkKind,
    MarkdownDocument,
    Policy,
    Severity,
    WorktreeKind,
)


def content_diagnostics(
    policy: Policy,
    root_directories: tuple[str, ...],
    governed: tuple[str, ...],
    entries: dict[str, InventoryEntry],
    parsed: dict[str, MarkdownDocument],
    assessments: dict[str, FileAssessment],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    governed_set = set(governed)
    for path in governed:
        if path not in parsed:
            diagnostics.append(
                unavailable_diagnostic(
                    path,
                    "governed",
                    _content_state(path, entries, assessments),
                    _root_indexes(root_directories, path),
                )
            )
    for root_index, root in enumerate(policy.documentation.roots):
        if root in governed_set:
            continue
        entry = entries.get(root)
        if (
            entry is not None
            and entry.source is not InventorySource.DELETED
            and entry.kind not in {WorktreeKind.REGULAR, WorktreeKind.MISSING}
        ):
            continue
        diagnostics.append(
            unavailable_diagnostic(
                root,
                "root",
                _content_state(root, entries, assessments),
                (root_index,),
            )
        )
    return tuple(diagnostics)


def unavailable_diagnostic(
    path: str,
    role: str,
    state: str,
    root_indexes: tuple[int, ...],
) -> Diagnostic:
    return policy_diagnostic(
        DOC_TEXT_UNAVAILABLE,
        Severity.ERROR,
        "required Markdown plaintext content is unavailable",
        path=path,
        details=(
            ("role", role),
            ("state", state),
            ("root_indexes", root_indexes),
        ),
    )


def structure_diagnostics(
    settings: DocumentationSettings,
    directories: tuple[DocumentationDirectory, ...],
    governed: tuple[str, ...],
    navigation_targets: dict[str, frozenset[str]],
) -> tuple[Diagnostic, ...]:
    governed_set = set(governed)
    diagnostics: list[Diagnostic] = []
    for directory in directories:
        index_path = directory.index_path
        if settings.require_directory_indexes and index_path not in governed_set:
            diagnostics.append(
                policy_diagnostic(
                    DOC_MISSING_DIRECTORY_INDEX,
                    Severity.ERROR,
                    "documentation directory is missing its required index",
                    path=index_path,
                    details=(
                        ("directory", directory.path),
                        ("index_path", index_path),
                    ),
                )
            )
        direct_targets = navigation_targets.get(index_path, frozenset())
        if settings.require_sibling_links:
            for target in directory.document_paths:
                if target != index_path and target not in direct_targets:
                    diagnostics.append(
                        _missing_route_diagnostic(
                            DOC_MISSING_SIBLING_LINK,
                            "documentation index lacks a direct sibling link",
                            directory.path,
                            index_path,
                            target,
                        )
                    )
        if settings.require_child_index_links:
            for child in directory.child_paths:
                target = _index_path(child)
                if target not in direct_targets:
                    diagnostics.append(
                        _missing_route_diagnostic(
                            DOC_MISSING_CHILD_INDEX_LINK,
                            "documentation index lacks a direct child-index link",
                            directory.path,
                            index_path,
                            target,
                        )
                    )
    return tuple(diagnostics)


def _missing_route_diagnostic(
    code: str,
    message: str,
    directory: str,
    index_path: str,
    target: str,
) -> Diagnostic:
    return policy_diagnostic(
        code,
        Severity.ERROR,
        message,
        path=index_path,
        details=(
            ("directory", directory),
            ("index_path", index_path),
            ("target_path", target),
        ),
    )


def link_diagnostics(
    settings: DocumentationSettings,
    source_paths: tuple[str, ...],
    entries: dict[str, InventoryEntry],
    parsed: dict[str, MarkdownDocument],
) -> tuple[Diagnostic, ...]:
    if not settings.check_local_targets:
        return ()
    anchors = {
        path: frozenset(anchor.value for anchor in document.anchors)
        for path, document in parsed.items()
        if path.endswith(".md")
    }
    diagnostics: list[Diagnostic] = []
    for source_path in source_paths:
        document = parsed.get(source_path)
        if document is None:
            continue
        for link in document.links:
            if link.resolution_error is not None:
                diagnostics.append(
                    _link_diagnostic(
                        DOC_UNSAFE_DESTINATION,
                        "local-looking Markdown destination is unsafe",
                        link,
                        details=(
                            ("raw_destination", link.raw_destination),
                            ("reason", link.resolution_error.value),
                            ("link_kind", link.kind.value),
                        ),
                    )
                )
                continue
            target = link.target_path
            if target is None:
                continue
            entry = entries.get(target)
            if not _is_present_target(entry):
                diagnostics.append(
                    _link_diagnostic(
                        DOC_LOCAL_TARGET_MISSING,
                        "local Markdown target is not a current repository file",
                        link,
                        details=(
                            ("raw_destination", link.raw_destination),
                            ("target_path", target),
                            ("target_state", entry_state(entry)),
                            ("link_kind", link.kind.value),
                        ),
                    )
                )
                continue
            if settings.check_fragments and link.fragment is not None:
                if link.fragment not in anchors.get(target, frozenset()):
                    diagnostics.append(
                        _link_diagnostic(
                            DOC_FRAGMENT_MISSING,
                            "local Markdown fragment does not exist",
                            link,
                            details=(
                                ("target_path", target),
                                ("fragment", link.fragment),
                            ),
                        )
                    )
    return tuple(diagnostics)


def _link_diagnostic(
    code: str,
    message: str,
    link: Link,
    *,
    details: tuple[tuple[str, JsonValue], ...],
) -> Diagnostic:
    return policy_diagnostic(
        code,
        Severity.ERROR,
        message,
        path=link.source.path,
        line=link.source.line,
        column=link.source.column,
        details=details,
    )


def entrypoint_diagnostics(
    policy: Policy,
    entries: dict[str, InventoryEntry],
    parsed: dict[str, MarkdownDocument],
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for entrypoint_index, entrypoint in enumerate(policy.entrypoints):
        entry = entries.get(entrypoint.path)
        document = parsed.get(entrypoint.path)
        if not is_present_regular(entry) or document is None:
            diagnostics.append(
                policy_diagnostic(
                    DOC_MISSING_ENTRYPOINT,
                    Severity.ERROR,
                    "configured documentation entrypoint is unavailable",
                    path=entrypoint.path,
                    details=(
                        ("entrypoint_index", entrypoint_index),
                        (
                            "state",
                            "text_unavailable" if is_present_regular(entry) else entry_state(entry),
                        ),
                    ),
                )
            )
            continue
        targets = direct_navigation_targets(document)
        for target_index, target in enumerate(entrypoint.required_targets):
            if target not in targets:
                diagnostics.append(
                    policy_diagnostic(
                        DOC_MISSING_ENTRYPOINT_LINK,
                        Severity.ERROR,
                        "documentation entrypoint lacks a required direct navigation link",
                        path=entrypoint.path,
                        details=(
                            ("entrypoint_index", entrypoint_index),
                            ("target_index", target_index),
                            ("target_path", target),
                        ),
                    )
                )
    return tuple(diagnostics)


def documentation_edges(
    governed: tuple[str, ...],
    parsed: dict[str, MarkdownDocument],
) -> tuple[DocumentationEdge, ...]:
    governed_set = set(governed)
    edge_pairs = {
        (source, link.target_path)
        for source in governed
        for link in (() if parsed.get(source) is None else parsed[source].links)
        if link.kind is LinkKind.NAVIGATION
        and link.resolution_error is None
        and link.target_path in governed_set
    }
    return tuple(DocumentationEdge(source, target) for source, target in sorted(edge_pairs))


def unreachable_paths(
    roots: tuple[str, ...],
    governed: tuple[str, ...],
    edges: tuple[DocumentationEdge, ...],
) -> tuple[str, ...]:
    governed_set = set(governed)
    adjacency: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adjacency[edge.source_path].append(edge.target_path)
    reachable = set(root for root in roots if root in governed_set)
    pending = deque(sorted(reachable))
    while pending:
        source = pending.popleft()
        for target in adjacency[source]:
            if target not in reachable:
                reachable.add(target)
                pending.append(target)
    return tuple(sorted(governed_set.difference(reachable)))


def direct_navigation_targets(document: MarkdownDocument | None) -> frozenset[str]:
    if document is None:
        return frozenset()
    return frozenset(
        link.target_path
        for link in document.links
        if link.kind is LinkKind.NAVIGATION
        and link.resolution_error is None
        and link.target_path is not None
    )


def entry_state(entry: InventoryEntry | None) -> str:
    if entry is None:
        return "absent"
    if entry.source is InventorySource.DELETED:
        return "deleted"
    if entry.kind is WorktreeKind.MISSING:
        return "sparse_missing" if entry.source is InventorySource.TRACKED else "missing"
    return entry.kind.value


def is_present_regular(entry: InventoryEntry | None) -> bool:
    return (
        entry is not None
        and entry.source is not InventorySource.DELETED
        and entry.kind is WorktreeKind.REGULAR
    )


def _is_present_target(entry: InventoryEntry | None) -> bool:
    return (
        entry is not None
        and entry.source is not InventorySource.DELETED
        and entry.kind in {WorktreeKind.REGULAR, WorktreeKind.SYMLINK}
    )


def _content_state(
    path: str,
    entries: dict[str, InventoryEntry],
    assessments: dict[str, FileAssessment],
) -> str:
    assessment = assessments.get(path)
    if assessment is not None and assessment.content_state not in {None, ContentState.UNREAD}:
        return assessment.content_state.value
    entry = entries.get(path)
    if is_present_regular(entry):
        return "text_unavailable"
    return entry_state(entry)


def _root_indexes(root_directories: tuple[str, ...], path: str) -> tuple[int, ...]:
    return tuple(
        index
        for index, directory in enumerate(root_directories)
        if not directory or path.startswith(f"{directory}/")
    )


def _index_path(directory: str) -> str:
    return f"{directory}/index.md" if directory else "index.md"
