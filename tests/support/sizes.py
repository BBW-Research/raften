from __future__ import annotations

from dataclasses import replace
from datetime import date

from raften.config import starter_policy
from raften.model import (
    ContextSet,
    FileKind,
    FileRule,
    InventoryEntry,
    InventorySource,
    WorktreeKind,
)


TODAY = date(2026, 9, 1)


def regular(
    path: str,
    size: int,
    *,
    source: InventorySource = InventorySource.TRACKED,
) -> InventoryEntry:
    return InventoryEntry(path, source, WorktreeKind.REGULAR, size_bytes=size)


def policy_with(
    *,
    warn_bytes: int = 10,
    hard_bytes: int = 20,
    context_sets: tuple[ContextSet, ...] = (),
    file_rules: tuple[FileRule, ...] | None = None,
):
    selected_rules = (
        file_rules
        if file_rules is not None
        else (
            FileRule(
                "authored",
                ("**",),
                FileKind.AUTHORED,
                True,
                warn_bytes,
                hard_bytes,
            ),
        )
    )
    return replace(
        starter_policy(),
        file_rules=selected_rules,
        path_overrides=(),
        context_sets=context_sets,
    )
