"""Plaintext classification, file budgets, context sets, and audit data."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import date

from repo_context.diagnostics import (
    CFG_EFFECTIVE_POLICY,
    CFG_UNCLASSIFIED_PATH,
    CONTEXT_HARD_BYTES,
    CONTEXT_MEMBER_MISSING,
    CONTEXT_WARN_BYTES,
    EXC_EXPIRED,
    FILE_HARD_BYTES,
    FILE_WARN_BYTES,
    diagnostic_sort_key,
    policy_diagnostic,
)
from repo_context.matcher import match_path
from repo_context.model import (
    ClassifiedContent,
    ContentState,
    ContextAssessment,
    ContextMember,
    Diagnostic,
    EffectiveFilePolicy,
    FileAssessment,
    FileExplanation,
    FileKind,
    InventoryEntry,
    InventorySource,
    JsonValue,
    LimitState,
    Severity,
    SizeEvaluation,
    TextDocument,
    WorktreeKind,
)
from repo_context.size_policy import (
    CompiledContextSet,
    CompiledSizePolicy,
    compile_size_policy,
    context_names_for_path,
    effective_policy_error,
    exception_is_expired,
    resolve_effective_policy,
)


ContentReader = Callable[[InventoryEntry], bytes]


class SizePolicyError(ValueError):
    """One or more path-specific effective-policy failures."""

    def __init__(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        self.diagnostics = diagnostics
        super().__init__(diagnostics[0].message)


def classify_content(data: bytes) -> ClassifiedContent:
    """Classify exact raw bytes without normalizing encoding or line endings."""

    if b"\x00" in data:
        return ClassifiedContent(ContentState.CONTAINS_NUL, len(data), None)
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return ClassifiedContent(ContentState.INVALID_UTF8, len(data), None)
    return ClassifiedContent(ContentState.PLAINTEXT, len(data), text)


def evaluate_sizes(
    compiled: CompiledSizePolicy,
    entries: Sequence[InventoryEntry],
    read_content: ContentReader,
    *,
    evaluation_date: date,
    retain_text_paths: frozenset[str] = frozenset(),
) -> SizeEvaluation:
    """Evaluate one sorted inventory while reading each scanned regular file once."""

    ordered_entries = tuple(sorted(entries, key=lambda item: item.path))
    diagnostics = list(_expired_exception_diagnostics(compiled, evaluation_date))
    files: list[FileAssessment] = []
    documents: list[TextDocument] = []
    for entry in ordered_entries:
        assessment, file_diagnostics, document = _evaluate_file(
            compiled,
            entry,
            read_content,
            evaluation_date,
            entry.path in retain_text_paths,
        )
        files.append(assessment)
        diagnostics.extend(file_diagnostics)
        if document is not None:
            documents.append(document)

    contexts: list[ContextAssessment] = []
    entries_by_path = {entry.path: entry for entry in ordered_entries}
    for context in compiled.contexts:
        assessment, context_diagnostics = _evaluate_context(context, entries_by_path)
        contexts.append(assessment)
        diagnostics.extend(context_diagnostics)

    return SizeEvaluation(
        files=tuple(files),
        contexts=tuple(contexts),
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
        documents=tuple(sorted(documents, key=lambda item: item.path)),
    )


def largest_governed_files(evaluation: SizeEvaluation) -> tuple[FileAssessment, ...]:
    """Return every classified path, with unsized states after descending sizes."""

    return tuple(
        sorted(
            (
                item
                for item in evaluation.files
                if item.policy is not None
            ),
            key=lambda item: (
                item.size_bytes is None,
                -1 if item.size_bytes is None else -item.size_bytes,
                item.entry.path,
            ),
        )
    )


def classification_counts(
    evaluation: SizeEvaluation,
) -> tuple[tuple[FileKind, int], ...]:
    counts = Counter(
        item.policy.kind
        for item in evaluation.files
        if item.policy is not None
    )
    return tuple((kind, counts[kind]) for kind in sorted(counts, key=lambda item: item.value))


def explain_size_path(
    compiled: CompiledSizePolicy,
    path: str,
    evaluation_date: date,
    evaluation: SizeEvaluation | None = None,
) -> FileExplanation:
    assessment = None
    if evaluation is not None:
        assessment = next(
            (item for item in evaluation.files if item.entry.path == path),
            None,
        )
    policy = resolve_effective_policy(compiled, path, evaluation_date)
    if policy is not None:
        inconsistency = effective_policy_error(policy)
        if inconsistency is not None:
            raise SizePolicyError(
                (_effective_policy_diagnostic(path, policy, inconsistency),)
            )
    return FileExplanation(
        path=path,
        policy=policy,
        context_sets=context_names_for_path(compiled, path),
        assessment=assessment,
    )


def _evaluate_file(
    compiled: CompiledSizePolicy,
    entry: InventoryEntry,
    read_content: ContentReader,
    evaluation_date: date,
    retain_text: bool,
) -> tuple[FileAssessment, tuple[Diagnostic, ...], TextDocument | None]:
    policy = resolve_effective_policy(compiled, entry.path, evaluation_date)
    size_bytes = entry.size_bytes if entry.kind is WorktreeKind.REGULAR else None
    content_state = (
        ContentState.UNREAD if entry.kind is WorktreeKind.REGULAR else None
    )
    if policy is None:
        diagnostic = policy_diagnostic(
            CFG_UNCLASSIFIED_PATH,
            Severity.ERROR,
            "repository path does not match a file rule",
            path=entry.path,
            details=(
                ("source", entry.source.value),
                ("worktree_kind", entry.kind.value),
            ),
            hint="add a narrow rule or restore the required final authored catch-all",
        )
        return (
            FileAssessment(entry, None, content_state, size_bytes, None),
            (diagnostic,),
            None,
        )
    inconsistency = effective_policy_error(policy)
    if inconsistency is not None:
        diagnostic = _effective_policy_diagnostic(entry.path, policy, inconsistency)
        return (
            FileAssessment(entry, policy, content_state, size_bytes, None),
            (diagnostic,),
            None,
        )
    ratchet_classification = (
        compiled.policy.ratchet.compare_file_sizes
        and policy.kind is FileKind.AUTHORED
        and policy.ordinary_scan
        and policy.ordinary_hard_bytes is not None
        and size_bytes is not None
        and size_bytes > policy.ordinary_hard_bytes
    )
    if entry.kind is not WorktreeKind.REGULAR or (
        not policy.effective_scan and not retain_text and not ratchet_classification
    ):
        return (
            FileAssessment(entry, policy, content_state, size_bytes, None),
            (),
            None,
        )

    raw = read_content(entry)
    classified = classify_content(raw)
    content_identity = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    document = None
    limit_state = None
    diagnostics: tuple[Diagnostic, ...] = ()
    if classified.state is ContentState.PLAINTEXT and policy.effective_scan:
        limit_state = _limit_state(
            classified.size_bytes,
            _required_limit(policy.effective_warn_bytes),
            _required_limit(policy.effective_hard_bytes),
        )
        diagnostic = _file_limit_diagnostic(entry, policy, classified.size_bytes, limit_state)
        diagnostics = () if diagnostic is None else (diagnostic,)
    if classified.state is ContentState.PLAINTEXT and retain_text:
        document = TextDocument(
            entry.path,
            _required_text(classified),
            classified.size_bytes,
        )
    return (
        FileAssessment(
            entry,
            policy,
            classified.state,
            classified.size_bytes,
            limit_state,
            content_identity,
        ),
        diagnostics,
        document,
    )


def _file_limit_diagnostic(
    entry: InventoryEntry,
    policy: EffectiveFilePolicy,
    size_bytes: int,
    state: LimitState,
) -> Diagnostic | None:
    if state is LimitState.WITHIN:
        return None
    hard = state is LimitState.HARD
    return policy_diagnostic(
        FILE_HARD_BYTES if hard else FILE_WARN_BYTES,
        Severity.ERROR if hard else Severity.WARNING,
        "plaintext file exceeds its hard byte limit"
        if hard
        else "plaintext file exceeds its warning byte limit",
        path=entry.path,
        details=(
            ("size_bytes", size_bytes),
            ("warn_bytes", _required_limit(policy.effective_warn_bytes)),
            ("hard_bytes", _required_limit(policy.effective_hard_bytes)),
            ("kind", policy.kind.value),
            ("rule_index", policy.rule_match.rule_index),
            ("rule_name", policy.rule_match.rule.name),
            (
                "override_index",
                None if policy.override_match is None else policy.override_match.override_index,
            ),
            (
                "exception_index",
                None if policy.exception_match is None else policy.exception_match.exception_index,
            ),
        ),
    )


def _effective_policy_diagnostic(
    path: str,
    policy: EffectiveFilePolicy,
    message: str,
) -> Diagnostic:
    return policy_diagnostic(
        CFG_EFFECTIVE_POLICY,
        Severity.ERROR,
        message,
        path=path,
        details=_policy_details(policy),
    )


def _evaluate_context(
    compiled: CompiledContextSet,
    entries_by_path: dict[str, InventoryEntry],
) -> tuple[ContextAssessment, tuple[Diagnostic, ...]]:
    context = compiled.context
    member_paths = set(context.paths)
    pattern_indexes_by_path: dict[str, tuple[int, ...]] = {}
    for path in entries_by_path:
        matched = tuple(
            pattern_index
            for pattern_index, pattern in enumerate(compiled.patterns)
            if match_path(pattern, path)
        )
        if matched:
            member_paths.add(path)
            pattern_indexes_by_path[path] = matched

    exact_indexes = {path: index for index, path in enumerate(context.paths)}
    members: list[ContextMember] = []
    missing: list[str] = []
    diagnostics: list[Diagnostic] = []
    total_bytes = 0
    for path in sorted(member_paths):
        entry = entries_by_path.get(path)
        required_exact = path in exact_indexes
        counted_bytes = entry.size_bytes if _is_counted_context_entry(entry) else None
        if counted_bytes is not None:
            total_bytes += counted_bytes
        elif required_exact:
            missing.append(path)
            diagnostics.append(
                _missing_context_member_diagnostic(
                    compiled,
                    exact_indexes[path],
                    path,
                    entry,
                )
            )
        members.append(
            ContextMember(
                path,
                entry,
                required_exact,
                pattern_indexes_by_path.get(path, ()),
                counted_bytes,
            )
        )

    state = _limit_state(total_bytes, context.warn_bytes, context.hard_bytes)
    limit_diagnostic = _context_limit_diagnostic(compiled, total_bytes, len(members), state)
    if limit_diagnostic is not None:
        diagnostics.append(limit_diagnostic)
    return (
        ContextAssessment(
            compiled.context_index,
            context.name,
            tuple(members),
            total_bytes,
            context.warn_bytes,
            context.hard_bytes,
            state,
            tuple(missing),
        ),
        tuple(diagnostics),
    )


def _missing_context_member_diagnostic(
    compiled: CompiledContextSet,
    member_index: int,
    path: str,
    entry: InventoryEntry | None,
) -> Diagnostic:
    state = "absent" if entry is None else _missing_entry_state(entry)
    return policy_diagnostic(
        CONTEXT_MEMBER_MISSING,
        Severity.ERROR,
        f"required context-set member is not a present regular file ({state})",
        path=path,
        details=(
            ("context_index", compiled.context_index),
            ("context_name", compiled.context.name),
            ("member_index", member_index),
            ("state", state),
        ),
    )


def _context_limit_diagnostic(
    compiled: CompiledContextSet,
    total_bytes: int,
    member_count: int,
    state: LimitState,
) -> Diagnostic | None:
    if state is LimitState.WITHIN:
        return None
    hard = state is LimitState.HARD
    context = compiled.context
    return policy_diagnostic(
        CONTEXT_HARD_BYTES if hard else CONTEXT_WARN_BYTES,
        Severity.ERROR if hard else Severity.WARNING,
        "context set exceeds its hard byte limit"
        if hard
        else "context set exceeds its warning byte limit",
        details=(
            ("context_index", compiled.context_index),
            ("context_name", context.name),
            ("total_bytes", total_bytes),
            ("warn_bytes", context.warn_bytes),
            ("hard_bytes", context.hard_bytes),
            ("member_count", member_count),
        ),
    )


def _expired_exception_diagnostics(
    compiled: CompiledSizePolicy,
    evaluation_date: date,
) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    for index, exception in enumerate(compiled.policy.exceptions.records):
        if exception_is_expired(exception, evaluation_date):
            diagnostics.append(
                policy_diagnostic(
                    EXC_EXPIRED,
                    Severity.ERROR,
                    "intentional exception is expired",
                    field_path=f"exceptions.record[{index}].expires_on",
                    details=(
                        ("exception_index", index),
                        ("expires_on", exception.expires_on.isoformat()),
                        ("evaluation_date", evaluation_date.isoformat()),
                    ),
                )
            )
    return tuple(diagnostics)


def _limit_state(size_bytes: int, warn_bytes: int, hard_bytes: int) -> LimitState:
    if size_bytes > hard_bytes:
        return LimitState.HARD
    if size_bytes > warn_bytes:
        return LimitState.WARNING
    return LimitState.WITHIN


def _is_counted_context_entry(entry: InventoryEntry | None) -> bool:
    return (
        entry is not None
        and entry.source is not InventorySource.DELETED
        and entry.kind is WorktreeKind.REGULAR
        and entry.size_bytes is not None
    )


def _missing_entry_state(entry: InventoryEntry) -> str:
    if entry.source is InventorySource.DELETED:
        return "deleted"
    if entry.kind is WorktreeKind.MISSING:
        return (
            "sparse_missing"
            if entry.source is InventorySource.TRACKED
            else "missing"
        )
    return entry.kind.value


def _policy_details(policy: EffectiveFilePolicy) -> tuple[tuple[str, JsonValue], ...]:
    return (
        ("rule_index", policy.rule_match.rule_index),
        (
            "override_index",
            None if policy.override_match is None else policy.override_match.override_index,
        ),
        (
            "exception_index",
            None if policy.exception_match is None else policy.exception_match.exception_index,
        ),
        ("effective_scan", policy.effective_scan),
        ("effective_warn_bytes", policy.effective_warn_bytes),
        ("effective_hard_bytes", policy.effective_hard_bytes),
    )


def _required_limit(value: int | None) -> int:
    if value is None:
        raise AssertionError("validated effective scanned policy has complete limits")
    return value


def _required_size(assessment: FileAssessment) -> int:
    if assessment.size_bytes is None:
        raise AssertionError("largest governed files include only sized entries")
    return assessment.size_bytes


def _required_text(classified: ClassifiedContent) -> str:
    if classified.text is None:
        raise AssertionError("plaintext classification must retain decoded text")
    return classified.text
