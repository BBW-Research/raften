"""Strict parsing for entrypoints, context sets, and governed exceptions."""

from __future__ import annotations

from typing import Any

from raften.config_validation import Validator
from raften.config_values import (
    parse_limits,
    parse_path_list,
    parse_path_value,
    parse_pattern_list,
    parse_selector,
)
from raften.diagnostics import (
    CFG_AMBIGUOUS_OVERRIDE,
    CFG_DUPLICATE_NAME,
    CFG_DUPLICATE_SELECTOR,
    CFG_INCONSISTENT,
    CFG_MISSING_KEY,
    CFG_VALUE,
    EXC_BROAD_SELECTOR,
)
from raften.matcher import pattern_specificity, patterns_provably_disjoint
from raften.model import (
    ContextSet,
    Entrypoint,
    ExactSelector,
    IntentionalException,
    PatternSelector,
)


def parse_entrypoints(root: dict[str, Any], validator: Validator) -> tuple[Entrypoint, ...]:
    result: list[Entrypoint] = []
    seen_paths: dict[str, int] = {}
    for index, table in validator.array_of_tables(root, "entrypoint"):
        parent = f"entrypoint[{index}]"
        validator.keys(
            table,
            parent=parent,
            allowed=frozenset({"path", "required_targets"}),
            required=frozenset({"path", "required_targets"}),
        )
        path = parse_path_value(validator, table, "path", parent, required=False)
        targets = parse_path_list(
            validator,
            table,
            "required_targets",
            parent=parent,
            required=False,
            nonempty=True,
        )
        if path is not None:
            previous = seen_paths.get(path)
            if previous is not None:
                validator.add(
                    CFG_DUPLICATE_SELECTOR,
                    f"{parent}.path",
                    f"duplicate entrypoint {path!r}",
                    details=(("first_index", previous),),
                )
            else:
                seen_paths[path] = index
            if targets is not None and path in targets:
                validator.add(
                    CFG_INCONSISTENT,
                    f"{parent}.required_targets",
                    "an entrypoint may not require a link to itself",
                )
        if path is not None and targets is not None:
            result.append(Entrypoint(path, targets))
    return tuple(result)


def parse_context_sets(root: dict[str, Any], validator: Validator) -> tuple[ContextSet, ...]:
    result: list[ContextSet] = []
    seen_names: dict[str, int] = {}
    for index, table in validator.array_of_tables(root, "context_set"):
        parent = f"context_set[{index}]"
        validator.keys(
            table,
            parent=parent,
            allowed=frozenset({"name", "paths", "patterns", "warn_bytes", "hard_bytes"}),
            required=frozenset({"name", "warn_bytes", "hard_bytes"}),
        )
        name = validator.string(table, "name", parent=parent, required=False, human=True)
        paths = parse_path_list(
            validator,
            table,
            "paths",
            parent=parent,
            required=False,
            nonempty=False,
        ) or ()
        patterns = parse_pattern_list(
            validator,
            table,
            "patterns",
            parent=parent,
            required=False,
            nonempty=False,
            narrow=True,
        ) or ()
        warn_bytes, hard_bytes = parse_limits(validator, table, parent, required=False)
        if not paths and not patterns:
            validator.add(
                CFG_VALUE,
                parent,
                "a context set must declare at least one path or narrow pattern",
            )
        if name is not None:
            previous = seen_names.get(name)
            if previous is not None:
                validator.add(
                    CFG_DUPLICATE_NAME,
                    f"{parent}.name",
                    f"duplicate context set name {name!r}",
                    details=(("first_index", previous),),
                )
            else:
                seen_names[name] = index
        if name is not None and (paths or patterns) and warn_bytes is not None and hard_bytes is not None:
            result.append(ContextSet(name, paths, patterns, warn_bytes, hard_bytes))
    return tuple(result)


def parse_exception_records(
    exceptions_table: dict[str, Any],
    validator: Validator,
) -> tuple[IntentionalException, ...]:
    result: list[IntentionalException] = []
    seen_selectors: dict[tuple[str, str], int] = {}
    pattern_selectors: list[tuple[int, str]] = []
    for index, table in validator.array_of_tables(
        exceptions_table,
        "record",
        parent="exceptions",
    ):
        parent = f"exceptions.record[{index}]"
        validator.keys(
            table,
            parent=parent,
            allowed=frozenset(
                {
                    "path",
                    "pattern",
                    "owner",
                    "rationale",
                    "tracking_reference",
                    "created_on",
                    "expires_on",
                    "scan",
                    "warn_bytes",
                    "hard_bytes",
                }
            ),
            required=frozenset({"owner", "rationale", "tracking_reference", "created_on"}),
        )
        selector = parse_selector(
            validator,
            table,
            parent,
            narrow=True,
            narrow_code=EXC_BROAD_SELECTOR,
        )
        owner = validator.string(table, "owner", parent=parent, required=False, human=True)
        rationale = validator.string(
            table,
            "rationale",
            parent=parent,
            required=False,
            human=True,
        )
        tracking = validator.string(
            table,
            "tracking_reference",
            parent=parent,
            required=False,
            human=True,
        )
        created_on = validator.local_date(table, "created_on", parent=parent, required=False)
        expires_on = validator.local_date(table, "expires_on", parent=parent, required=False)
        scan = validator.boolean(table, "scan", parent=parent, required=False)

        warn_present = "warn_bytes" in table
        hard_present = "hard_bytes" in table
        if warn_present != hard_present:
            missing = "hard_bytes" if warn_present else "warn_bytes"
            validator.add(
                CFG_MISSING_KEY,
                f"{parent}.{missing}",
                "exception replacement thresholds must be declared together",
            )
        warn_bytes, hard_bytes = parse_limits(validator, table, parent, required=False)
        if scan is None and not warn_present and not hard_present:
            validator.add(
                CFG_INCONSISTENT,
                parent,
                "an intentional exception must replace scan behavior or byte limits",
            )
        if scan is False and (warn_present or hard_present):
            validator.add(
                CFG_INCONSISTENT,
                parent,
                "an unscanned exception may not declare byte limits",
            )
        if created_on is not None and expires_on is not None and expires_on < created_on:
            validator.add(
                CFG_INCONSISTENT,
                f"{parent}.expires_on",
                "exception expiry may not precede its creation date",
            )

        if selector is not None:
            selector_key = (
                ("path", selector.path)
                if isinstance(selector, ExactSelector)
                else ("pattern", selector.pattern)
            )
            previous = seen_selectors.get(selector_key)
            if previous is not None:
                validator.add(
                    CFG_DUPLICATE_SELECTOR,
                    f"{parent}.{selector_key[0]}",
                    "duplicate intentional exception selector",
                    details=(("first_index", previous),),
                )
            else:
                seen_selectors[selector_key] = index
                if isinstance(selector, PatternSelector):
                    for other_index, other_pattern in pattern_selectors:
                        if (
                            pattern_specificity(other_pattern)
                            == pattern_specificity(selector.pattern)
                            and not patterns_provably_disjoint(
                                other_pattern,
                                selector.pattern,
                            )
                        ):
                            validator.add(
                                CFG_AMBIGUOUS_OVERRIDE,
                                f"{parent}.pattern",
                                "equal-specificity exception patterns are not provably disjoint",
                                details=(
                                    ("other_index", other_index),
                                    ("other_pattern", other_pattern),
                                ),
                            )
                    pattern_selectors.append((index, selector.pattern))

        if all(
            value is not None
            for value in (selector, owner, rationale, tracking, created_on)
        ) and (scan is not None or (warn_bytes is not None and hard_bytes is not None)):
            result.append(
                IntentionalException(
                    selector=selector,
                    owner=owner,
                    rationale=rationale,
                    tracking_reference=tracking,
                    created_on=created_on,
                    expires_on=expires_on,
                    scan=scan,
                    warn_bytes=warn_bytes,
                    hard_bytes=hard_bytes,
                )
            )
    return tuple(result)
