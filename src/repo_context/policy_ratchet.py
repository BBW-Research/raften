"""Conservative monotonic comparison for two valid version 1 policies."""

from __future__ import annotations

from repo_context.diagnostics import (
    RAT_FILE_LIMIT_INCREASED,
    RAT_FILE_POLICY_WEAKENED,
    RAT_OVERRIDE_WEAKENED,
    diagnostic_sort_key,
)
from repo_context.matcher import (
    compile_pattern,
    match_path,
    pattern_specificity,
    patterns_provably_disjoint,
)
from repo_context.model import (
    Diagnostic,
    ExactSelector,
    FileKind,
    FileRule,
    PathOverride,
    Policy,
    Selector,
)
from repo_context.policy_comparison import compare_limits, ratchet_finding, selector_key
from repo_context.policy_domains import compare_policy_domains


def compare_policies(
    current: Policy,
    base: Policy,
    *,
    policy_path: str = "repo-context.toml",
) -> tuple[Diagnostic, ...]:
    """Report every conservative v1 weakening relative to the base policy."""

    findings: list[Diagnostic] = []
    _compare_file_rules(current, base, policy_path, findings)
    _compare_overrides(current, base, policy_path, findings)
    findings.extend(compare_policy_domains(current, base, policy_path))
    return tuple(sorted(findings, key=diagnostic_sort_key))


def _compare_file_rules(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    check_limits = base.ratchet.forbid_limit_increases
    check_structure = base.ratchet.forbid_exclusion_expansion
    if not check_limits and not check_structure:
        return
    current_by_name = {rule.name: (index, rule) for index, rule in enumerate(current.file_rules)}
    base_by_name = {rule.name: (index, rule) for index, rule in enumerate(base.file_rules)}

    for name, (_base_index, base_rule) in base_by_name.items():
        selected = current_by_name.get(name)
        if selected is None:
            if base_rule.scan:
                findings.append(
                    ratchet_finding(
                        RAT_FILE_POLICY_WEAKENED,
                        policy_path,
                        "file_rule",
                        "scanned_rule_removed",
                        base=name,
                        current=None,
                    )
                )
            continue
        current_index, current_rule = selected
        parent = f"file_rule[{current_index}]"
        if base_rule.scan:
            _compare_scanned_rule(
                current_rule,
                base_rule,
                policy_path,
                parent,
                findings,
                check_limits=check_limits,
            )
        else:
            if check_structure and current_rule.kind is not base_rule.kind:
                findings.append(
                    ratchet_finding(
                        RAT_FILE_POLICY_WEAKENED,
                        policy_path,
                        f"{parent}.kind",
                        "unscanned_classification_changed",
                        base=base_rule.kind,
                        current=current_rule.kind,
                    )
                )
            added_patterns = tuple(
                pattern
                for pattern in current_rule.patterns
                if pattern not in base_rule.patterns
            )
            if current_rule.scan and added_patterns:
                _compare_new_scanned_rule(
                    FileRule(
                        current_rule.name,
                        added_patterns,
                        current_rule.kind,
                        True,
                        current_rule.warn_bytes,
                        current_rule.hard_bytes,
                        current_rule.reason,
                    ),
                    base.file_rules,
                    policy_path,
                    parent,
                    findings,
                    check_limits=check_limits,
                    check_structure=check_structure,
                )
            else:
                for pattern in sorted(added_patterns):
                    findings.append(
                        ratchet_finding(
                            RAT_FILE_POLICY_WEAKENED,
                            policy_path,
                            f"{parent}.patterns",
                            "unscanned_pattern_added",
                            base=None,
                            current=pattern,
                        )
                    )

    for name, (current_index, current_rule) in current_by_name.items():
        if name in base_by_name:
            continue
        parent = f"file_rule[{current_index}]"
        if current_rule.scan:
            _compare_new_scanned_rule(
                current_rule,
                base.file_rules,
                policy_path,
                parent,
                findings,
                check_limits=check_limits,
                check_structure=check_structure,
            )
        else:
            for pattern in sorted(current_rule.patterns):
                findings.append(
                    ratchet_finding(
                        RAT_FILE_POLICY_WEAKENED,
                        policy_path,
                        f"{parent}.patterns",
                        "unscanned_pattern_added",
                        base=None,
                        current=pattern,
                    )
                )

    retained_base_order = tuple(
        rule.name
        for rule in base.file_rules
        if rule.scan and rule.name in current_by_name and current_by_name[rule.name][1].scan
    )
    retained_current_order = tuple(
        rule.name for rule in current.file_rules if rule.name in retained_base_order
    )
    if retained_current_order != retained_base_order:
        findings.append(
            ratchet_finding(
                RAT_FILE_POLICY_WEAKENED,
                policy_path,
                "file_rule",
                "file_rule_precedence_changed",
                base=retained_base_order,
                current=retained_current_order,
            )
        )
    _compare_unscanned_rule_positions(
        current_by_name,
        base.file_rules,
        policy_path,
        findings,
    )


def _compare_unscanned_rule_positions(
    current_by_name: dict[str, tuple[int, FileRule]],
    base_rules: tuple[FileRule, ...],
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    for base_index, base_rule in enumerate(base_rules):
        if base_rule.scan or base_rule.name not in current_by_name:
            continue
        current_index, _current_rule = current_by_name[base_rule.name]
        for preceding in base_rules[:base_index]:
            if not preceding.scan:
                continue
            retained = current_by_name.get(preceding.name)
            if retained is None or not retained[1].scan:
                continue
            preceding_current_index = retained[0]
            if current_index >= preceding_current_index:
                continue
            findings.append(
                ratchet_finding(
                    RAT_FILE_POLICY_WEAKENED,
                    policy_path,
                    f"file_rule[{current_index}]",
                    "unscanned_rule_moved_ahead",
                    base=(preceding.name, base_rule.name),
                    current=(base_rule.name, preceding.name),
                    extra=(("rule", base_rule.name),),
                )
            )
            break


def _compare_scanned_rule(
    current: FileRule,
    base: FileRule,
    policy_path: str,
    parent: str,
    findings: list[Diagnostic],
    *,
    check_limits: bool,
) -> None:
    if current.patterns != base.patterns:
        findings.append(
            ratchet_finding(
                RAT_FILE_POLICY_WEAKENED,
                policy_path,
                f"{parent}.patterns",
                "scanned_patterns_changed",
                base=base.patterns,
                current=current.patterns,
            )
        )
    if not current.scan:
        findings.append(
            ratchet_finding(
                RAT_FILE_POLICY_WEAKENED,
                policy_path,
                f"{parent}.scan",
                "scanned_rule_disabled",
                base=True,
                current=False,
            )
        )
    if base.kind is FileKind.AUTHORED and current.kind is not FileKind.AUTHORED:
        reason = "authored_classification_removed"
    elif current.kind is not base.kind:
        reason = "classification_changed"
    else:
        reason = None
    if reason is not None:
        findings.append(
            ratchet_finding(
                RAT_FILE_POLICY_WEAKENED,
                policy_path,
                f"{parent}.kind",
                reason,
                base=base.kind,
                current=current.kind,
            )
        )
    if check_limits and current.scan:
        compare_limits(
            current.warn_bytes,
            current.hard_bytes,
            base.warn_bytes,
            base.hard_bytes,
            RAT_FILE_LIMIT_INCREASED,
            policy_path,
            parent,
            findings,
        )


def _compare_new_scanned_rule(
    current: FileRule,
    base_rules: tuple[FileRule, ...],
    policy_path: str,
    parent: str,
    findings: list[Diagnostic],
    *,
    check_limits: bool,
    check_structure: bool,
) -> None:
    overlapping = tuple(
        base for base in base_rules if base.scan and _rule_patterns_overlap(current, base)
    )
    if (
        check_structure
        and any(base.kind is FileKind.AUTHORED for base in overlapping)
        and current.kind is not FileKind.AUTHORED
    ):
        findings.append(
            ratchet_finding(
                RAT_FILE_POLICY_WEAKENED,
                policy_path,
                f"{parent}.kind",
                "authored_classification_removed",
                base=FileKind.AUTHORED,
                current=current.kind,
            )
        )
    if check_limits:
        for base in overlapping:
            compare_limits(
                current.warn_bytes,
                current.hard_bytes,
                base.warn_bytes,
                base.hard_bytes,
                RAT_FILE_LIMIT_INCREASED,
                policy_path,
                parent,
                findings,
                reason_prefix="new_scanned_rule_",
            )


def _compare_overrides(
    current: Policy,
    base: Policy,
    policy_path: str,
    findings: list[Diagnostic],
) -> None:
    if not base.ratchet.forbid_limit_increases:
        return
    current_by_selector = {
        selector_key(item.selector): (index, item)
        for index, item in enumerate(current.path_overrides)
    }
    base_by_selector = {
        selector_key(item.selector): (index, item)
        for index, item in enumerate(base.path_overrides)
    }
    for key, (_base_index, base_override) in base_by_selector.items():
        selected = current_by_selector.get(key)
        if selected is None:
            findings.append(
                ratchet_finding(
                    RAT_OVERRIDE_WEAKENED,
                    policy_path,
                    "path_override",
                    "override_removed",
                    base=f"{key[0]}:{key[1]}",
                    current=None,
                )
            )
            continue
        current_index, current_override = selected
        compare_limits(
            current_override.warn_bytes,
            current_override.hard_bytes,
            base_override.warn_bytes,
            base_override.hard_bytes,
            RAT_OVERRIDE_WEAKENED,
            policy_path,
            f"path_override[{current_index}]",
            findings,
        )
    for key, (current_index, current_override) in current_by_selector.items():
        if key in base_by_selector:
            continue
        for _base_index, base_override in base_by_selector.values():
            if _override_can_displace(current_override, base_override) and (
                current_override.warn_bytes > base_override.warn_bytes
                or current_override.hard_bytes > base_override.hard_bytes
            ):
                findings.append(
                    ratchet_finding(
                        RAT_OVERRIDE_WEAKENED,
                        policy_path,
                        f"path_override[{current_index}]",
                        "displacing_override_added",
                        base=_selector_label(base_override.selector),
                        current=_selector_label(current_override.selector),
                    )
                )
                break


def _rule_patterns_overlap(left: FileRule, right: FileRule) -> bool:
    return any(
        not patterns_provably_disjoint(left_pattern, right_pattern)
        for left_pattern in left.patterns
        for right_pattern in right.patterns
    )


def _override_can_displace(current: PathOverride, base: PathOverride) -> bool:
    current_selector = current.selector
    base_selector = base.selector
    if isinstance(base_selector, ExactSelector):
        return False
    if isinstance(current_selector, ExactSelector):
        return match_path(compile_pattern(base_selector.pattern), current_selector.path)
    return (
        pattern_specificity(current_selector.pattern) > pattern_specificity(base_selector.pattern)
        and not patterns_provably_disjoint(current_selector.pattern, base_selector.pattern)
    )


def _selector_label(selector: Selector) -> str:
    kind, value = selector_key(selector)
    return f"{kind}:{value}"
