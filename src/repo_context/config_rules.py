"""Strict parsing for ordered file rules and byte-limit overrides."""

from __future__ import annotations

from typing import Any

from repo_context.config_validation import Validator
from repo_context.config_values import (
    parse_enum,
    parse_limits,
    parse_pattern_list,
    parse_selector,
)
from repo_context.diagnostics import (
    CFG_AMBIGUOUS_OVERRIDE,
    CFG_CATCH_ALL,
    CFG_DUPLICATE_NAME,
    CFG_DUPLICATE_SELECTOR,
    CFG_INCONSISTENT,
    CFG_MISSING_KEY,
)
from repo_context.matcher import pattern_specificity, patterns_provably_disjoint
from repo_context.model import (
    ExactSelector,
    FileKind,
    FileRule,
    PathOverride,
    PatternSelector,
)


def parse_file_rules(root: dict[str, Any], validator: Validator) -> tuple[FileRule, ...]:
    records = validator.array_of_tables(root, "file_rule", required=True)
    rules: list[tuple[int, FileRule]] = []
    seen_names: dict[str, int] = {}
    seen_patterns: dict[str, int] = {}
    for index, table in records:
        parent = f"file_rule[{index}]"
        validator.keys(
            table,
            parent=parent,
            allowed=frozenset(
                {"name", "patterns", "kind", "scan", "warn_bytes", "hard_bytes", "reason"}
            ),
            required=frozenset({"name", "patterns", "kind", "scan"}),
        )
        name = validator.string(table, "name", parent=parent, required=False, human=True)
        patterns = parse_pattern_list(
            validator,
            table,
            "patterns",
            parent=parent,
            required=False,
            nonempty=True,
        )
        kind = parse_enum(validator, table, "kind", parent, FileKind, required=False)
        scan = validator.boolean(table, "scan", parent=parent, required=False)
        reason = validator.string(table, "reason", parent=parent, required=False, human=True)

        warn_bytes: int | None = None
        hard_bytes: int | None = None
        if scan is True:
            warn_bytes, hard_bytes = parse_limits(validator, table, parent, required=True)
        elif scan is False:
            warn_bytes, hard_bytes = parse_limits(validator, table, parent, required=False)
            if warn_bytes is not None or hard_bytes is not None:
                validator.add(
                    CFG_INCONSISTENT,
                    parent,
                    "unscanned file rules may not declare byte limits",
                )
            if "reason" not in table:
                validator.add(
                    CFG_MISSING_KEY,
                    f"{parent}.reason",
                    "unscanned file rules require a reason",
                )
            if kind is FileKind.AUTHORED:
                validator.add(
                    CFG_INCONSISTENT,
                    f"{parent}.scan",
                    "authored files may not be excluded by a file rule",
                    hint="Use a generated, vendored, fixture, or legal classification.",
                )

        if name is not None:
            previous = seen_names.get(name)
            if previous is not None:
                validator.add(
                    CFG_DUPLICATE_NAME,
                    f"{parent}.name",
                    f"duplicate file rule name {name!r}",
                    details=(("first_index", previous),),
                )
            else:
                seen_names[name] = index

        if patterns is not None:
            for pattern_index, pattern in enumerate(patterns):
                previous = seen_patterns.get(pattern)
                if previous is not None:
                    validator.add(
                        CFG_DUPLICATE_SELECTOR,
                        f"{parent}.patterns[{pattern_index}]",
                        f"file rule pattern {pattern!r} is already declared",
                        details=(("first_rule_index", previous),),
                    )
                else:
                    seen_patterns[pattern] = index

        if (
            name is not None
            and patterns is not None
            and kind is not None
            and scan is not None
            and (not scan or (warn_bytes is not None and hard_bytes is not None))
        ):
            rules.append(
                (
                    index,
                    FileRule(
                        name=name,
                        patterns=patterns,
                        kind=kind,
                        scan=scan,
                        warn_bytes=warn_bytes,
                        hard_bytes=hard_bytes,
                        reason=reason,
                    ),
                )
            )

    catch_alls = [(index, rule) for index, rule in rules if rule.patterns == ("**",)]
    if len(catch_alls) != 1:
        validator.add(
            CFG_CATCH_ALL,
            "file_rule",
            "policy must contain exactly one dedicated catch-all rule",
            details=(("count", len(catch_alls)),),
        )
    else:
        catch_index, catch_rule = catch_alls[0]
        if not records or catch_index != records[-1][0]:
            validator.add(
                CFG_CATCH_ALL,
                f"file_rule[{catch_index}].patterns",
                "the catch-all file rule must be last",
            )
        if catch_rule.kind is not FileKind.AUTHORED or not catch_rule.scan:
            validator.add(
                CFG_CATCH_ALL,
                f"file_rule[{catch_index}]",
                "the catch-all file rule must be scanned and authored",
            )
    return tuple(rule for _index, rule in rules)


def parse_path_overrides(
    root: dict[str, Any],
    validator: Validator,
) -> tuple[PathOverride, ...]:
    result: list[tuple[int, PathOverride]] = []
    exact_selectors: dict[str, int] = {}
    pattern_selectors: list[tuple[int, str]] = []
    for index, table in validator.array_of_tables(root, "path_override"):
        parent = f"path_override[{index}]"
        validator.keys(
            table,
            parent=parent,
            allowed=frozenset({"path", "pattern", "warn_bytes", "hard_bytes"}),
            required=frozenset({"warn_bytes", "hard_bytes"}),
        )
        selector = parse_selector(validator, table, parent)
        warn_bytes, hard_bytes = parse_limits(validator, table, parent, required=False)
        if isinstance(selector, ExactSelector):
            previous = exact_selectors.get(selector.path)
            if previous is not None:
                validator.add(
                    CFG_DUPLICATE_SELECTOR,
                    f"{parent}.path",
                    f"duplicate exact override for {selector.path!r}",
                    details=(("first_index", previous),),
                )
            else:
                exact_selectors[selector.path] = index
        elif isinstance(selector, PatternSelector):
            duplicate = next(
                (
                    other_index
                    for other_index, pattern in pattern_selectors
                    if pattern == selector.pattern
                ),
                None,
            )
            if duplicate is not None:
                validator.add(
                    CFG_DUPLICATE_SELECTOR,
                    f"{parent}.pattern",
                    f"duplicate pattern override {selector.pattern!r}",
                    details=(("first_index", duplicate),),
                )
            else:
                for other_index, other_pattern in pattern_selectors:
                    if (
                        pattern_specificity(other_pattern) == pattern_specificity(selector.pattern)
                        and not patterns_provably_disjoint(other_pattern, selector.pattern)
                    ):
                        validator.add(
                            CFG_AMBIGUOUS_OVERRIDE,
                            f"{parent}.pattern",
                            "equal-specificity pattern overrides are not provably disjoint",
                            details=(("other_index", other_index), ("other_pattern", other_pattern)),
                        )
                pattern_selectors.append((index, selector.pattern))
        if selector is not None and warn_bytes is not None and hard_bytes is not None:
            result.append((index, PathOverride(selector, warn_bytes, hard_bytes)))
    return tuple(item for _index, item in result)
