"""Pure current-file comparison against Git or first-adoption baselines."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from repo_context.diagnostics import (
    FILE_HARD_BYTES,
    RAT_BASE_TYPE_CHANGED,
    RAT_BASE_WITHIN_ORDINARY,
    RAT_COMPARISON_UNAVAILABLE,
    RAT_NEW_OVERSIZE,
    RAT_SIZE_REGRESSION,
    diagnostic_sort_key,
    policy_diagnostic,
)
from repo_context.git_records import find_base_entry
from repo_context.model import (
    BaseTreeEntry,
    ContentState,
    Diagnostic,
    FileAssessment,
    FileKind,
    FileRatchetAssessment,
    FileRatchetEvaluation,
    GitFileMode,
    GitObjectType,
    MigrationDebtEntry,
    MigrationDebtManifest,
    MigrationStatus,
    Policy,
    RatchetBaselineSource,
    RatchetUnavailableReason,
    Severity,
    WorktreeKind,
)
from repo_context.sizes import classify_content


BaseContentReader = Callable[[BaseTreeEntry], bytes]
_REGULAR_MODES = frozenset({GitFileMode.REGULAR, GitFileMode.EXECUTABLE})


def is_all_zero_ref(ref: str) -> bool:
    """Recognize the established CI no-parent sentinel without invoking Git."""

    return bool(ref) and set(ref) == {"0"}


def evaluate_file_ratchet(
    current_policy: Policy,
    current_files: Sequence[FileAssessment],
    *,
    evaluation_date: date,
    base_policy: Policy | None = None,
    base_entries: Sequence[BaseTreeEntry] = (),
    read_base: BaseContentReader | None = None,
    debt_manifest: MigrationDebtManifest | None = None,
    unavailable_reason: RatchetUnavailableReason = RatchetUnavailableReason.BASE_REF_ABSENT,
) -> FileRatchetEvaluation:
    """Evaluate current ordinary oversize using one authoritative baseline source."""

    del evaluation_date  # The ordinary size ratchet never evaluates exception expiry.
    candidates = _candidates(current_files)
    if not current_policy.ratchet.compare_file_sizes:
        source = RatchetBaselineSource.DISABLED
        return FileRatchetEvaluation(source, _unbaselined_candidates(candidates, source), ())

    if base_policy is not None:
        if base_policy.version != current_policy.version:
            raise ValueError("current and base policies must use the same schema version")
        if read_base is None:
            raise ValueError("Git-backed file ratchet requires a base-content reader")
        source = RatchetBaselineSource.GIT
        files, diagnostics = _evaluate_git(
            current_policy,
            candidates,
            base_entries,
            read_base,
        )
    elif debt_manifest is not None:
        source = RatchetBaselineSource.MANIFEST
        files, diagnostics = _evaluate_manifest(current_policy, candidates, debt_manifest)
    else:
        if not isinstance(unavailable_reason, RatchetUnavailableReason):
            raise ValueError("unavailable_reason must be a RatchetUnavailableReason")
        source = RatchetBaselineSource.UNAVAILABLE
        diagnostic = policy_diagnostic(
            RAT_COMPARISON_UNAVAILABLE,
            Severity.NOTE,
            "file-size ratchet comparison is unavailable",
            details=(("reason", unavailable_reason.value),),
            hint="supply a resolvable base revision or capture first-adoption debt",
        )
        return FileRatchetEvaluation(
            source,
            _unbaselined_candidates(candidates, source),
            (diagnostic,),
        )

    return FileRatchetEvaluation(
        source,
        tuple(sorted(files, key=lambda item: item.path)),
        tuple(sorted(diagnostics, key=diagnostic_sort_key)),
    )


def reconcile_size_diagnostics(
    diagnostics: Sequence[Diagnostic],
    file_ratchet: FileRatchetEvaluation,
) -> tuple[Diagnostic, ...]:
    """Suppress blocking ordinary-size findings only for proven migration debt."""

    migration_paths = {
        item.path
        for item in file_ratchet.files
        if item.migration_status is MigrationStatus.DEBT
    }
    return tuple(
        sorted(
            (
                diagnostic
                for diagnostic in diagnostics
                if not (
                    diagnostic.code == FILE_HARD_BYTES
                    and diagnostic.location is not None
                    and diagnostic.location.path in migration_paths
                )
            ),
            key=diagnostic_sort_key,
        )
    )


def _candidates(files: Sequence[FileAssessment]) -> tuple[FileAssessment, ...]:
    selected: list[FileAssessment] = []
    for assessment in files:
        policy = assessment.policy
        if (
            policy is not None
            and assessment.entry.kind is WorktreeKind.REGULAR
            and policy.kind is FileKind.AUTHORED
            and policy.ordinary_scan
            and policy.ordinary_hard_bytes is not None
            and assessment.content_state is ContentState.PLAINTEXT
            and assessment.size_bytes is not None
            and assessment.size_bytes > policy.ordinary_hard_bytes
        ):
            selected.append(assessment)
    return tuple(sorted(selected, key=lambda item: item.entry.path))


def _unbaselined_candidates(
    candidates: tuple[FileAssessment, ...],
    source: RatchetBaselineSource,
) -> tuple[FileRatchetAssessment, ...]:
    return tuple(
        FileRatchetAssessment(
            assessment.entry.path,
            _current_size(assessment),
            _ordinary_hard(assessment),
            None,
            None,
            None,
            source,
            MigrationStatus.UNBASELINED,
        )
        for assessment in candidates
    )


def _evaluate_git(
    current_policy: Policy,
    candidates: tuple[FileAssessment, ...],
    base_entries: Sequence[BaseTreeEntry],
    read_base: BaseContentReader,
) -> tuple[list[FileRatchetAssessment], list[Diagnostic]]:
    files: list[FileRatchetAssessment] = []
    diagnostics: list[Diagnostic] = []
    for current in candidates:
        path = current.entry.path
        hard = _ordinary_hard(current)
        size = _current_size(current)
        base = find_base_entry(base_entries, path)
        if base is None:
            _append_unbaselined(
                current_policy,
                files,
                diagnostics,
                path=path,
                size=size,
                hard=hard,
                source=RatchetBaselineSource.GIT,
                code=RAT_NEW_OVERSIZE,
                reason="new_path",
                message="new authored path exceeds its ordinary hard limit",
            )
            continue
        if base.mode not in _REGULAR_MODES or base.object_type is not GitObjectType.BLOB:
            _append_unbaselined(
                current_policy,
                files,
                diagnostics,
                path=path,
                size=size,
                hard=hard,
                source=RatchetBaselineSource.GIT,
                code=RAT_BASE_TYPE_CHANGED,
                reason="non_regular_type",
                message="base path is not an eligible regular plaintext file",
                extra_details=(
                    ("base_mode", base.mode.value),
                    ("base_object_type", base.object_type.value),
                    ("base_object_id", base.object_id),
                ),
            )
            continue
        raw = read_base(base)
        classified = classify_content(raw)
        if classified.state is not ContentState.PLAINTEXT:
            _append_unbaselined(
                current_policy,
                files,
                diagnostics,
                path=path,
                size=size,
                hard=hard,
                source=RatchetBaselineSource.GIT,
                code=RAT_BASE_TYPE_CHANGED,
                reason="non_plaintext",
                message="base path is not an eligible regular plaintext file",
                base_size=len(raw),
                base_identity=f"git:{base.object_id}",
                extra_details=(
                    ("base_content_state", classified.state.value),
                    ("base_object_id", base.object_id),
                ),
            )
            continue
        _compare_sizes(
            current_policy,
            files,
            diagnostics,
            path=path,
            size=size,
            hard=hard,
            base_size=classified.size_bytes,
            base_identity=f"git:{base.object_id}",
            source=RatchetBaselineSource.GIT,
        )
    return files, diagnostics


def _evaluate_manifest(
    current_policy: Policy,
    candidates: tuple[FileAssessment, ...],
    manifest: MigrationDebtManifest,
) -> tuple[list[FileRatchetAssessment], list[Diagnostic]]:
    by_path: dict[str, MigrationDebtEntry] = {}
    for entry in manifest.entries:
        if entry.path in by_path:
            raise ValueError(f"duplicate migration-debt path {entry.path!r}")
        by_path[entry.path] = entry
    files: list[FileRatchetAssessment] = []
    diagnostics: list[Diagnostic] = []
    for current in candidates:
        path = current.entry.path
        hard = _ordinary_hard(current)
        size = _current_size(current)
        base = by_path.get(path)
        if base is None:
            _append_unbaselined(
                current_policy,
                files,
                diagnostics,
                path=path,
                size=size,
                hard=hard,
                source=RatchetBaselineSource.MANIFEST,
                code=RAT_NEW_OVERSIZE,
                reason="new_path",
                message="new authored path exceeds its ordinary hard limit",
            )
            continue
        _compare_sizes(
            current_policy,
            files,
            diagnostics,
            path=path,
            size=size,
            hard=hard,
            base_size=base.size_bytes,
            base_identity=base.content_identity,
            source=RatchetBaselineSource.MANIFEST,
        )
    return files, diagnostics


def _compare_sizes(
    current_policy: Policy,
    files: list[FileRatchetAssessment],
    diagnostics: list[Diagnostic],
    *,
    path: str,
    size: int,
    hard: int,
    base_size: int,
    base_identity: str,
    source: RatchetBaselineSource,
) -> None:
    if base_size <= hard:
        _append_unbaselined(
            current_policy,
            files,
            diagnostics,
            path=path,
            size=size,
            hard=hard,
            source=source,
            code=RAT_BASE_WITHIN_ORDINARY,
            reason="within_ordinary_limit",
            message="base version was within the current ordinary hard limit",
            base_size=base_size,
            base_identity=base_identity,
        )
        return
    if size > base_size:
        diagnostics.append(
            policy_diagnostic(
                RAT_SIZE_REGRESSION,
                Severity.ERROR,
                "oversized authored file grew relative to its immediate baseline",
                path=path,
                details=(
                    ("base_size_bytes", base_size),
                    ("current_size_bytes", size),
                    ("ordinary_hard_bytes", hard),
                ),
                hint="restore the baseline size or split the file",
            )
        )
        files.append(
            FileRatchetAssessment(
                path,
                size,
                hard,
                base_size,
                base_identity,
                base_size,
                source,
                MigrationStatus.VIOLATION,
            )
        )
        return
    files.append(
        FileRatchetAssessment(
            path,
            size,
            hard,
            base_size,
            base_identity,
            base_size,
            source,
            MigrationStatus.DEBT,
        )
    )


def _append_unbaselined(
    current_policy: Policy,
    files: list[FileRatchetAssessment],
    diagnostics: list[Diagnostic],
    *,
    path: str,
    size: int,
    hard: int,
    source: RatchetBaselineSource,
    code: str,
    reason: str,
    message: str,
    base_size: int | None = None,
    base_identity: str | None = None,
    extra_details=(),
) -> None:
    forbidden = current_policy.ratchet.forbid_new_oversize
    if forbidden:
        details = [
            ("current_size_bytes", size),
            ("ordinary_hard_bytes", hard),
            ("reason", reason),
        ]
        if base_size is not None:
            details.append(("base_size_bytes", base_size))
        details.extend(extra_details)
        diagnostics.append(
            policy_diagnostic(
                code,
                Severity.ERROR,
                message,
                path=path,
                details=tuple(details),
                hint="split the file or restore an eligible oversized baseline",
            )
        )
    files.append(
        FileRatchetAssessment(
            path,
            size,
            hard,
            base_size,
            base_identity,
            None,
            source,
            MigrationStatus.VIOLATION if forbidden else MigrationStatus.UNBASELINED,
        )
    )


def _ordinary_hard(assessment: FileAssessment) -> int:
    value = None if assessment.policy is None else assessment.policy.ordinary_hard_bytes
    if value is None:
        raise AssertionError("file-ratchet candidate has no ordinary hard limit")
    return value


def _current_size(assessment: FileAssessment) -> int:
    if assessment.size_bytes is None:
        raise AssertionError("file-ratchet candidate has no current byte size")
    return assessment.size_bytes
