"""Compiled classification and effective file-policy resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections.abc import Callable
from raften.evaluation_limits import EvaluationBudget

from raften.matcher import CompiledPattern, compile_pattern, match_path, pattern_specificity
from raften.model import (
    ContextSet,
    EffectiveFilePolicy,
    ExactSelector,
    ExceptionMatch,
    FileRule,
    IntentionalException,
    OverrideMatch,
    PathOverride,
    PatternSpecificity,
    Policy,
    RuleMatch,
)


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    rule_index: int
    rule: FileRule
    patterns: tuple[CompiledPattern, ...]


@dataclass(frozen=True, slots=True)
class _CompiledOverride:
    override_index: int
    override: PathOverride
    pattern: CompiledPattern | None
    specificity: PatternSpecificity | None


@dataclass(frozen=True, slots=True)
class _CompiledException:
    exception_index: int
    exception: IntentionalException
    pattern: CompiledPattern | None
    specificity: PatternSpecificity | None


@dataclass(frozen=True, slots=True)
class CompiledContextSet:
    context_index: int
    context: ContextSet
    patterns: tuple[CompiledPattern, ...]


@dataclass(frozen=True, slots=True)
class CompiledSizePolicy:
    policy: Policy
    rules: tuple[_CompiledRule, ...]
    overrides: tuple[_CompiledOverride, ...]
    exceptions: tuple[_CompiledException, ...]
    contexts: tuple[CompiledContextSet, ...]
    budget: EvaluationBudget | None = None


def compile_size_policy(policy: Policy, *, budget: EvaluationBudget | None = None) -> CompiledSizePolicy:
    """Compile every policy pattern once for deterministic repeated evaluation."""

    patterns: dict[str, CompiledPattern] = {}

    def compile_once(source: str) -> CompiledPattern:
        if source not in patterns:
            patterns[source] = compile_pattern(source)
        return patterns[source]

    return CompiledSizePolicy(
        policy=policy,
        rules=tuple(
            _CompiledRule(
                rule_index,
                rule,
                tuple(compile_once(pattern) for pattern in rule.patterns),
            )
            for rule_index, rule in enumerate(policy.file_rules)
        ),
        overrides=tuple(
            _compile_override(override_index, override, compile_once)
            for override_index, override in enumerate(policy.path_overrides)
        ),
        exceptions=tuple(
            _compile_exception(exception_index, exception, compile_once)
            for exception_index, exception in enumerate(policy.exceptions.records)
        ),
        contexts=tuple(
            CompiledContextSet(
                context_index,
                context,
                tuple(compile_once(pattern) for pattern in context.patterns),
            )
            for context_index, context in enumerate(policy.context_sets)
        ),
        budget=budget,
    )


def resolve_effective_policy(
    compiled: CompiledSizePolicy,
    path: str,
    evaluation_date: date,
) -> EffectiveFilePolicy | None:
    """Resolve first-match classification, override precedence, and exceptions."""

    budget = compiled.budget or EvaluationBudget()
    budget.selectors(file_selector_count(compiled))
    budget.matcher.charge(file_selector_count(compiled) * (len(path) + 1))
    rule_match = _match_rule(compiled.rules, path, budget)
    if rule_match is None:
        return None
    override_match = _match_override(compiled.overrides, path, budget)
    ordinary_scan = rule_match.rule.scan
    if ordinary_scan:
        ordinary_warn = rule_match.rule.warn_bytes
        ordinary_hard = rule_match.rule.hard_bytes
        if override_match is not None:
            ordinary_warn = _narrow_limit(
                ordinary_warn,
                override_match.override.warn_bytes,
            )
            ordinary_hard = _narrow_limit(
                ordinary_hard,
                override_match.override.hard_bytes,
            )
    else:
        ordinary_warn = None
        ordinary_hard = None

    exception_match = _match_exception(compiled.exceptions, path, evaluation_date, budget)
    effective_scan = ordinary_scan
    effective_warn = ordinary_warn
    effective_hard = ordinary_hard
    if exception_match is not None:
        exception = exception_match.exception
        if exception.scan is not None:
            effective_scan = exception.scan
        if exception.warn_bytes is not None and exception.hard_bytes is not None:
            effective_warn = exception.warn_bytes
            effective_hard = exception.hard_bytes
    if not effective_scan:
        effective_warn = None
        effective_hard = None

    return EffectiveFilePolicy(
        rule_match=rule_match,
        override_match=override_match,
        exception_match=exception_match,
        kind=rule_match.rule.kind,
        ordinary_scan=ordinary_scan,
        ordinary_warn_bytes=ordinary_warn,
        ordinary_hard_bytes=ordinary_hard,
        effective_scan=effective_scan,
        effective_warn_bytes=effective_warn,
        effective_hard_bytes=effective_hard,
    )


def effective_policy_error(policy: EffectiveFilePolicy) -> str | None:
    """Return the shared fail-closed validation error for one resolved policy."""

    exception = policy.exception_match
    if (
        exception is not None
        and exception.exception.warn_bytes is not None
        and not policy.effective_scan
    ):
        return "exception byte limits do not govern an effectively unscanned path"
    if policy.effective_scan and (
        policy.effective_warn_bytes is None or policy.effective_hard_bytes is None
    ):
        return "effective scanned policy has no complete byte limits"
    return None


def context_names_for_path(compiled: CompiledSizePolicy, path: str) -> tuple[str, ...]:
    budget = compiled.budget or EvaluationBudget()
    checks = sum(len(item.context.paths) + len(item.patterns) for item in compiled.contexts)
    budget.selectors(checks)
    budget.matcher.charge(checks * (len(path) + 1))
    return tuple(
        item.context.name
        for item in compiled.contexts
        if path in item.context.paths
        or any(match_path(pattern, path, budget=budget.matcher) for pattern in item.patterns)
    )


def exception_is_expired(exception: IntentionalException, evaluation_date: date) -> bool:
    return exception.expires_on is not None and evaluation_date > exception.expires_on


def _compile_override(override_index: int, override: PathOverride,
                      compile_once: Callable[[str], CompiledPattern]) -> _CompiledOverride:
    selector = override.selector
    if isinstance(selector, ExactSelector):
        return _CompiledOverride(override_index, override, None, None)
    return _CompiledOverride(
        override_index,
        override,
        compile_once(selector.pattern),
        pattern_specificity(selector.pattern),
    )


def _compile_exception(
    exception_index: int,
    exception: IntentionalException,
    compile_once: Callable[[str], CompiledPattern],
) -> _CompiledException:
    selector = exception.selector
    if isinstance(selector, ExactSelector):
        return _CompiledException(exception_index, exception, None, None)
    return _CompiledException(
        exception_index,
        exception,
        compile_once(selector.pattern),
        pattern_specificity(selector.pattern),
    )


def _match_rule(rules: tuple[_CompiledRule, ...], path: str,
                budget: EvaluationBudget) -> RuleMatch | None:
    for item in rules:
        for pattern_index, pattern in enumerate(item.patterns):
            if match_path(pattern, path, budget=budget.matcher):
                return RuleMatch(
                    item.rule_index,
                    pattern_index,
                    pattern.source,
                    item.rule,
                )
    return None


def _match_override(
    overrides: tuple[_CompiledOverride, ...],
    path: str,
    budget: EvaluationBudget,
) -> OverrideMatch | None:
    for item in overrides:
        selector = item.override.selector
        if isinstance(selector, ExactSelector) and selector.path == path:
            return OverrideMatch(item.override_index, item.override, None)
    candidates = tuple(
        item
        for item in overrides
        if item.pattern is not None and match_path(item.pattern, path, budget=budget.matcher)
    )
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: item.specificity)
    return OverrideMatch(
        selected.override_index,
        selected.override,
        selected.specificity,
    )


def _match_exception(
    exceptions: tuple[_CompiledException, ...],
    path: str,
    evaluation_date: date,
    budget: EvaluationBudget,
) -> ExceptionMatch | None:
    active = tuple(
        item
        for item in exceptions
        if not exception_is_expired(item.exception, evaluation_date)
    )
    for item in active:
        selector = item.exception.selector
        if isinstance(selector, ExactSelector) and selector.path == path:
            return ExceptionMatch(item.exception_index, item.exception, None)
    candidates = tuple(
        item
        for item in active
        if item.pattern is not None and match_path(item.pattern, path, budget=budget.matcher)
    )
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: item.specificity)
    return ExceptionMatch(
        selected.exception_index,
        selected.exception,
        selected.specificity,
    )


def _narrow_limit(rule_limit: int | None, override_limit: int) -> int | None:
    return None if rule_limit is None else min(rule_limit, override_limit)


def file_selector_count(compiled: CompiledSizePolicy) -> int:
    return (sum(len(item.patterns) for item in compiled.rules)
            + len(compiled.overrides) + len(compiled.exceptions))


def preflight_size_work(compiled: CompiledSizePolicy, path_count: int, *,
                        contexts: bool = True, extra_checks: int = 0) -> None:
    context_patterns = {pattern.source for item in compiled.contexts for pattern in item.patterns}
    count = path_count * (file_selector_count(compiled) + (len(context_patterns) if contexts else 0))
    if contexts:
        count += sum(len(item.context.paths) for item in compiled.contexts)
    count += extra_checks
    (compiled.budget or EvaluationBudget()).preflight(count)
