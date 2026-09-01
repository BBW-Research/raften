"""Monotonic documentation, entrypoint, context, ratchet, and exception policy."""

from __future__ import annotations

import posixpath
from datetime import date

from repo_context.diagnostics import (
    RAT_CONTEXT_WEAKENED,
    RAT_DOCUMENTATION_WEAKENED,
    RAT_ENTRYPOINT_WEAKENED,
    RAT_EXCEPTION_BROADENED,
    RAT_RATCHET_DISABLED,
)
from repo_context.model import (
    Diagnostic,
    ExactSelector,
    IntentionalException,
    JsonValue,
    Policy,
)
from repo_context.policy_comparison import compare_limits, ratchet_finding, selector_key
from repo_context.size_policy import (
    CompiledSizePolicy,
    compile_size_policy,
    effective_policy_error,
    resolve_effective_policy,
)


_DOCUMENTATION_REQUIREMENTS = (
    "require_directory_indexes",
    "require_sibling_links",
    "require_child_index_links",
    "require_root_reachability",
    "check_local_targets",
    "check_fragments",
)
_RATCHET_SETTINGS = (
    "compare_file_sizes",
    "forbid_new_oversize",
    "forbid_limit_increases",
    "forbid_exclusion_expansion",
    "forbid_removed_documentation_roots",
    "forbid_removed_entrypoint_targets",
)


def compare_policy_domains(
    current: Policy,
    base: Policy,
    policy_path: str,
) -> tuple[Diagnostic, ...]:
    findings: list[Diagnostic] = []
    _compare_ratchet_settings(current, base, policy_path, findings)
    _compare_documentation(current, base, policy_path, findings)
    _compare_entrypoints(current, base, policy_path, findings)
    _compare_contexts(current, base, policy_path, findings)
    _compare_exceptions(current, base, policy_path, findings)
    return tuple(findings)


def _compare_documentation(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    if base.ratchet.forbid_removed_documentation_roots:
        for root in sorted(set(base.documentation.roots).difference(current.documentation.roots)):
            findings.append(
                ratchet_finding(
                    RAT_DOCUMENTATION_WEAKENED,
                    policy_path,
                    "documentation.roots",
                    "documentation_root_removed",
                    base=root,
                    current=None,
                )
            )
        if base.documentation.require_root_reachability:
            base_directories = tuple(
                _documentation_root_directory(root)
                for root in base.documentation.roots
            )
            for root in sorted(set(current.documentation.roots).difference(base.documentation.roots)):
                if any(_is_within_directory(root, directory) for directory in base_directories):
                    findings.append(
                        ratchet_finding(
                            RAT_DOCUMENTATION_WEAKENED,
                            policy_path,
                            "documentation.roots",
                            "reachability_root_added_within_governed_tree",
                            base=base.documentation.roots,
                            current=root,
                        )
                    )
        for setting in _DOCUMENTATION_REQUIREMENTS:
            if getattr(base.documentation, setting) and not getattr(current.documentation, setting):
                findings.append(
                    ratchet_finding(
                        RAT_DOCUMENTATION_WEAKENED,
                        policy_path,
                        f"documentation.{setting}",
                        "documentation_requirement_disabled",
                        base=True,
                        current=False,
                        extra=(("setting", setting),),
                    )
                )
    if base.ratchet.forbid_exclusion_expansion:
        for pattern in sorted(set(current.documentation.exclude).difference(base.documentation.exclude)):
            findings.append(
                ratchet_finding(
                    RAT_DOCUMENTATION_WEAKENED,
                    policy_path,
                    "documentation.exclude",
                    "documentation_exclusion_added",
                    base=None,
                    current=pattern,
                )
            )


def _compare_entrypoints(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    if not base.ratchet.forbid_removed_entrypoint_targets:
        return
    current_by_path = {item.path: (index, item) for index, item in enumerate(current.entrypoints)}
    for base_entrypoint in base.entrypoints:
        selected = current_by_path.get(base_entrypoint.path)
        if selected is None:
            findings.append(
                ratchet_finding(
                    RAT_ENTRYPOINT_WEAKENED,
                    policy_path,
                    "entrypoint",
                    "entrypoint_removed",
                    base=base_entrypoint.path,
                    current=None,
                )
            )
            continue
        current_index, current_entrypoint = selected
        for target in sorted(
            set(base_entrypoint.required_targets).difference(current_entrypoint.required_targets)
        ):
            findings.append(
                ratchet_finding(
                    RAT_ENTRYPOINT_WEAKENED,
                    policy_path,
                    f"entrypoint[{current_index}].required_targets",
                    "required_target_removed",
                    base=target,
                    current=None,
                    extra=(("entrypoint", base_entrypoint.path),),
                )
            )


def _compare_contexts(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    current_by_name = {item.name: (index, item) for index, item in enumerate(current.context_sets)}
    for base_context in base.context_sets:
        selected = current_by_name.get(base_context.name)
        if selected is None:
            findings.append(
                ratchet_finding(
                    RAT_CONTEXT_WEAKENED,
                    policy_path,
                    "context_set",
                    "context_set_removed",
                    base=base_context.name,
                    current=None,
                )
            )
            continue
        current_index, current_context = selected
        parent = f"context_set[{current_index}]"
        for path in sorted(set(base_context.paths).difference(current_context.paths)):
            findings.append(
                ratchet_finding(
                    RAT_CONTEXT_WEAKENED,
                    policy_path,
                    f"{parent}.paths",
                    "context_path_removed",
                    base=path,
                    current=None,
                )
            )
        for pattern in sorted(set(base_context.patterns).difference(current_context.patterns)):
            findings.append(
                ratchet_finding(
                    RAT_CONTEXT_WEAKENED,
                    policy_path,
                    f"{parent}.patterns",
                    "context_pattern_removed",
                    base=pattern,
                    current=None,
                )
            )
        if base.ratchet.forbid_limit_increases:
            compare_limits(
                current_context.warn_bytes,
                current_context.hard_bytes,
                base_context.warn_bytes,
                base_context.hard_bytes,
                RAT_CONTEXT_WEAKENED,
                policy_path,
                parent,
                findings,
            )


def _compare_ratchet_settings(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    for setting in _RATCHET_SETTINGS:
        if getattr(base.ratchet, setting) and not getattr(current.ratchet, setting):
            findings.append(
                ratchet_finding(
                    RAT_RATCHET_DISABLED,
                    policy_path,
                    f"ratchet.{setting}",
                    "ratchet_disabled",
                    base=True,
                    current=False,
                    extra=(("setting", setting),),
                )
            )


def _compare_exceptions(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    compiled_current = compile_size_policy(current)
    compiled_base = compile_size_policy(base)
    current_by_selector = {
        selector_key(item.selector): (index, item)
        for index, item in enumerate(current.exceptions.records)
    }
    base_by_selector = {
        selector_key(item.selector): item for item in base.exceptions.records
    }
    for key, base_exception in base_by_selector.items():
        if key in current_by_selector:
            continue
        selector = base_exception.selector
        if isinstance(selector, ExactSelector):
            weakens = _exact_enforcement_is_weaker(
                selector.path,
                compiled_current,
                compiled_base,
            )
        else:
            weakens = base_exception.scan is not False
        if weakens:
            findings.append(
                ratchet_finding(
                    RAT_EXCEPTION_BROADENED,
                    policy_path,
                    "exceptions.record",
                    "exception_removal_exposes_weaker_fallback",
                    base=f"{key[0]}:{key[1]}",
                    current=None,
                )
            )
    for key, (current_index, current_exception) in current_by_selector.items():
        parent = f"exceptions.record[{current_index}]"
        base_exception = base_by_selector.get(key)
        if base_exception is None:
            findings.append(
                ratchet_finding(
                    RAT_EXCEPTION_BROADENED,
                    policy_path,
                    parent,
                    "exception_added",
                    base=None,
                    current=f"{key[0]}:{key[1]}",
                    extra=_governance_details(current_exception),
                )
            )
            continue
        if _scan_relief_rank(current_exception.scan) > _scan_relief_rank(base_exception.scan):
            findings.append(
                ratchet_finding(
                    RAT_EXCEPTION_BROADENED,
                    policy_path,
                    f"{parent}.scan",
                    "scan_relief_broadened",
                    base=base_exception.scan,
                    current=current_exception.scan,
                )
            )
        if base_exception.warn_bytes is None and current_exception.warn_bytes is not None:
            findings.append(
                ratchet_finding(
                    RAT_EXCEPTION_BROADENED,
                    policy_path,
                    parent,
                    "limit_relief_added",
                    base=None,
                    current=current_exception.hard_bytes,
                )
            )
        elif base_exception.warn_bytes is not None and current_exception.warn_bytes is not None:
            compare_limits(
                current_exception.warn_bytes,
                current_exception.hard_bytes,
                base_exception.warn_bytes,
                base_exception.hard_bytes,
                RAT_EXCEPTION_BROADENED,
                policy_path,
                parent,
                findings,
            )
        elif base_exception.warn_bytes is not None:
            selector = current_exception.selector
            if not isinstance(selector, ExactSelector) or _exact_enforcement_is_weaker(
                selector.path,
                compiled_current,
                compiled_base,
            ):
                findings.append(
                    ratchet_finding(
                        RAT_EXCEPTION_BROADENED,
                        policy_path,
                        parent,
                        "replacement_limits_removed",
                        base=(base_exception.warn_bytes, base_exception.hard_bytes),
                        current=None,
                    )
                )
        if _expiry_extended(current_exception.expires_on, base_exception.expires_on):
            findings.append(
                ratchet_finding(
                    RAT_EXCEPTION_BROADENED,
                    policy_path,
                    f"{parent}.expires_on",
                    "expiry_extended",
                    base=base_exception.expires_on,
                    current=current_exception.expires_on,
                )
            )


def _scan_relief_rank(value: bool | None) -> int:
    return {True: 0, None: 1, False: 2}[value]


def _expiry_extended(current: date | None, base: date | None) -> bool:
    return base is not None and (current is None or current > base)


def _exact_enforcement_is_weaker(
    path: str,
    compiled_current: CompiledSizePolicy,
    compiled_base: CompiledSizePolicy,
) -> bool:
    current = resolve_effective_policy(compiled_current, path, date.min)
    base = resolve_effective_policy(compiled_base, path, date.min)
    if current is None or base is None:
        raise AssertionError("valid version 1 policies require a final catch-all file rule")
    current_invalid = effective_policy_error(current) is not None
    base_invalid = effective_policy_error(base) is not None
    if current_invalid:
        # Policy comparison cannot rely on an inventoried path to surface CFG015.
        return True
    if base_invalid:
        # Repairing fail-closed base state is safe only when finite scanning replaces it.
        return not current.effective_scan
    if base.effective_scan and not current.effective_scan:
        return True
    if not base.effective_scan or not current.effective_scan:
        return False
    return (
        current.effective_warn_bytes > base.effective_warn_bytes
        or current.effective_hard_bytes > base.effective_hard_bytes
    )


def _documentation_root_directory(root: str) -> str:
    directory = posixpath.dirname(root)
    return "." if not directory else directory


def _is_within_directory(path: str, directory: str) -> bool:
    return directory == "." or path.startswith(f"{directory}/")


def _governance_details(exception: IntentionalException) -> tuple[tuple[str, JsonValue], ...]:
    return (
        ("owner", exception.owner),
        ("rationale", exception.rationale),
        ("tracking_reference", exception.tracking_reference),
        ("created_on", exception.created_on.isoformat()),
        ("expires_on", None if exception.expires_on is None else exception.expires_on.isoformat()),
    )
