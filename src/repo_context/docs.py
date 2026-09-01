"""Documentation discovery and immutable graph construction."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from repo_context.diagnostics import (
    CFG_INCONSISTENT,
    DOC_AUTHORED_SYMLINK,
    DOC_UNREACHABLE,
    diagnostic_sort_key,
    policy_diagnostic,
)
from repo_context.document_checks import (
    content_diagnostics,
    direct_navigation_targets,
    documentation_edges,
    entrypoint_diagnostics,
    is_present_regular,
    link_diagnostics,
    structure_diagnostics,
    unavailable_diagnostic,
    unreachable_paths,
)
from repo_context.markdown import parse_markdown
from repo_context.matcher import CompiledPattern, compile_pattern, matches_any
from repo_context.model import (
    Diagnostic,
    DocumentationDirectory,
    DocumentationEvaluation,
    FileAssessment,
    InventoryEntry,
    InventorySource,
    MarkdownDocument,
    Policy,
    Severity,
    TextDocument,
    WorktreeKind,
)


@dataclass(frozen=True, slots=True)
class CompiledDocumentationPolicy:
    policy: Policy
    exclusions: tuple[CompiledPattern, ...]
    root_directories: tuple[str, ...]


def compile_documentation_policy(policy: Policy) -> CompiledDocumentationPolicy:
    """Compile documentation exclusions once for repeated path evaluation."""

    return CompiledDocumentationPolicy(
        policy,
        tuple(compile_pattern(pattern) for pattern in policy.documentation.exclude),
        tuple(_parent_path(root) for root in policy.documentation.roots),
    )


def documentation_text_paths(
    compiled: CompiledDocumentationPolicy,
    entries: Sequence[InventoryEntry],
) -> frozenset[str]:
    """Select regular Markdown and entrypoint text for one shared content read."""

    entrypoints = frozenset(item.path for item in compiled.policy.entrypoints)
    return frozenset(
        entry.path
        for entry in entries
        if is_present_regular(entry)
        and (entry.path.endswith(".md") or entry.path in entrypoints)
    )


def evaluate_documentation(
    compiled: CompiledDocumentationPolicy,
    entries: Sequence[InventoryEntry],
    text_documents: Sequence[TextDocument],
    *,
    file_assessments: Sequence[FileAssessment] = (),
) -> DocumentationEvaluation:
    """Build and check a documentation graph without repository access."""

    ordered_entries = tuple(sorted(entries, key=lambda item: item.path))
    entries_by_path = {entry.path: entry for entry in ordered_entries}
    documents_by_path = _unique_text_documents(text_documents)
    assessments_by_path = {item.entry.path: item for item in file_assessments}
    configuration_diagnostics = _root_exclusion_diagnostics(compiled)
    if configuration_diagnostics:
        return DocumentationEvaluation(
            roots=compiled.policy.documentation.roots,
            governed_paths=(),
            documents=(),
            directories=(),
            edges=(),
            diagnostics=tuple(sorted(configuration_diagnostics, key=diagnostic_sort_key)),
            unreachable_paths=(),
        )

    known_directories = _known_directories(ordered_entries)
    parsed = tuple(
        parse_markdown(
            path,
            document.text,
            known_directories=known_directories,
        )
        for path, document in sorted(documents_by_path.items())
    )
    parsed_by_path = {document.path: document for document in parsed}

    diagnostics: list[Diagnostic] = []
    governed, discovery_diagnostics = _discover_governed(compiled, ordered_entries)
    diagnostics.extend(discovery_diagnostics)
    diagnostics.extend(
        content_diagnostics(
            compiled.policy,
            compiled.root_directories,
            governed,
            entries_by_path,
            parsed_by_path,
            assessments_by_path,
        )
    )
    directories = _build_directories(compiled, governed)
    navigation_targets = {
        path: direct_navigation_targets(parsed_by_path.get(path))
        for path in set(governed).union(item.index_path for item in directories)
    }
    diagnostics.extend(
        structure_diagnostics(
            compiled.policy.documentation,
            directories,
            governed,
            navigation_targets,
        )
    )

    checked_sources = tuple(
        sorted(set(governed).union(item.path for item in compiled.policy.entrypoints))
    )
    diagnostics.extend(
        link_diagnostics(
            compiled.policy.documentation,
            checked_sources,
            entries_by_path,
            parsed_by_path,
        )
    )
    diagnostics.extend(
        entrypoint_diagnostics(compiled.policy, entries_by_path, parsed_by_path)
    )

    edges = documentation_edges(governed, parsed_by_path)
    unreachable = unreachable_paths(compiled.policy.documentation.roots, governed, edges)
    if compiled.policy.documentation.require_root_reachability:
        diagnostics.extend(
            policy_diagnostic(
                DOC_UNREACHABLE,
                Severity.ERROR,
                "governed Markdown document is unreachable from every configured root",
                path=path,
                details=(("roots", compiled.policy.documentation.roots),),
                hint="add a navigation route from a configured documentation root",
            )
            for path in unreachable
        )
    return DocumentationEvaluation(
        roots=compiled.policy.documentation.roots,
        governed_paths=governed,
        documents=parsed,
        directories=directories,
        edges=edges,
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
        unreachable_paths=unreachable,
    )


def _root_exclusion_diagnostics(
    compiled: CompiledDocumentationPolicy,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for root_index, root in enumerate(compiled.policy.documentation.roots):
        for exclusion_index, exclusion in enumerate(compiled.exclusions):
            if matches_any((exclusion,), root):
                diagnostics.append(
                    policy_diagnostic(
                        CFG_INCONSISTENT,
                        Severity.ERROR,
                        "documentation root is matched by an exclusion pattern",
                        field_path=f"documentation.roots[{root_index}]",
                        details=(
                            ("root_index", root_index),
                            ("root", root),
                            ("exclusion_index", exclusion_index),
                            ("exclusion_pattern", exclusion.source),
                        ),
                    )
                )
    return tuple(diagnostics)


def _discover_governed(
    compiled: CompiledDocumentationPolicy,
    entries: Sequence[InventoryEntry],
) -> tuple[tuple[str, ...], tuple[Diagnostic, ...]]:
    governed: list[str] = []
    diagnostics: list[Diagnostic] = []
    for entry in entries:
        if not entry.path.endswith(".md") or not _under_any_root(compiled, entry.path):
            continue
        if matches_any(compiled.exclusions, entry.path):
            continue
        if entry.source is InventorySource.DELETED or entry.kind is WorktreeKind.MISSING:
            continue
        root_indexes = _root_indexes(compiled, entry.path)
        if entry.kind is WorktreeKind.SYMLINK:
            if not compiled.policy.documentation.allow_authored_symlinks:
                diagnostics.append(
                    policy_diagnostic(
                        DOC_AUTHORED_SYMLINK,
                        Severity.ERROR,
                        "governed authored Markdown may not be a symlink",
                        path=entry.path,
                        details=(
                            ("kind", entry.kind.value),
                            ("root_indexes", root_indexes),
                        ),
                    )
                )
            else:
                diagnostics.append(
                    unavailable_diagnostic(
                        entry.path,
                        "governed",
                        "symlink",
                        root_indexes,
                    )
                )
            continue
        if entry.kind is not WorktreeKind.REGULAR:
            diagnostics.append(
                unavailable_diagnostic(
                    entry.path,
                    "governed",
                    entry.kind.value,
                    root_indexes,
                )
            )
            continue
        governed.append(entry.path)
    return tuple(sorted(governed)), tuple(diagnostics)


def _build_directories(
    compiled: CompiledDocumentationPolicy,
    governed: tuple[str, ...],
) -> tuple[DocumentationDirectory, ...]:
    directory_paths: set[str] = set()
    for path in governed:
        parent = _parent_path(path)
        for root_directory in compiled.root_directories:
            if not _under_directory(path, root_directory):
                continue
            current = parent
            while True:
                directory_paths.add(current)
                if current == root_directory:
                    break
                current = _parent_path(current)

    direct_documents: dict[str, list[str]] = defaultdict(list)
    for path in governed:
        parent = _parent_path(path)
        if parent in directory_paths:
            direct_documents[parent].append(path)
    children: dict[str, list[str]] = defaultdict(list)
    for path in directory_paths:
        parent = _parent_path(path)
        if path and parent in directory_paths:
            children[parent].append(path)
    return tuple(
        DocumentationDirectory(
            path,
            _index_path(path),
            tuple(sorted(direct_documents[path])),
            tuple(sorted(children[path])),
        )
        for path in sorted(directory_paths)
    )


def _under_any_root(compiled: CompiledDocumentationPolicy, path: str) -> bool:
    return any(_under_directory(path, directory) for directory in compiled.root_directories)


def _root_indexes(compiled: CompiledDocumentationPolicy, path: str) -> tuple[int, ...]:
    return tuple(
        index
        for index, directory in enumerate(compiled.root_directories)
        if _under_directory(path, directory)
    )


def _under_directory(path: str, directory: str) -> bool:
    return not directory or path.startswith(f"{directory}/")


def _known_directories(entries: Sequence[InventoryEntry]) -> frozenset[str]:
    directories: set[str] = set()
    for entry in entries:
        if entry.source is InventorySource.DELETED or entry.kind is WorktreeKind.MISSING:
            continue
        parent = _parent_path(entry.path)
        while parent:
            directories.add(parent)
            parent = _parent_path(parent)
    return frozenset(directories)


def _unique_text_documents(
    documents: Sequence[TextDocument],
) -> dict[str, TextDocument]:
    by_path: dict[str, TextDocument] = {}
    for document in documents:
        if document.path in by_path:
            raise ValueError(f"duplicate retained text document: {document.path}")
        by_path[document.path] = document
    return by_path


def _parent_path(path: str) -> str:
    return path.rpartition("/")[0]


def _index_path(directory: str) -> str:
    return f"{directory}/index.md" if directory else "index.md"
